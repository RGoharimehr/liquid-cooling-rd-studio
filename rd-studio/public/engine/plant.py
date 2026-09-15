"""Two hydronic plant layouts, external equipment ports and functional paths."""
from math import cos,sin,radians,dist


def _measure(points):
    length=sum(dist(p,q) for p,q in zip(points,points[1:]))
    return length,max(0,len(points)-2)


def _plan_routes(b,c,links,service):
    """Ask the lane router for better waypoints than the deterministic lanes.

    Returns {key: points} for the links it improved. A link is only replaced when
    the search actually beats the lane it would otherwise use, measured with the
    same cost, so enabling the optimizer can never lengthen a run. Anything it
    cannot place legally is left alone and reported.
    """
    from route_lanes import LaneRouter,Request,obstacles_from_graph,_collapse,_validate
    ends=[b.xyz(a) for _,a,d,_,_,_ in links]+[b.xyz(d) for _,a,d,_,_,_ in links]
    levels=sorted({round(p[2],3) for p in ends})
    levels+= [z+1.2 for z in levels]
    router=LaneRouter(
        obstacles_from_graph(b.g,b.xyz,pipe_half_m=c.route_pipe_clearance_m,
            equipment_pad_m=c.route_equipment_clearance_m,
            overfly_top_m=c.ceiling_height_m if c.route_avoid_overfly else None),
        bend_radius_m=c.bend_radius_m,bend_cost_m=c.route_bend_cost_m,
        bundle_discount=c.route_bundle_discount,corridor_m=c.route_corridor_m,
        z_levels=sorted(set(levels)))
    requests=[Request(key=key,start=tuple(b.xyz(a)),end=tuple(b.xyz(d)),
                      start_dir=adir,end_dir=ddir,lead_m=2.0,
                      clearance_m=c.route_pipe_clearance_m,service=service)
              for key,a,d,adir,ddir,_ in links]
    results=router.route(requests)
    report=b.g['metadata'].setdefault('route_optimizer',{}).setdefault('links',[])
    chosen={}
    for key,a,d,adir,ddir,fallback in links:
        res=results[key]
        base_pts=_collapse([tuple(b.xyz(a))]+[tuple(x) for x in fallback]+[tuple(b.xyz(d))])
        base_len,base_bends=_measure(base_pts)
        base_cost=base_len+base_bends*c.route_bend_cost_m
        row={'link':key,'service':service,'status':res.status,
             'lane_m':round(base_len,3),'lane_bends':base_bends,
             'bound_m':round(res.bound_m,3)}
        if res.status=='routed':
            cost=res.length_m+res.bends*c.route_bend_cost_m
            row.update(routed_m=round(res.length_m,3),routed_bends=res.bends,
                       shared_m=round(res.shared_m,3),
                       gap_over_bound=round(res.length_m/res.bound_m-1,4) if res.bound_m else None)
            if cost<base_cost-1e-6:
                chosen[key]=res.waypoints
                row['chosen']='optimized'
                row['saved_m']=round(base_len-res.length_m,3)
            else:
                row['chosen']='lane'
                row['reason']='deterministic lane already at or below the optimised cost'
        else:
            row['chosen']='lane'
            row['reason']=res.reason
        report.append(row)
    return chosen


