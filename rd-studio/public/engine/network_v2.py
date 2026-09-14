"""Physical reference network, independent pods and hydronic plant templates.

Routes use finite fitting takeoffs; equipment internals are functional graph
paths, never extruded as pipes. No pressure/network solver is used.
"""
from dataclasses import asdict
from math import dist, cos, sin, radians
from topology import Builder


def assignments(count,pods,explicit):
    return explicit or [min(pods, i*pods//count+1) for i in range(count)]

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

    def collectors(self):
        c=self.c;z=c.header_elevation_m;zr=z+c.return_elevation_offset_m
        allports={i:{} for i in range(1,c.cdu_count+1)};ends={}
        for service in ('FWS','TCS'):
            for pod in (range(1,c.pod_count+1) if service=='TCS' else [0]):
                self.current_pod=pod or 1
                units=[i for i in allports if service=='FWS' or self.cdus[i-1]==pod]
                previous={}
                offset=(pod-1)*c.pod_elevation_spacing_m if pod else 0
                for position,i in enumerate(units):
                    y=self.layout['cdu_origin_m'][1]+(i-1)*c.cdu_pitch_m
                    for label,x,zz,split in ([('ts',0,z+offset,False),('tr',-.65,zr+offset,True)] if service=='TCS' else [('fs',-8,z,True),('fr',-8.65,zr,False)]):
                        common,other,branch=self.junction([x,y,zz],[0,-1,0],[-1,0,0] if service=='TCS' else [1,0,0],service,'main',[self.fixed(0),self.fixed(0)],(None,None,None),split=split,last=position==0)
                        if position:
                            if split:self.route(other,previous[label],service,'main',self.fixed(0),(None,None,None))
                            else:self.route(previous[label],other,service,'main',self.fixed(0),(None,None,None))
                        previous[label]=common;allports[i][label]=branch
                ends[pod]=previous if pod else ends.get(pod,{})
                if service=='FWS':ends[0]=previous
        # Facility plant interface continues away from the hall in negative Y.
        fs=ends[0]['fs'];fr=ends[0]['fr']
        # Collector common ends point toward +Y. Take both to a clear corridor.
        y=max(1.,self.layout['cdu_origin_m'][1]+(c.cdu_count-1)*c.cdu_pitch_m+2)
        source=self.node([-8,y,z],'FWS','boundary');sink=self.node([-8.65,y,zr],'FWS','boundary')
        self.route(source,fs,'FWS','main',self.fixed(0),(None,None,None));self.route(fr,sink,'FWS','main',self.fixed(0),(None,None,None))
        self.g['metadata'].update(fws_source=source,fws_sink=sink,cdu_pump_nodes={})
        for i,ports in allports.items():
            self.current_pod=self.cdus[i-1];self.cdu_assembly(i,**ports)
        self.pod_ends={p:ends[p] for p in range(1,c.pod_count+1)}
        return source,sink

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
