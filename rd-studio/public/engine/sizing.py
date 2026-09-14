"""Apply commercial pipe dimensions to the graph. No pressure solver lives here.

Flow, pressure loss and duties come from `preliminary_sizing`, which runs after
this and writes its results back onto the same edges. This module only resolves
each pipe family to a bore from the selected catalogue.
"""
from collections import defaultdict
from math import pi
from hydraulics import CATALOGUES, heat_flows


def apply_sizes(graph, config):
    """Set every edge to the commercial bore its pipe family has been given.

    In preliminary mode the caller runs this once with the current nominal
    sizes, asks `preliminary_sizing` for a recommendation, then runs it again
    with the recommended sizes. Flow and loss are left to that module, so they
    are deliberately zeroed here rather than half-assigned.
    """
    groups=defaultdict(list)
    for edge in graph['edges']:
        service=edge['service'];level=edge['level']
        key=('rack' if level in ('rack','row_branch') else 'row') if service=='TCS' and level not in ('main','cdu') else service.lower()+'_'+level
        key=edge.get('pipe_family',key)
        nominal=getattr(config,key+'_nominal_in')
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
    graph['hydraulics']={'mode':config.sizing_mode,'pressure_analysis_performed':False,
        'flow_assignment':'assigned by preliminary_sizing after routing',
        'heat_and_flow':heat_flows(config),
        'heat_and_flow_basis':'Declared circuit design flow on the configured basis and fluid properties. '
            'The same derivation produces metadata.preliminary_sizing.thermal_flows; the two must agree.',
        'scope':'No pump, pressure, or nonlinear network solution. Equipment maps belong in downstream software.'}
    return graph['hydraulics']
