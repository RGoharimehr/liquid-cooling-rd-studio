"""Shared graph builder: identities, ports, fittings and routed lengths.

`network_v2.NetworkBuilder` subclasses `Builder` and supplies the in-hall and
plant geometry. This module owns only what both share.
"""
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


def _retired():
    """The v1 in-hall generator (collectors/distribution/racks/cdu_assembly and
    a module-level generate()) lived here until it was removed. network_v2
    replaced every one of those methods, and keeping the old bodies around meant
    the repository held two divergent answers for the same geometry. Use
    `network_v2.generate`."""


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
