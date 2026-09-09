"""Graph-first reference layout. Every hydraulic component has identity and ports."""
from dataclasses import asdict
from math import dist
from layout import arrangement
from itertools import combinations
from model import Node, Component, Edge, empty_graph, build_profile
from hydraulics import heat_flows

K = {'isolation_valve':.2,'balancing_valve':2.,'check_valve':2.5,
     'elbow':.6,'reducer':.15,'tee_run':.6,'tee_branch':1.8}


class Builder:
    def __init__(self,c,profile=None):
        self.c=c;self.g=empty_graph(c);self.n={};self.count={}
        self.h=heat_flows(c)
        self.layout=arrangement(c)
        if c.sizing_mode=='manual':
            self.h={k:(0.0 if k.endswith(('_m3_s','_mass_kg_s')) else v) for k,v in self.h.items()}
        self.P=profile if profile is not None else build_profile(c)

    def node(self,xyz,service,kind='port'):
        name=f'N{len(self.n)+1:05d}'
        n=asdict(Node(name,kind,list(xyz),None,service))
        self.n[name]=n;self.g['nodes'].append(n);return name

    def xyz(self,n):return self.n[n]['route_hint_m']

    def component(self,kind,ports,service,level,basis,group,**extra):
        if group[1] and ((kind=='quick_disconnect' and not self.c.include_quick_disconnects) or (kind=='balancing_valve' and not self.c.include_rack_balancing_valves) or (kind=='isolation_valve' and not self.c.include_rack_isolation_valves)):
            kind='pipe'
        prefix={'pipe':'P','tee':'T','elbow':'E','reducer':'R','isolation_valve':'IV',
                'balancing_valve':'BV','check_valve':'CV','rack_load':'LOAD','rack_manifold':'RM',
                'quick_disconnect':'QD','pump':'PUMP','cdu_primary':'HX-P','cdu_secondary':'HX-S',
                'strainer':'STR','air_separator':'AS','expansion_tank':'EXP'}.get(kind,kind.upper())
        row,rack,cdu=group
        scope=f'C{cdu:02d}' if cdu else (f'R{row:02d}K{rack:02d}' if rack else (f'R{row:02d}' if row else 'MAIN'))
        key=service+'-'+scope+'-'+prefix;self.count[key]=self.count.get(key,0)+1
        tag=f'{key}-{self.count[key]:03d}'
        row,rack,cdu=group
        sheet=f'{service}-CDU-{cdu:02d}' if cdu else (f'{service}-ROW-{row:02d}-RACK-{rack:02d}' if rack else (f'{service}-ROW-{row:02d}' if row else f'{service}-MAIN'))
        comp=asdict(Component(tag,tag,kind,service,level,ports,row,rack,cdu,sheet))
        comp['assumptions']=['ASSUMPTION: routing envelope only; vendor dimensions and connector rating unverified'] if kind!='pipe' else []
        if kind=='isolation_valve':comp['normal_position']='normally open; closed when parent CDU isolated' if cdu else 'normally open; manual closure for row/rack maintenance'
        if kind=='balancing_valve':comp['normal_position']='ASSUMPTION controlled/throttled; final setting unresolved'
        if kind=='check_valve':comp['normal_position']='automatic nonreturn'
        comp.update(extra);self.g['components'].append(comp)
        if kind!='tee':self.edge(comp,ports[0],ports[1],kind,basis)
        return comp

    def edge(self,comp,a,b,kind,basis):
        service,level=comp['service'],comp['level']
        cat=self.P.category_for(service,level)
        material=cat.catalogue
        nominalflow={'rack':self.h['rack_m3_s'],'row_branch':self.h['rack_m3_s'],
            'row':self.h['row_m3_s'],'main':self.h['tcs_total_m3_s'] if service=='TCS' else self.h['fws_total_m3_s'],
            'cdu':self.h['cdu_secondary_m3_s'] if service=='TCS' else self.h['cdu_primary_m3_s']}[level]
        refdp={'rack_load':self.c.rack_load_dp_Pa,'rack_manifold':self.c.manifold_dp_Pa,
            'quick_disconnect':self.c.qd_dp_Pa,'cdu_secondary':self.c.cdu_secondary_dp_Pa,
            'cdu_primary':self.c.cdu_primary_dp_Pa,'strainer':self.c.strainer_dp_Pa}.get(kind,0.)
        e=asdict(Edge(f'H{len(self.g["edges"])+1:05d}',comp['id'],a,b,service,level,kind,
            nominalflow,nominalflow,basis,self.c.initial_pipe_length_m if kind=='pipe' else 0.,
            material,K.get(kind,0.),refdp,nominalflow,comp['row'],comp['rack'],comp['cdu'],
            {'flow':'calculated from heat balance; assumed controlled parallel flow split',
             'K':'EPANET 2.2 Table 3.3 representative value' if kind in ('elbow','tee_run','tee_branch','isolation_valve','check_valve') else 'ASSUMPTION where nonzero; vendor Cv/K missing',
             'reference_dp':'ASSUMPTION where nonzero; vendor curves missing',
             'length':'ASSUMPTION initial 1 m per pipe; replaced in routing stage',
             'material':'assigned by pipe category, not by hard-coded level test'}))
        e['sizing_flow_m3_s']=nominalflow
        e['pipe_category']=cat.name
        e['velocity_cap_m_s']=cat.velocity_cap_m_s.value
        e['roughness_m']=cat.roughness_m.value
        e['insulation_thickness_m']=cat.insulation_thickness_m.value
        e['provenance']['velocity_cap']=f'{cat.velocity_cap_m_s.source} {cat.velocity_cap_m_s.clause} ({cat.velocity_cap_m_s.status})'.strip()
        e['provenance']['material']=f'pipe category {cat.name}; catalogue {cat.catalogue}'
        self.g['edges'].append(e);return e

    def part(self,a,end,kind,service,level,basis,group,**extra):
        b=self.node(end,service)
        comp=self.component(kind,[a,b],service,level,basis,group,**extra)
        return b,comp

    def route(self,a,b,service,level,basis,group):
        """Orthogonal centre-line pipes and explicit finite-endpoint elbow components."""
        p=list(self.xyz(a));target=self.xyz(b);points=[p]
        for axis in (0,1,2):
            if abs(p[axis]-target[axis])>1e-9:
                p=p.copy();p[axis]=target[axis];points.append(p)
        if len(points)==1:
            raise ValueError('Zero-length connection must share a node')
        current=a
        for j in range(1,len(points)-1):
            before,corner,after=points[j-1:j+2]
            trim=min(self.c.bend_radius_m,dist(before,corner)/3,dist(corner,after)/3) # ASSUMPTION elbow envelope
            pre=[corner[k]+(before[k]-corner[k])*trim/dist(before,corner) for k in range(3)]
            post=[corner[k]+(after[k]-corner[k])*trim/dist(after,corner) for k in range(3)]
            pnode=self.node(pre,service);qnode=self.node(post,service)
            if dist(self.xyz(current),pre)>1e-9:self.component('pipe',[current,pnode],service,level,basis,group)
            self.component('elbow',[pnode,qnode],service,level,basis,group,center_m=corner)
            current=qnode
        if dist(self.xyz(current),self.xyz(b))>1e-9:self.component('pipe',[current,b],service,level,basis,group)

    def junction(self,center,axis,branch,service,level,bases,group,split=True,last=False):
        arm=self.c.fitting_arm_m # Parametric envelope, checked against selected bore
        common=self.node([center[i]-axis[i]*arm for i in range(3)],service,'header_junction')
        other=self.node([center[i]+axis[i]*arm for i in range(3)],service,'header_junction') if not last else None
        side=self.node([center[i]+branch[i]*arm for i in range(3)],service,'header_junction')
        if last:
            ports=[common,side] if split else [side,common]
            self.component('elbow',ports,service,level,bases[1],group,center_m=center)
        else:
            comp=self.component('tee',[common,other,side],service,level,bases[1],group,center_m=center)
            self.edge(comp,common if split else other,other if split else common,'tee_run',bases[0])
            self.edge(comp,common if split else side,side if split else common,'tee_branch',bases[1])
        return common,other,side

    def fixed(self,q):return {'type':'fixed','total_m3_s':q}
    def cdu(self,i,service):return {'type':'cdu','cdu':i,'total_m3_s':self.h['tcs_total_m3_s'] if service=='TCS' else self.h['fws_total_m3_s']}
    def collector(self,ids,service):return {'type':'collector','cdus':list(ids),'total_m3_s':self.h['tcs_total_m3_s'] if service=='TCS' else self.h['fws_total_m3_s']}

    def racks(self,ri,supply,ret,ry):
        c=self.c;z=c.header_elevation_m;zr=z+c.return_elevation_offset_m
        prev_s=supply;prev_r=ret
        reverse=c.return_topology=='reverse_return'
        if reverse:
            prev_r=self.node([c.first_rack_x_m+(c.racks_per_row-1)*c.rack_pitch_m+.65,ry+c.header_half_separation_m,zr],'TCS')
            raised=self.node([self.xyz(prev_r)[0],ry+c.header_half_separation_m,zr+.45],'TCS')
            end=self.node([self.xyz(ret)[0],ry+c.header_half_separation_m,zr+.45],'TCS')
            self.route(prev_r,raised,'TCS','row',self.fixed(self.h['row_m3_s']),(ri,None,None))
            self.route(raised,end,'TCS','row',self.fixed(self.h['row_m3_s']),(ri,None,None))
            self.route(end,ret,'TCS','row',self.fixed(self.h['row_m3_s']),(ri,None,None))
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
        c=self.c;g=(ri,rj,None);basis=self.fixed(self.h['rack_m3_s'])
        sy=ry-c.header_half_separation_m;ryy=ry+c.header_half_separation_m
        # Every valve/QD/manifold/load is an explicit two-port component.
        current,_=self.part(sb,[x,sy,c.header_elevation_m-.32],'reducer','TCS','rack',basis,g)
        current,_=self.part(current,[x,sy,c.header_elevation_m-.52],'isolation_valve','TCS','rack',basis,g)
        low=self.node([x,sy,c.manifold_elevation_m+.30],'TCS','rack_port')
        self.route(current,low,'TCS','rack',basis,g)
        current,_=self.part(low,[x,sy,c.manifold_elevation_m+.15],'quick_disconnect','TCS','rack',basis,g)
        current,_=self.part(current,[x,sy,c.manifold_elevation_m+.07],'flex_connector' if c.include_flex_connectors else 'pipe','TCS','rack',basis,g)
        current,_=self.part(current,[x,sy,c.manifold_elevation_m],'rack_manifold','TCS','rack',basis,g)
        current,load=self.part(current,[x,ryy,c.manifold_elevation_m],'rack_load','TCS','rack',basis,g,heat_W=self.h['rack_heat_W'])
        current,_=self.part(current,[x,ryy,c.manifold_elevation_m+.07],'rack_manifold','TCS','rack',basis,g)
        current,_=self.part(current,[x,ryy,c.manifold_elevation_m+.15],'flex_connector' if c.include_flex_connectors else 'pipe','TCS','rack',basis,g)
        current,_=self.part(current,[x,ryy,c.manifold_elevation_m+.30],'quick_disconnect','TCS','rack',basis,g)
        current,_=self.part(current,[x,ryy,c.manifold_elevation_m+.50],'balancing_valve','TCS','rack',basis,g)
        high=self.node([x,ryy,c.header_elevation_m+c.return_elevation_offset_m-.52],'TCS')
        self.route(current,high,'TCS','rack',basis,g)
        current,_=self.part(high,[x,ryy,c.header_elevation_m+c.return_elevation_offset_m-.32],'isolation_valve','TCS','rack',basis,g)
        self.component('reducer',[current,rb],'TCS','row',basis,g) # expansion to row bore

    def distribution(self,start_s,start_r):
        c=self.c;z=c.header_elevation_m;zr=z+c.return_elevation_offset_m
        prev_s,prev_r=start_s,start_r
        for ri in range(1,c.rows+1):
            y=self.layout['compute_row_y_m'][ri-1];q=self.h['row_m3_s'];remain=(c.rows-ri)*q
            sc,sn,sb=self.junction([0,y-c.header_half_separation_m,z],[0,1,0],[1,0,0],
                'TCS','main',[self.fixed(remain),self.fixed(q)],(None,None,None),last=ri==c.rows)
            rc,rn,rb=self.junction([-.65,y+c.header_half_separation_m,zr],[0,1,0],[1,0,0],
                'TCS','main',[self.fixed(remain),self.fixed(q)],(None,None,None),split=False,last=ri==c.rows)
            self.route(prev_s,sc,'TCS','main',self.fixed(remain+q),(None,None,None))
            self.route(rc,prev_r,'TCS','main',self.fixed(remain+q),(None,None,None))
            prev_s,prev_r=sn,rn;g=(ri,None,None);basis=self.fixed(q)
            rs,_=self.part(sb,[.40,y-c.header_half_separation_m,z],'reducer','TCS','row',basis,g)
            rs,_=self.part(rs,[.65,y-c.header_half_separation_m,z],'isolation_valve','TCS','row',basis,g)
            # Flow from row return toward main; size change explicitly represented.
            rr=self.node([.65,y+c.header_half_separation_m,zr],'TCS')
            vr,_=self.part(rr,[.40,y+c.header_half_separation_m,zr],'balancing_valve','TCS','row',basis,g)
            vr,_=self.part(vr,[.15,y+c.header_half_separation_m,zr],'isolation_valve','TCS','row',basis,g)
            self.component('reducer',[vr,rb],'TCS','main',basis,g)
            self.racks(ri,rs,rr,y)

    def collectors(self):
        c=self.c;z=c.header_elevation_m;zr=z+c.return_elevation_offset_m
        ts={};tr={};fs={};fr={};previous={}
        # Collector branches are generated for the configured CDU count.
        # TCS supply combines pump outlets; TCS return splits into pump inlets.
        for i in range(1,c.cdu_count+1):
            y=self.layout['cdu_origin_m'][1]+(i-1)*c.cdu_pitch_m
            for label,service,x,zz,split,axis in [
                ('ts','TCS',0,z,False,[0,-1,0]),('tr','TCS',-.65,zr,True,[0,-1,0]),
                ('fs','FWS',-6,z,True,[0,-1,0]),('fr','FWS',-6.65,zr,False,[0,-1,0])]:
                common,other,branch=self.junction([x,y,zz],axis,[-1,0,0] if service=='TCS' else [1,0,0],
                    service,'main',[self.collector(range(1,i),service),self.cdu(i,service)],(None,None,None),
                    split=split,last=i==1)
                if i>1:
                    if split:self.route(other,previous[label],service,'main',self.collector(range(1,i),service),(None,None,None))
                    else:self.route(previous[label],other,service,'main',self.collector(range(1,i),service),(None,None,None))
                previous[label]=common
                {'ts':ts,'tr':tr,'fs':fs,'fr':fr}[label][i]=branch
        # FWS open boundaries reside at the plant-side interface, not a fabricated plant loop.
        source=self.node([-6,0,z],'FWS','boundary');sink=self.node([-6.65,0,zr],'FWS','boundary')
        self.route(source,previous['fs'],'FWS','main',self.fixed(self.h['fws_total_m3_s']),(None,None,None))
        self.route(previous['fr'],sink,'FWS','main',self.fixed(self.h['fws_total_m3_s']),(None,None,None))
        self.g['metadata'].update(fws_source=source,fws_sink=sink,cdu_pump_nodes={})
        for i in ts:self.cdu_assembly(i,ts[i],tr[i],fs[i],fr[i])
        return previous['ts'],previous['tr']

    def cdu_assembly(self,i,ts,tr,fs,fr):
        c=self.c;g=(None,None,i);y=self.layout['cdu_origin_m'][1]+(i-1)*c.cdu_pitch_m
        shift=self.layout['cdu_origin_m'][0]+4.1
        t=self.cdu(i,'TCS');f=self.cdu(i,'FWS');group_ids=[]
        begin=len(self.g['components'])
        # TCS return branch into CDU, internal HX + pump, then supply discharge.
        a,_=self.part(tr,[-1.0,y,c.header_elevation_m+c.return_elevation_offset_m],'reducer','TCS','cdu',t,g)
        a,iv_return=self.part(a,[-1.25,y,c.header_elevation_m+c.return_elevation_offset_m],'isolation_valve','TCS','cdu',t,g)
        low=self.node([-3.5+shift,y,1.2],'TCS','cdu_port');self.route(a,low,'TCS','cdu',t,g)
        a,_=self.part(low,[-3.7+shift,y,1.2],'strainer','TCS','cdu',t,g,
                      filtration_um=35.0,
                      filtration_basis='OCP Deschutes 3.2/4.2 secondary side filtration 25-44 um; 35 um selected mid-band')
        a,hxs=self.part(a,[-3.9+shift,y,1.2],'cdu_secondary','TCS','cdu',t,g,heat_capacity_W=self.h['cdu_duty_heat_W'])
        # Air separation belongs where temperature is high and pressure low: the
        # return side at pump suction (ASHRAE TC 9.9 Coolant Integrity, Air Management).
        a,_=self.part(a,[-3.95+shift,y,1.2],'air_separator','TCS','cdu',t,g,
                      source_basis='OCP Deschutes 3.2 Spirovent; ASHRAE TC 9.9 air-management placement')
        # The flow-through expansion tank is the TCS pressure reference. It lives
        # in the CDU, not in the distribution network (OCP Deschutes 3.2 / 4.2).
        a,_=self.part(a,[-4.0+shift,y,1.2],'expansion_tank','TCS','cdu',t,g,
                      pressure_reference=True,
                      source_basis='OCP Deschutes 3.2 flow-through expansion tank, front serviceable')
        suction=a
        a,pump=self.part(a,[-4.1+shift,y,1.2],'pump','TCS','cdu',t,g,duty_role='duty')
        discharge=a
        pump['internal_pump_redundancy']='vendor assembly detail unmodelled; CDU redundancy is explicit'
        a,check=self.part(a,[-4.1+shift,y,1.45],'check_valve','TCS','cdu',t,g)
        a,iv_supply=self.part(a,[-4.1+shift,y,1.70],'isolation_valve','TCS','cdu',t,g)
        end=self.node([-.40,y,c.header_elevation_m],'TCS')
        self.route(a,end,'TCS','cdu',t,g)
        self.component('reducer',[end,ts],'TCS','main',t,g)
        # Primary FWS branch; no connection nodes are shared with the TCS.
        a,_=self.part(fs,[-5.6,y,c.header_elevation_m],'reducer','FWS','cdu',f,g)
        a,iv_primary_in=self.part(a,[-5.35,y,c.header_elevation_m],'isolation_valve','FWS','cdu',f,g)
        low=self.node([-5.+shift,y,1.2],'FWS','cdu_port');self.route(a,low,'FWS','cdu',f,g)
        a,_=self.part(low,[-4.8+shift,y,1.2],'strainer','FWS','cdu',f,g,
                      filtration_um=500.0,
                      filtration_basis='OCP Deschutes 4.2 primary side strainer: 500 um')
        a,hxp=self.part(a,[-4.6+shift,y,1.2],'cdu_primary','FWS','cdu',f,g,heat_capacity_W=self.h['cdu_duty_heat_W'])
        a,_=self.part(a,[-4.6+shift,y,1.45],'balancing_valve','FWS','cdu',f,g)
        a,iv_primary_out=self.part(a,[-4.6+shift,y,1.7],'isolation_valve','FWS','cdu',f,g)
        end=self.node([-6.25,y,c.header_elevation_m+c.return_elevation_offset_m],'FWS')
        self.route(a,end,'FWS','cdu',f,g)
        self.component('reducer',[end,fr],'FWS','main',f,g)
        self.g['metadata']['cdu_pump_nodes'][str(i)]={'suction':suction,'discharge':discharge,'pump_component':pump['id']}
        self.g['couplings'].append({'id':f'CDU-{i:02d}','primary_component':hxp['id'],
            'secondary_component':hxs['id'],'heat_W':self.h['total_heat_W']/self.c.cdu_count,
            'design_capacity_W':self.h['cdu_duty_heat_W'],
            'heat_basis':'heat_W is all-online transfer; design_capacity_W is installed N-duty rating',
            'mass_transfer_kg_s':0.,'isolation_components':[x['id'] for x in (iv_return,iv_supply,iv_primary_in,iv_primary_out)],
            'nonreturn_component':check['id'],'component_ids':[x['id'] for x in self.g['components'][begin:]]})