def add_plant(b):
    c=b.c;px,py,pz=c.plant_origin_x_m,c.plant_origin_y_m,c.plant_elevation_m
    z=pz+c.plant_header_elevation_m;zr=z+c.return_elevation_offset_m
    begin_nodes=len(b.g['nodes']);begin_components=len(b.g['components'])
    group=(None,None,None);basis=b.fixed(0);equipment=[]
    def node(p,service,kind='port'):return b.node(p,service,kind)
    def unit(cid,kind,center,size,connections,spare=False):
        comp={'id':cid,'tag':cid,'kind':kind,'service':'EQUIPMENT','level':'main','ports':[], 'row':None,'rack':None,'cdu':None,
            'center_m':center,'size_m':size,'schematic_group':'PLANT','hydraulic_element':True,'status':'conceptual',
            'duty_role':'spare' if spare else 'duty','port_directions':{},'functions':[kind],'assumptions':['Generic equipment envelope; manufacturer selection and performance unassigned.']}
        for service,a,d,ekind in connections:
            comp['ports'] += [a,d];comp['port_directions'].update({a:[0,0,1],d:[0,0,1]})
        b.g['components'].append(comp)
        for service,a,d,ekind in connections:
            comp['service']=service;e=b.edge(comp,a,d,ekind,basis);e['internal']=True
        comp['service']='EQUIPMENT';comp['circuit_id']='MULTI' if len(connections)>1 else connections[0][0];equipment.append(comp)
        return comp
    # Collector arms point toward the equipment; last branch is an elbow.
    def bank(taps,service,y,height,direction):
        prev=None;first=None
        for i,(port,x,incoming) in enumerate(taps):
            common,other,branch=b.junction([x,y,height],[1,0,0],[0,direction,0],service,'main',[basis,basis],group,last=i==len(taps)-1,split=True)
            if prev:b.route(prev,common,service,'main',basis,group)
            if first is None:first=common
            prev=other
            target=b.xyz(port)
            if incoming:
                a,_=b.part(branch,[x,y+direction*.65,height],'isolation_valve',service,'main',basis,group)
                # Optional strainer is external and accessible before inlet.
                a,_=b.part(a,[x,y+direction*.95,height],'strainer',service,'main',basis,group)
                b.route_path(a,port,[[x,target[1],height]],service,'main',basis,group)
            else:
                a=node([x,y+direction*.65,height],service)
                b.route_path(port,a,[[x,target[1],height]],service,'main',basis,group)
                b.component('isolation_valve',[a,branch],service,'main',basis,group)
        return first
    supply=[];ret=[];cw_in=[];cw_out=[]
    for i in range(c.chiller_count):
        x=px+i*c.plant_equipment_pitch_m
        a=node([x-.7,py+c.chiller_depth_m/2,pz+c.chiller_height_m],'FWS','equipment_port');d=node([x+.7,py+c.chiller_depth_m/2,pz+c.chiller_height_m],'FWS','equipment_port')
        pairs=[('FWS',a,d,'chiller_evaporator')];ret.append((a,x-.7,True));supply.append((d,x+.7,False))
        if c.plant_type=='water_cooled':
            ca=node([x-.7,py-c.chiller_depth_m/2,pz+c.chiller_height_m],'CWS','equipment_port');cd=node([x+.7,py-c.chiller_depth_m/2,pz+c.chiller_height_m],'CWS','equipment_port')
            pairs.append(('CWS',ca,cd,'chiller_condenser'));cw_in.append((ca,x-.7,True));cw_out.append((cd,x+.7,False))
        unit(f'CHILLER-{i+1:02}','chiller',[x,py,pz+c.chiller_height_m/2],[c.chiller_width_m,c.chiller_depth_m,c.chiller_height_m],pairs,i>=c.chiller_count-c.chiller_spares)
    s=bank(supply,'FWS',py+4,z,-1);r=bank(ret,'FWS',py+6,zr,-1)
    # A pump bank has parallel branches, with inlet/outlet collectors in Y.
    def pumps(service,count,spares,origin):
        x,y=origin;ins=[];outs=[]
        for i in range(count):
            yy=y+i*3
            a=node([x-.7,yy,pz+c.plant_pump_height_m],'FWS' if service=='FWS' else 'CWS','equipment_port');d=node([x+.7,yy,pz+c.plant_pump_height_m],service,'equipment_port')
            unit(service+f'-PUMP-{i+1:02}','pump',[x,yy,pz+c.plant_pump_height_m/2],[c.plant_pump_width_m,c.plant_pump_depth_m,c.plant_pump_height_m],[(service,a,d,'pump')],i>=count-spares)
            ins.append(a);outs.append(d)
        endpoints=[]
        for ports,hx,zz in [(ins,x-2,z),(outs,x+2,z)]:
            first=None;prev=None
            for i,p in enumerate(ports):
                yy=y+i*3;direction=1 if hx<x else -1
                common,other,branch=b.junction([hx,yy,zz],[0,1,0],[direction,0,0],service,'main',[basis,basis],group,last=i==len(ports)-1)
                if prev:b.route(prev,common,service,'main',basis,group)
                if first is None:first=common
                prev=other;tx,ty,tz=b.xyz(p)
                if ports is ins:
                    v,_=b.part(branch,[hx+direction*.6,yy,zz],'isolation_valve',service,'main',basis,group)
                    b.route_path(v,p,[[tx,yy,zz]],service,'main',basis,group)
                else:
                    q=node([hx+direction*.9,yy,zz],service);b.route_path(p,q,[[tx,yy,zz]],service,'main',basis,group)
                    v,_=b.part(q,[hx+direction*.6,yy,zz],'check_valve',service,'main',basis,group)
                    b.component('isolation_valve',[v,branch],service,'main',basis,group)
            endpoints.append(first)
        return endpoints
    # Pumps in a separate corridor west of the chiller bank.
    pi,po=pumps('FWS',c.fws_pump_count,c.fws_pump_spares,(px-8,py))
    def connect(a,d,points,service):b.route_path(a,d,points,service,'main',basis,group)
    def emit(links,service):
        # The optimizer proposes; route_path still builds every component, and a
        # proposal that will not place legally falls back to the fixed lane.
        chosen=_plan_routes(b,c,links,service) if c.route_optimizer else {}
        for key,a,d,adir,ddir,fallback in links:
            points=chosen.get(key,fallback)
            try:
                b.route_path(a,d,points,service,'main',basis,group)
            except ValueError:
                if key not in chosen:raise
                b.g['metadata']['route_optimizer'].setdefault('rejected',[]).append(key)
                b.route_path(a,d,fallback,service,'main',basis,group)
    ax,ay,az=b.xyz(s);ix,iy,iz=b.xyz(pi)
    connect(s,pi,[[px-12,ay,az],[px-12,py-3,az],[px-12,py-3,iz],[ix,py-3,iz]],'FWS')
    # Put expansion/air separation on the pump suction header as actual ports.
    host=next(comp for comp in reversed(b.g['components']) if comp['kind']=='pipe' and comp['service']=='FWS' and
        abs(b.xyz(comp['ports'][0])[1]-(py+4))<1e-6 and abs(b.xyz(comp['ports'][1])[1]-(py+4))<1e-6 and
        abs(b.xyz(comp['ports'][0])[0]-b.xyz(comp['ports'][1])[0])>5)
    first,last=host['ports'];a0=b.xyz(first);a1=b.xyz(last);sign=1 if a1[0]>a0[0] else -1
    center=[(a0[0]+a1[0])/2,py+4,z]
    b.g['components'].remove(host);b.g['edges']=[e for e in b.g['edges'] if e['component_id']!=host['id']]
    common,other,branch=b.junction(center,[sign,0,0],[0,1,0],'FWS','main',[basis,basis],group)
    b.route(first,common,'FWS','main',basis,group)
    sep_end=node([b.xyz(other)[0]+sign*.6,py+4,z],'FWS')
    b.component('air_separator',[other,sep_end],'FWS','main',basis,group,functions=['air_separation'],status='Vendor selection required')
    b.route(sep_end,last,'FWS','main',basis,group)
    vessel_port=node([center[0],py+6,pz+1.2],'FWS','equipment_port')
    valve_top=node([center[0],py+6,pz+2],'FWS')
    b.route_path(branch,valve_top,[[center[0],py+6,z]],'FWS','main',basis,group)
    valve_bottom,_=b.part(valve_top,[center[0],py+6,pz+1.6],'isolation_valve','FWS','main',basis,group)
    b.route(valve_bottom,vessel_port,'FWS','main',basis,group)
    b.g['components'].append({'id':'FWS-EXPANSION','tag':'FWS-EXPANSION','kind':'expansion_tank','service':'FWS','circuit_id':'FWS','level':'main','ports':[vessel_port],
        'center_m':[center[0],py+6,pz+.6],'size_m':[.6,.6,1.2],'hydraulic_element':True,'port_directions':{vessel_port:[0,0,1]},
        'status':'conceptual','assumptions':['Connected expansion provision; volume, charge pressure and connection size require vendor selection.']})
    if c.plant_type=='water_cooled':
        # Condenser-water circuit remains in plant-local coordinates until rotation.
        ci=bank(cw_in,'CWS',py-4,z,1);cr=bank(cw_out,'CWS',py-6,zr,1)
        t_in=[];t_out=[]
        for i in range(c.tower_count):
            x=px+i*c.plant_equipment_pitch_m;y=py-14
            a=node([x-.7,y+c.tower_depth_m/2-.5,pz+c.tower_height_m],'CWS','equipment_port');d=node([x+.7,y+c.tower_depth_m/2-.5,pz+c.tower_height_m],'CWS','equipment_port')
            unit(f'TOWER-{i+1:02}','cooling_tower',[x,y,pz+c.tower_height_m/2],[c.tower_width_m,c.tower_depth_m,c.tower_height_m],[('CWS',a,d,'cooling_tower')],i>=c.tower_count-c.tower_spares)
            t_in.append((a,x-.7,True));t_out.append((d,x+.7,False))
        ti=bank(t_in,'CWS',py-8,zr,-1);to=bank(t_out,'CWS',py-10,z,-1)
        cpi,cpo=pumps('CWS',c.cws_pump_count,c.cws_pump_spares,(px-16,py-16))
        def westlane(a,d,axial_a,axial_d,xlane,ylane):
            aa=b.xyz(a);dd=b.xyz(d);ap=[aa[k]+axial_a[k]*2 for k in range(3)];dp=[dd[k]+axial_d[k]*2 for k in range(3)]
            return [ap,[xlane,ap[1],ap[2]],[xlane,ylane,ap[2]],[xlane,ylane,dp[2]],[dp[0],ylane,dp[2]],dp]
        aa=b.xyz(cpo);dd=b.xyz(ci);high=z+1.2
        # Condenser water is one loop in three legs. Routed as a batch so a leg
        # can share a corridor already opened by the leg before it.
        emit([('CWS-chiller-to-tower',cr,ti,(-1,0,0),(-1,0,0),
               westlane(cr,ti,[-1,0,0],[-1,0,0],px-5,py-7)),
              ('CWS-tower-to-pump',to,cpi,(-1,0,0),(0,-1,0),
               westlane(to,cpi,[-1,0,0],[0,-1,0],px-21,py-20)),
              ('CWS-pump-to-chiller',cpo,ci,(0,-1,0),(-1,0,0),
               [[aa[0],aa[1]-2,aa[2]],[px-12,aa[1]-2,aa[2]],[px-12,aa[1]-2,high],
                [px-4,aa[1]-2,high],[px-4,dd[1],high],[px-4,dd[1],dd[2]]])],'CWS')
        for kind in ('makeup','blowdown'):
            b.g['metadata'].setdefault('service_interfaces',[]).append({'id':'CWS-'+kind,'kind':kind,'host':'TOWER-01','status':'Interface for detailed design; flow unassigned'})
    # Rotate plant geometry before connecting its four external interfaces.
    from zone_geometry import transform_zone_geometry,transform_zone_vector
    spec=transform_zone_geometry(b.g['nodes'][begin_nodes:],b.g['components'][begin_components:],
        [px,py,pz],c.plant_rotation_deg,c.plant_flip_x,c.plant_flip_y)
    # Use a west/south service corridor and approach all open collector ends axially.
    source=b.g['metadata']['fws_source'];sink=b.g['metadata']['fws_sink']
    # The hall hands over on the side facing the plant, so the service corridor
    # has to be on that side too: approach the interface from outside it, never
    # from across the hall.
    outward=b.g['metadata'].get('fws_interface_dir',[0,1,0])
    oy=1 if outward[1]>=0 else -1
    south_edge=min(n['route_hint_m'][1] for n in b.g['nodes'][begin_nodes:])
    def lane(node_y,gap):
        # The corridor sits beyond the interface approach point, or the run
        # doubles back on itself, and beyond the plant, or it runs through it.
        return max(node_y+gap,py+8+gap) if oy>0 else min(node_y-gap,south_edge+2-gap)
    def boundary_lane(a,d,start_dir,end_dir,lane_y):
        aa=b.xyz(a);dd=b.xyz(d);lead=2
        ap=[aa[k]+start_dir[k]*lead for k in range(3)]
        end_lead=3.0 if c.plant_rotation_deg or c.plant_flip_x or c.plant_flip_y else lead
        dp=[dd[k]+end_dir[k]*end_lead for k in range(3)]
        if c.plant_rotation_deg or c.plant_flip_x or c.plant_flip_y:
            high=max(zr,aa[2],dd[2])+3+(1 if a==sink else 0)
            return [ap,[ap[0],ap[1],high],[dp[0],ap[1],high],[dp[0],dp[1],high],dp]
        detour=px+(c.chiller_count-1)*c.plant_equipment_pitch_m+5 if abs(start_dir[1])>.5 and start_dir[1]<0 else ap[0]
        # The detour exists to clear the chiller bank. A start already east of it
        # needs no sidestep, and one shorter than the bends it would take is not a
        # route at all.
        if abs(detour-ap[0])<3*c.bend_radius_m:detour=ap[0]
        travel_z=ap[2]+1.2 if c.plant_type=='water_cooled' and start_dir[1]<0 else ap[2]
        return [ap,[ap[0],ap[1],travel_z],[detour,ap[1],travel_z],[detour,lane_y,travel_z],[dp[0],lane_y,travel_z],[dp[0],lane_y,dp[2]],dp]
    # Outward direction at the first Y collector is -Y, at first X collector -X.
    pdir=transform_zone_vector([0,-1,0],spec);rdir=transform_zone_vector([-1,0,0],spec)
    # Supply first: the return then prices its corridor and follows it onto one
    # rack instead of opening a second.
    emit([('FWS-plant-supply',po,source,tuple(pdir),(0,oy,0),
           boundary_lane(po,source,pdir,[0,oy,0],lane(b.xyz(source)[1],4))),
          ('FWS-plant-return',sink,r,(0,oy,0),tuple(rdir),
           boundary_lane(sink,r,[0,oy,0],rdir,lane(b.xyz(sink)[1],6)))],'FWS')
    for comp in b.g['components'][begin_components:]:comp['zone']='plant'
    b.g['metadata']['plant']={'type':c.plant_type,'pumping':'variable_primary','equipment_ids':[x['id'] for x in equipment],
        'capacity_status':'NOT_EVALUABLE: manufacturer ratings and minimum-flow controls unassigned'}
