"""Apply commercial pipe dimensions to the graph. No pressure solver lives here.

Flow, pressure loss and duties come from `preliminary_sizing`, which runs after
this and writes its results back onto the same edges. This module only resolves
each pipe family to a bore from the selected catalogue.
"""
from collections import defaultdict
from math import pi
from hydraulics import CATALOGUES, heat_flows


def apply_sizes(graph, config, per_edge=None, per_port=None):
    """Set every edge to the commercial bore its pipe family, or its run, has been given.

    In preliminary mode the caller runs this once with the current nominal
    sizes, asks `preliminary_sizing` for a recommendation, then runs it again
    with the recommended sizes. Flow and loss are left to that module, so they
    are deliberately zeroed here rather than half-assigned.
    """
    per_edge=per_edge or {};per_port=per_port or {}
    groups=defaultdict(list)
    for edge in graph['edges']:
        service=edge['service'];level=edge['level']
        key=('rack' if level in ('rack','row_branch') else 'row') if service=='TCS' and level not in ('main','cdu') else service.lower()+'_'+level
        key=edge.get('pipe_family',key)
        nominal=per_edge.get(edge['id'],getattr(config,key+'_nominal_in'))
        table,standard=CATALOGUES[edge['material']]
        match=next((x for x in table if x[0]==nominal),None)
        if not match:raise ValueError(f'{nominal} in is unavailable in {edge["material"]}; select a listed nominal size')
        n,od,wall=match
        edge.update({'nominal_size_in':n,'od_m':od*.0254,'id_m':(od-2*wall)*.0254,'wall_m':wall*.0254,
                     'required_id_m':0,'size_standard':standard})
        edge['design_flow_m3_s']=edge['flow_m3_s']=0.0
        edge['velocity_m_s']=0.0
        edge['velocity_cap_pass']=True
        edge['hydraulic_result_basis']='commercial bore applied; flow and loss assigned by preliminary_sizing'
        edge['provenance']['flow']=edge['hydraulic_result_basis']
        edge['reference_dp_Pa']=0;edge['K']=0
        groups[edge['component_id']].append(edge)
    incoming=defaultdict(list)
    for e in graph['edges']:incoming[e['to_node']].append(e)
    for comp in graph['components']:
        edges=groups[comp['id']]
        if not edges:continue
        largest=max(edges,key=lambda e:e['od_m'])
        comp.update({k:largest[k] for k in ('nominal_size_in','id_m','od_m','material')})
        comp['port_sizes_in']={};comp['port_od_m']={};comp['port_id_m']={}
        for e in edges:
            for node in (e['from_node'],e['to_node']):
                comp['port_sizes_in'][node]=e['nominal_size_in'];comp['port_od_m'][node]=e['od_m'];comp['port_id_m'][node]=e['id_m']
        if comp['kind']=='reducer':
            e=edges[0];prev=incoming[e['from_node']]
            if prev:
                up=prev[0];node=e['from_node'];comp['port_sizes_in'][node]=up['nominal_size_in'];comp['port_od_m'][node]=up['od_m'];comp['port_id_m'][node]=up['id_m']
                comp['inlet_nominal_size_in']=up['nominal_size_in'];comp['outlet_nominal_size_in']=e['nominal_size_in'];e['inlet_id_m']=up['id_m']
                comp['od_m']=max(up['od_m'],e['od_m'])
        # A run-sized port overrides the family bore its edge carried in, because
        # the run on each side of a fitting is what decides that port's size. The
        # dimensions arrive already resolved in that run's own material.
        for node,dims in per_port.get(comp['id'],{}).items():
            comp['port_sizes_in'][node]=dims['nominal_size_in'];comp['port_od_m'][node]=dims['od_m'];comp['port_id_m'][node]=dims['id_m']
        sizes=sorted({v for v in comp['port_sizes_in'].values() if v})
        # Equipment legitimately has ports of different sizes on different
        # services; only a fitting is described as reducing.
        comp['reducing']=len(sizes)>1 and not comp.get('size_m')
        if comp['reducing']:
            # Describe the fitting by its largest port, taking OD, ID and bore
            # from that one port so the three stay a real pipe section.
            widest=max(comp['port_od_m'],key=lambda n:comp['port_od_m'][n])
            comp['od_m']=comp['port_od_m'][widest];comp['id_m']=comp['port_id_m'][widest]
            comp['nominal_size_in']=comp['port_sizes_in'][widest]
            if comp['kind']=='tee' and len(comp['ports'])==3:
                run=[comp['port_sizes_in'].get(n) for n in comp['ports'][:2]];branch=comp['port_sizes_in'].get(comp['ports'][2])
                if all(run) and branch:
                    comp['reducing_designation']='%g x %g x %g'%(run[0],run[1],branch)
                    comp['reducing_reference']='ASME B16.9 reducing tee, run x run x branch; the listed combination requires confirmation'
            elif comp['kind']=='reducer':
                comp['inlet_nominal_size_in']=comp.get('inlet_nominal_size_in',max(sizes))
                comp['outlet_nominal_size_in']=min(sizes)
                comp['reducing_reference']='Concentric or eccentric reducer; eccentric flat side up on a pump suction'
    graph['hydraulics']={'mode':config.sizing_mode,'pressure_analysis_performed':False,
        'flow_assignment':'assigned by preliminary_sizing after routing',
        'heat_and_flow':heat_flows(config),
        'heat_and_flow_basis':'Declared circuit design flow on the configured basis and fluid properties. '
            'The same derivation produces metadata.preliminary_sizing.thermal_flows; the two must agree.',
        'scope':'No pump, pressure, or nonlinear network solution. Equipment maps belong in downstream software.'}
    return graph['hydraulics']
