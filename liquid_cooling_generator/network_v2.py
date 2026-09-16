"""Physical reference network, independent pods and hydronic plant templates.

Routes use finite fitting takeoffs; equipment internals are functional graph
paths, never extruded as pipes. No pressure/network solver is used.
"""
from dataclasses import asdict
from math import dist, cos, sin, radians
from topology import Builder


def assignments(count,pods,explicit):
    return explicit or [min(pods, i*pods//count+1) for i in range(count)]

# How far east of the trunk a moved pod's own collector runs: wide enough for the
# link corridor between the two, and no wider, because every centimetre of it
# comes out of the CDU branch's run east to the equipment port.
POD_LANE_M=1.25


def assign_connections(zones,points):
    """Send each zone to the nearest facility point that can still take all of it.

    Nearest first, then spill-over: a zone whose closest point has no capacity
    left for its whole flow goes to the next closest that has. A zone is never
    split between two points, because it has one pair of connection ports and
    half its duty cannot arrive from somewhere else.
    """
    free={p['id']:p.get('capacity_m3_s') for p in points}
    rows=[]
    for zone in zones:
        ranked=sorted(points,key=lambda p:(dist(zone['point_m'],p['point_m']),p['id']))
        flow=zone.get('flow_m3_s') or 0.
        fits=[(rank,p) for rank,p in enumerate(ranked) if free[p['id']] is None or free[p['id']]+1e-9>=flow]
        rank,point=fits[0] if fits else (0,ranked[0])
        if free[point['id']] is not None:free[point['id']]-=flow
        row={'zone':zone['id'],'connection_point':point['id'],'flow_m3_s':flow,
             'distance_m':round(dist(zone['point_m'],point['point_m']),3)}
        if not fits:row['status']='OVERSUBSCRIBED: no declared facility connection point has capacity for this zone'
        elif rank:row['status']='SPILLED: the nearest facility connection point had no spare capacity'
        rows.append(row)
    return rows

class NetworkBuilder(Builder):
    def __init__(self,c,profile):
        super().__init__(c,profile)
        self.rows=assignments(c.rows,c.pod_count,c.row_pod_assignments)
        self.cdus=assignments(c.cdu_count,c.pod_count,c.cdu_pod_assignments)
        self.current_pod=1

    def edge(self,comp,a,b,kind,basis):
        original=comp['service']
        if original=='CWS':comp['service']='FWS'
        edge=super().edge(comp,a,b,kind,basis)
        comp['service']=original;edge['service']=original
        if original=='CWS':edge['material']=self.c.cws_material
        edge['circuit_id']=f'TCS-P{self.current_pod:02}' if original=='TCS' else original
        edge['id']=comp['id']+':'+kind+':'+str(sum(e['component_id']==comp['id'] for e in self.g['edges']))
        edge['insulation_thickness_m']=self.c.insulation_thickness_m
        comp['circuit_id']=edge['circuit_id'];comp['pod']=self.current_pod if original=='TCS' else None
        return edge

    def route_path(self,a,b,points,service,level,basis,group):
        # Remove repeated and collinear waypoints, never shrink a requested bend.
        pts=[list(self.xyz(a))]+[list(p) for p in points]+[list(self.xyz(b))]
        unique=[]
        for p in pts:
            if not unique or dist(unique[-1],p)>1e-8:unique.append(p)
        pts=[]
        for p in unique:
            while len(pts)>1 and sum(abs(pts[-2][k]-p[k])>1e-8 for k in range(3))==1 and all(min(pts[-2][k],p[k])-1e-8<=pts[-1][k]<=max(pts[-2][k],p[k])+1e-8 for k in range(3)):pts.pop()
            pts.append(p)
        if len(pts)<2:raise ValueError('Coincident route endpoints: '+a+' / '+b)
        for p,q in zip(pts,pts[1:]):
            if sum(abs(p[k]-q[k])>1e-8 for k in range(3))!=1:raise ValueError('Route requires orthogonal waypoints')
        radius=self.c.bend_radius_m
        for i,(p,q) in enumerate(zip(pts,pts[1:])):
            required=radius*((i>0)+(i<len(pts)-2))+.01
            if len(pts)>2 and dist(p,q)<required-1e-8:raise ValueError(f'Route {a} → {b}: segment {dist(p,q):.3f} m cannot fit {radius:.3f} m bends; increase spacing or select smaller fitting takeoff.')
        current=a
        for before,corner,after in zip(pts,pts[1:],pts[2:]):
            pre=[corner[k]+(before[k]-corner[k])*radius/dist(before,corner) for k in range(3)]
            post=[corner[k]+(after[k]-corner[k])*radius/dist(after,corner) for k in range(3)]
            pnode=self.node(pre,service);qnode=self.node(post,service)
            if dist(self.xyz(current),pre)>1e-8:self.component('pipe',[current,pnode],service,level,basis,group)
            self.component('elbow',[pnode,qnode],service,level,basis,group,center_m=corner,bend_radius_m=radius)
            current=qnode
        if dist(self.xyz(current),self.xyz(b))>1e-8:self.component('pipe',[current,b],service,level,basis,group)

    def route(self,a,b,service,level,basis,group):
        p=list(self.xyz(a));target=self.xyz(b);points=[]
        for axis in (0,1,2):
            if abs(p[axis]-target[axis])>1e-8:p=p.copy();p[axis]=target[axis];points.append(p)
        self.route_path(a,b,points[:-1],service,level,basis,group)

    def facility_interface(self):
        """Fix which end of the hall hands over to the facility, before any pipe.

        The FWS collector used to leave the hall at its north end whatever else
        was there. On RD113 - plant at y=-16, pod 1 sitting beside it at
        y=-16..-10 - that sent every circuit north to y=+1.7 and the plant then
        reached back the length of the hall to meet it. The interface now sits at
        whichever end of the CDU line faces the plant, and the collector is
        ordered to leave on that side, so no pod starts by travelling away from
        the plant it is trying to reach.

        The interface only moves to the plant's side when the service corridor on
        that side is clear. A water-cooled plant puts its condenser banks, towers
        and condenser pumps south of the chillers, and the plant's own FWS ends
        face west and north, so the run would have to cross that circuit to reach
        a south interface. Those designs, and boundary designs with no plant to
        face at all, keep the north corridor until the plant can declare a
        hall-facing connection point of its own.
        """
        c=self.c;ys=[self.layout['cdu_origin_m'][1]+(i-1)*c.cdu_pitch_m for i in range(1,c.cdu_count+1)]
        lo,hi=min(ys),max(ys)
        if c.plant_type=='air_cooled' and c.plant_origin_y_m<(lo+hi)/2:return lo-2.,-1
        return max(1.,hi+2.),1

    def cdu_y(self,i):
        return self.layout['cdu_origin_m'][1]+(i-1)*self.c.cdu_pitch_m

    def fws_collectors(self,allports,interface_y,outward):
        """The facility-water corridor: one trunk, and one collector per pod.

        A pod's collector is part of the pod. It gathers that pod's CDUs and
        nothing else, ends at the pod's connection point, and travels with the
        pod when it is arranged somewhere else - so only the pair of links back
        to the trunk has to be rerouted.

        This used to be a single chain through every CDU with the collector
        pinned in place, and relocate_pods then ran a separate elevated lane from
        each CDU's tee out to wherever that CDU had gone, stacking them 0.8 m
        apart because they all left from the same column. On RD113 the eighth
        lane sat at 11.76 m, through a 6.5 m ceiling, so an eight-CDU pod could
        not be arranged at all. One link per pod replaces eight per pod and they
        share a single elevation.

        The trunk runs from the interface out past the pods that stay, and each
        pod that moves is a tee beyond them, never between an unmoved pod and the
        plant. Returns the corridor's open end, per-pod connection points, the
        air-unit tap and the links that relocate_pods still has to build.
        """
        c=self.c;z=c.header_elevation_m;zr=z+c.return_elevation_offset_m
        basis=self.fixed(0);group=(None,None,None);labels=[('fs',-8.,z,True),('fr',-8.65,zr,False)]
        from zone_editing import _specs
        specs={spec['pod']:spec for spec in _specs(self)}
        from air_cooling import heat_ledger
        # The air units sit north of the hall. When the interface faces south the
        # corridor's far end is the one beside them, so it stays open for them to
        # tap rather than sending a branch the length of the hall past every CDU.
        air=outward<0 and heat_ledger(c)['air_W']>1e-9
        stay=[p for p in range(1,c.pod_count+1) if not specs[p]['moved']]
        move=[p for p in range(1,c.pod_count+1) if specs[p]['moved']]
        joins={};tap={};links=[];previous={};built=[0]

        def takeoff(y,pod,east=True):
            """One position on the trunk, walking from its far end to the interface."""
            branches={}
            for label,x,zz,split in labels:
                common,other,branch=self.junction([x,y,zz],[0,-outward,0],[1 if east else -1,0,0],'FWS','main',[basis,basis],group,
                                                  split=split,last=not built[0] and not air)
                if built[0]:
                    if split:self.route(other,previous[label],'FWS','main',basis,group)
                    else:self.route(previous[label],other,'FWS','main',basis,group)
                elif other is not None:tap[label]=other
                previous[label]=common;branches[label]=branch
            built[0]+=1
            return branches

        # Where each moved pod's connection point comes to rest. The takeoffs have
        # to sit clear of that, not just clear of where the pods started, or a pod
        # arranged along the hall lands on top of its own takeoff.
        from zone_geometry import transform_zone_point
        def landing(pod,y=None):
            ys=[self.cdu_y(i) for i in allports if self.cdus[i-1]==pod]
            if y is None:y=max(ys,key=lambda v:outward*v)+outward*c.fitting_arm_m
            return transform_zone_point([-8.+POD_LANE_M,y,z],specs[pod])
        # The whole arranged pod, not just its connection point: a takeoff has to
        # clear the far end of the pod as well as the end that reaches back to it.
        reach=[self.cdu_y(i) for i in allports]
        reach+=[landing(pod,self.cdu_y(i))[1] for pod in move for i in allports if self.cdus[i-1]==pod]
        spur=max(reach)+2. if outward<0 else min(reach)-2.
        # Furthest from the interface first: each moved pod tees off out here,
        # where there is room, and the pods that stay keep a clear run inward.
        for offset,pod in enumerate(move):
            self.current_pod=pod
            # Furthest out first, like the CDUs: the corridor is walked in one
            # direction and every takeoff has to be nearer the interface than the
            # one before it, or the run doubles back through its own tee.
            branches=takeoff(spur-outward*(len(move)-offset)*2.,pod,east=landing(pod)[0]>-8.)
            for label,_,_,_ in labels:links.append({'pod':pod,'label':label,'trunk':branches[label]})
        # Same order as the CDUs within a pod: furthest from the interface first,
        # so the corridor is walked once and ends at the interface.
        for pod in sorted(stay,key=lambda p:min(outward*self.cdu_y(i) for i in allports if self.cdus[i-1]==p)):
            self.current_pod=pod
            for i in sorted((i for i in allports if self.cdus[i-1]==pod),key=lambda i:outward*self.cdu_y(i)):
                branches=takeoff(self.cdu_y(i),pod)
                for label,_,_,_ in labels:allports[i][label]=branches[label]
                joins[pod]={label:previous[label] for label,_,_,_ in labels}
        source=self.node([-8.,interface_y,z],'FWS','boundary');sink=self.node([-8.65,interface_y,zr],'FWS','boundary')
        self.route(source,previous['fs'],'FWS','main',basis,group);self.route(previous['fr'],sink,'FWS','main',basis,group)

        # Each moved pod's own collector, built where the pod still is. The
        # transform in relocate_pods carries it, its CDU branches and its
        # connection point across together.
        # A moved pod's collector travels with the pod, so a pod arranged a few
        # metres along the hall would otherwise come to rest on top of the trunk
        # it just left. Its own lane, 1.4 m east, clears the trunk and still
        # leaves each CDU branch its run to the equipment port.
        lane=[(label,x+POD_LANE_M,zz,split) for label,x,zz,split in labels]
        for pod in move:
            self.current_pod=pod;start=len(self.g['components'])
            local={}
            for position,i in enumerate(sorted((i for i in allports if self.cdus[i-1]==pod),key=lambda i:outward*self.cdu_y(i))):
                for label,x,zz,split in lane:
                    common,other,branch=self.junction([x,self.cdu_y(i),zz],[0,-outward,0],[1,0,0],'FWS','main',[basis,basis],group,
                                                      split=split,last=position==0)
                    if position:
                        if split:self.route(other,local[label],'FWS','main',basis,group)
                        else:self.route(local[label],other,'FWS','main',basis,group)
                    local[label]=common;allports[i][label]=branch
            joins[pod]=dict(local)
            for comp in self.g['components'][start:]:comp['zone_pod']=pod
            for link in links:
                if link['pod']==pod:link['pod_end']=local[link['label']]
        return source,sink,joins,tap,links

    def collectors(self):
        c=self.c;z=c.header_elevation_m;zr=z+c.return_elevation_offset_m
        allports={i:{} for i in range(1,c.cdu_count+1)};ends={}
        interface_y,outward=self.facility_interface()
        source,sink,joins,tap,links=self.fws_collectors(allports,interface_y,outward)
        for pod in range(1,c.pod_count+1):
            self.current_pod=pod
            units=[i for i in allports if self.cdus[i-1]==pod]
            previous={};offset=(pod-1)*c.pod_elevation_spacing_m
            for position,i in enumerate(units):
                y=self.cdu_y(i)
                for label,x,zz,split in [('ts',0,z+offset,False),('tr',-.65,zr+offset,True)]:
                    common,other,branch=self.junction([x,y,zz],[0,-1,0],[-1,0,0],'TCS','main',[self.fixed(0),self.fixed(0)],(None,None,None),split=split,last=position==0)
                    if position:
                        if split:self.route(other,previous[label],'TCS','main',self.fixed(0),(None,None,None))
                        else:self.route(previous[label],other,'TCS','main',self.fixed(0),(None,None,None))
                    previous[label]=common;allports[i][label]=branch
            ends[pod]=previous
        self.g['metadata'].update(fws_source=source,fws_sink=sink,cdu_pump_nodes={},fws_interface_dir=[0,outward,0])
        # An open trunk port, not a routed stub: whoever uses it owns the turn,
        # and a turn only gets an elbow where one route makes the corner.
        if tap:self.g['metadata']['fws_air_tap']={'supply':tap['fs'],'return':tap['fr'],'run_out_m':-2.*outward}
        if links:self.g['metadata']['fws_pod_links']=links
        self.declare_connections(joins,source,sink,outward)
        for i,ports in allports.items():
            self.current_pod=self.cdus[i-1];self.cdu_assembly(i,**ports)
        self.pod_ends={p:ends[p] for p in range(1,c.pod_count+1)}
        return source,sink

    def declare_connections(self,joins,source,sink,outward):
        """Record where each zone hands over, and which facility point it uses.

        A pod's connection point is the tee where its primary duty joins the
        facility trunk: upstream of it the piping belongs to the pod, downstream
        it is shared. Declaring the point is what lets a reviewer see that a pod
        reaches the plant directly, and it is what the nearest-plant rule ranks.
        One plant can be declared today, so every pod is assigned to it; the
        spill-over branch becomes reachable when a second plant can be declared.
        """
        c=self.c
        points=[{'id':'facility-fws','kind':'plant' if c.plant_type!='boundary' else 'boundary',
                 'label':'Cooling plant' if c.plant_type!='boundary' else 'Facility boundary',
                 'service':'FWS','supply_node':source,'return_node':sink,
                 'point_m':[round(v,3) for v in self.xyz(source)],'outward_dir':[0,outward,0],
                 'capacity_m3_s':self.h['fws_total_m3_s']}]
        zones=[{'id':f'pod-{pod}','kind':'cooling_pod','pod':pod,'label':f'Cooling pod {pod}','service':'FWS',
                'supply_node':joins[pod]['fs'],'return_node':joins[pod]['fr'],
                'point_m':[round(v,3) for v in self.xyz(joins[pod]['fs'])],
                'flow_m3_s':self.h['fws_cdu_total_m3_s']*self.rows.count(pod)/c.rows} for pod in sorted(joins)]
        self.g['metadata']['connection_points']={'facility':points,'zones':zones,
            'assignments':assign_connections(zones,points),
            'basis':'Each cooling pod joins the facility trunk at its own tee and takes the nearest declared facility connection point with capacity for its whole primary flow.',
            'scope':'Geometric and flow-capacity assignment only. No pressure, control-valve authority or plant staging check.'}

    def cdu_assembly(self,i,ts,tr,fs,fr):
        c=self.c;group=(None,None,i);y=self.layout['cdu_origin_m'][1]+(i-1)*c.cdu_pitch_m
        x=self.layout['cdu_origin_m'][0];ports={};ivs=[]
        for label,branch,service,px,inlet in [('ts',ts,'TCS',x+.65,False),('tr',tr,'TCS',x+.05,True),('fs',fs,'FWS',x-1.15,True),('fr',fr,'FWS',x-.55,False)]:
            bx,by,bz=self.xyz(branch);direction=-1 if service=='TCS' else 1
            # Reducer and isolation remain inline with the collector branch.
            length=.35;end=[bx+direction*length,y,bz]
            if inlet:
                red,rc=self.part(branch,end,'reducer',service,'cdu',self.fixed(0),group)
                iv,vc=self.part(red,[end[0]+direction*.3,y,bz],'isolation_valve',service,'cdu',self.fixed(0),group)
                port=self.node([px,y,c.cdu_height_m],service,'equipment_port')
                self.route_path(iv,port,[[px,y,bz]],service,'cdu',self.fixed(0),group)
            else:
                port=self.node([px,y,c.cdu_height_m],service,'equipment_port')
                iv=self.node([end[0]+direction*.3,y,bz],service)
                self.route_path(port,iv,[[px,y,bz]],service,'cdu',self.fixed(0),group)
                red,vc=self.part(iv,end,'isolation_valve',service,'cdu',self.fixed(0),group)
                rc=self.component('reducer',[red,branch],service,'main',self.fixed(0),group)
            ivs.append(vc['id']);ports[label]=port
        cid=f'CDU-{i:02}'
        comp={'id':cid,'tag':cid,'kind':'cdu','service':'EQUIPMENT','level':'cdu','ports':[ports[k] for k in ('fs','fr','tr','ts')],
              'row':None,'rack':None,'cdu':i,'pod':self.current_pod,'center_m':[x-.25,y,c.cdu_height_m/2],'size_m':[c.cdu_width_m,c.cdu_depth_m,c.cdu_height_m],
              'schematic_group':'equipment-cdu','status':'conceptual','hydraulic_element':True,'port_directions':{p:[0,0,1] for p in ports.values()},
              'functions':['heat_exchanger','secondary_pump','expansion','air_separation','filtration'],
              'assumptions':['Four external ports; manufacturer internals and ratings remain unassigned.']}
        self.g['components'].append(comp)
        for service,a,b,kind in [('FWS',ports['fs'],ports['fr'],'cdu_primary'),('TCS',ports['tr'],ports['ts'],'cdu_secondary')]:
            comp['service']=service;e=self.edge(comp,a,b,kind,self.fixed(0));e['internal']=True
        comp['service']='EQUIPMENT';comp['circuit_id']='MULTI';comp['pod']=self.current_pod
        self.g['couplings'].append({'id':cid,'primary_component':cid,'secondary_component':cid,'primary_ports':[ports['fs'],ports['fr']],
            'secondary_ports':[ports['tr'],ports['ts']],'heat_W':self.rows.count(self.current_pod)*c.racks_per_row*c.rack_power_W*c.liquid_fraction/self.cdus.count(self.current_pod),'design_capacity_W':None,
            'mass_transfer_kg_s':0.,'isolation_components':ivs,'component_ids':[cid]+ivs,'heat_basis':'Aggregate load allocation; equipment capacity not validated'})

    def distribution_pods(self):
        c=self.c;original=c.header_elevation_m
        for pod in range(1,c.pod_count+1):
            self.current_pod=pod;c.header_elevation_m=original+(pod-1)*c.pod_elevation_spacing_m
            selected=[i+1 for i,p in enumerate(self.rows) if p==pod]
            prev_s=self.pod_ends[pod]['ts'];prev_r=self.pod_ends[pod]['tr']
            for index,ri in enumerate(selected):
                y=self.layout['compute_row_y_m'][ri-1];z=c.header_elevation_m;zr=z+c.return_elevation_offset_m;group=(ri,None,None)
                sc,sn,sb=self.junction([0,y-c.header_half_separation_m,z],[0,1,0],[1,0,0],'TCS','main',[self.fixed(0),self.fixed(0)],group,last=index==len(selected)-1)
                rc,rn,rb=self.junction([-.65,y+c.header_half_separation_m,zr],[0,1,0],[1,0,0],'TCS','main',[self.fixed(0),self.fixed(0)],group,split=False,last=index==len(selected)-1)
                self.route(prev_s,sc,'TCS','main',self.fixed(0),group);self.route(rc,prev_r,'TCS','main',self.fixed(0),group)
                prev_s,prev_r=sn,rn
                rs,_=self.part(sb,[.55,y-c.header_half_separation_m,z],'reducer','TCS','row',self.fixed(0),group)
                rs,_=self.part(rs,[.85,y-c.header_half_separation_m,z],'isolation_valve','TCS','row',self.fixed(0),group)
                rr=self.node([.85,y+c.header_half_separation_m,zr],'TCS')
                vr,_=self.part(rr,[.55,y+c.header_half_separation_m,zr],'balancing_valve','TCS','row',self.fixed(0),group)
                vr,_=self.part(vr,[.25,y+c.header_half_separation_m,zr],'isolation_valve','TCS','row',self.fixed(0),group)
                self.component('reducer',[vr,rb],'TCS','main',self.fixed(0),group)
                self.racks(ri,rs,rr,y)
        c.header_elevation_m=original

    def racks(self,ri,supply,ret,ry):
        c=self.c;z=c.header_elevation_m;zr=z+c.return_elevation_offset_m
        prev_s=supply;prev_r=ret
        reverse=c.return_topology=='reverse_return'
        if reverse:
            prev_r=self.node([c.first_rack_x_m+(c.racks_per_row-1)*c.rack_pitch_m+.65,ry+c.header_half_separation_m,zr],'TCS')
            xright=self.xyz(prev_r)[0]+.6;xleft=self.xyz(ret)[0]+.6
            self.route_path(prev_r,ret,[[xright,ry+c.header_half_separation_m,zr],[xright,ry+c.header_half_separation_m,zr+.8],[xleft,ry+c.header_half_separation_m,zr+.8],[xleft,ry+c.header_half_separation_m,zr]],'TCS','row',self.fixed(self.h['row_m3_s']),(ri,None,None))
        rack_connections=[]
        return_branches={}
        for rj in range(1,c.racks_per_row+1):
            x=c.first_rack_x_m+(rj-1)*c.rack_pitch_m;g=(ri,None,None)
            q=self.h['rack_m3_s'];remain=q*(c.racks_per_row-rj)
            sc,sn,sb=self.junction([x,ry-c.header_half_separation_m,z],[1,0,0],[0,0,-1],
                'TCS','row',[self.fixed(remain),self.fixed(q)],g,last=rj==c.racks_per_row)
            rx=c.first_rack_x_m+(c.racks_per_row-rj)*c.rack_pitch_m if reverse else x
            rc,rn,rb=self.junction([rx,ry+c.header_half_separation_m,zr],[-1,0,0] if reverse else [1,0,0],[0,0,-1],
                'TCS','row',[self.fixed(remain),self.fixed(q)],g,split=False,last=rj==c.racks_per_row)
            self.route(prev_s,sc,'TCS','row',self.fixed(remain+q),g)
            self.route(rc,prev_r,'TCS','row',self.fixed(remain+q),g)
            prev_s,prev_r=sn,rn
            rack_connections.append((rj,sb,x))
            return_branches[c.racks_per_row-rj+1 if reverse else rj]=rb
        for rj,sb,x in rack_connections:self.rack(ri,rj,sb,return_branches[rj],ry,x)

    def rack(self,ri,rj,sb,rb,ry,x):
        # Vertical external connection pairs terminate on the rack roof.
        c=self.c;group=(ri,rj,None);basis=self.fixed(0);ports=[]
        for incoming,start in [(True,sb),(False,rb)]:
            sx,sy,z=self.xyz(start);target=self.node([sx,sy,c.rack_height_m],'TCS','equipment_port')
            if incoming:
                a,_=self.part(start,[sx,sy,z-.2],'reducer','TCS','rack',basis,group)
                a,_=self.part(a,[sx,sy,z-.5],'isolation_valve' if c.include_rack_isolation_valves else 'pipe','TCS','rack',basis,group)
                q=self.node([sx,sy,c.rack_height_m+.25],'TCS');self.route(a,q,'TCS','rack',basis,group)
                f,_=self.part(q,[sx,sy,c.rack_height_m+.12],'quick_disconnect' if c.include_quick_disconnects else 'pipe','TCS','rack',basis,group)
                self.component('flex_connector' if c.include_flex_connectors else 'pipe',[f,target],'TCS','rack',basis,group)
            else:
                f,_=self.part(target,[sx,sy,c.rack_height_m+.12],'flex_connector' if c.include_flex_connectors else 'pipe','TCS','rack',basis,group)
                q,_=self.part(f,[sx,sy,c.rack_height_m+.25],'quick_disconnect' if c.include_quick_disconnects else 'pipe','TCS','rack',basis,group)
                a=self.node([sx,sy,z-.8],'TCS');self.route(q,a,'TCS','rack',basis,group)
                a,_=self.part(a,[sx,sy,z-.5],'balancing_valve' if c.include_rack_balancing_valves else 'pipe','TCS','rack',basis,group)
                a,_=self.part(a,[sx,sy,z-.2],'isolation_valve' if c.include_rack_isolation_valves else 'pipe','TCS','rack',basis,group)
                self.component('reducer',[a,start],'TCS','row',basis,group)
            ports.append(target)
        comp=self.component('rack_load',ports,'TCS','rack',basis,group,heat_W=c.rack_power_W*c.liquid_fraction,abstract=True,
            port_directions={p:[0,0,1] for p in ports},host_equipment=f'IT-R{ri:02}-{rj:02}')
        self.g['edges'][-1]['internal']=True


def generate(c,profile):
    b=NetworkBuilder(c,profile);b.collectors();b.distribution_pods()
    from zone_editing import relocate_pods
    relocate_pods(b)
    from air_cooling import add_air_cooling
    add_air_cooling(b)
    if c.plant_type!='boundary':
        from plant import add_plant
        add_plant(b)
    b.g['metadata']['pod_assignments']={'rows':b.rows,'cdus':b.cdus}
    b.g['metadata']['standards']=profile.manifest()
    from cdu_scenarios import attach
    attach(b.g,c,b.rows,b.cdus)

    return b.g
