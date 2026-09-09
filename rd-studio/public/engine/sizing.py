"""Commercial dimensions and optional heat-balance estimates; no pressure solver."""
from collections import defaultdict
from math import pi
from hydraulics import CATALOGUES, select_size, scenario_flow, heat_flows


def apply_sizes(graph, config):
    groups=defaultdict(list)
    scenarios=[s for s in graph['scenarios'] if s['kind']=='design']
    manual=config.sizing_mode=='manual'
    for edge in graph['edges']:
        service=edge['service'];level=edge['level']
        if manual:
            key=('rack' if level in ('rack','row_branch') else 'row') if service=='TCS' and level not in ('main','cdu') else service.lower()+'_'+level
            key=edge.get('pipe_family',key)
            nominal=getattr(config,key+'_nominal_in')
            table,standard=CATALOGUES[edge['material']]
            match=next((x for x in table if x[0]==nominal),None)
            if not match:raise ValueError(f'{nominal} in is unavailable in {edge["material"]}; select a listed nominal size')
            n,od,wall=match
            dims={'nominal_size_in':n,'od_m':od*.0254,'id_m':(od-2*wall)*.0254,'wall_m':wall*.0254,'required_id_m':0,'size_standard':standard}
            edge['design_flow_m3_s']=edge['flow_m3_s']=0.0
        else:
            edge['design_flow_m3_s']=max(scenario_flow(edge,s['active_cdus']) for s in scenarios)
            edge['flow_m3_s']=scenario_flow(edge,list(range(1,config.cdu_count+1)))
            dims=select_size(max(edge['design_flow_m3_s'],edge.get('sizing_flow_m3_s',0)),edge['material'],edge['velocity_cap_m_s'])
        edge.update(dims)
        edge['velocity_m_s']=edge['design_flow_m3_s']/(pi*edge['id_m']**2/4)
        edge['velocity_cap_pass']=edge['velocity_m_s']<=edge['velocity_cap_m_s']
        edge['hydraulic_result_basis']='unassigned; manual geometry sizing' if manual else 'heat balance with prescribed flow split; pressure not evaluated'
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
    graph['hydraulics']={'mode':config.sizing_mode,'pressure_analysis_performed':False,'flow_assignment':'unassigned' if manual else 'prescribed heat-balance estimates','heat_and_flow':heat_flows(config),'scope':'No pump, pressure, or nonlinear network solution. Equipment maps belong in downstream software.'}
    return graph['hydraulics']