def generate(c,profile=None):
    c.validate();b=Builder(c,profile);s,r=b.collectors();b.distribution(s,r)
    units=list(range(1,c.cdu_count+1))
    b.g['scenarios']=[{'name':'all_online','kind':'operating','active_cdus':units,'control_assumption':'Flow is unassigned in manual mode; equal sharing is only a sizing assumption'}]
    for offline in combinations(units,c.redundancy):
        inactive=[b.g['couplings'][i-1] for i in offline]
        b.g['scenarios'].append({'name':'duty_'+('_'.join(map(str,offline)) or 'all'),'kind':'design',
            'active_cdus':[i for i in units if i not in offline],
            'closed_components':[x for q in inactive for x in q['isolation_components']],
            'disabled_components':[x for q in inactive for x in q['component_ids']],
            'control_assumption':'Sizing assumption only; operating flow allocation belongs to downstream software'})
    for i,coupling in enumerate(b.g['couplings'],1):
        coupling['scenario_heat_W']={s['name']:(b.h['total_heat_W']/len(s['active_cdus']) if i in s['active_cdus'] else 0.) for s in b.g['scenarios']}
    b.g['metadata']['standards']=b.P.manifest()
    b.g['metadata']['redundancy']={'total_units':c.cdu_count,
        'duty_units':c.cdu_count-c.redundancy,'spare_units':c.redundancy,
        'capacity_per_cdu_W':b.h['cdu_duty_heat_W'],
        'scope':'CDU unit outages only; common supply/return headers are single points of failure'}
    return b.g


def route_graph(g):
    nodes={n['id']:n for n in g['nodes']}
    for n in nodes.values():n['xyz_m']=n['route_hint_m'].copy()
    for e in g['edges']:
        if e['kind']=='pipe':
            a=nodes[e['from_node']]['xyz_m'];b=nodes[e['to_node']]['xyz_m']
            if sum(abs(a[i]-b[i])>1e-9 for i in range(3))!=1:raise ValueError('Nonorthogonal straight pipe')
            e['length_m']=dist(a,b);e['provenance']['length']='calculated from routed connection coordinates'
    g['metadata']['routing_status']='Orthogonal centre-lines; no clash, support, seismic or vendor-envelope validation'
    g['metadata']['pipe_length_m']=sum(e['length_m'] for e in g['edges'] if e['kind']=='pipe')
    return g
