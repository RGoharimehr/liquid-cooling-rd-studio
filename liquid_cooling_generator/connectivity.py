"""Graph reachability under component isolation; no capacity/redundancy solver."""
from collections import defaultdict

def evaluate(g,c):
    comps={x['id']:x for x in g['components']};couplings=g['couplings']
    cdus=[x for x in g['components'] if x['kind']=='cdu']
    scenarios=[]
    cases=[('all_online',set())]
    cases += [(x['id']+'_isolated',{x['id']}|set(next((a['isolation_components'] for a in couplings if a.get('primary_component')==x['id']),[]))) for x in cdus]
    cases += [(x['id']+'_isolated',{x['id']}) for x in g['components'] if x['kind'] in ('pump','chiller','cooling_tower') and x.get('zone')=='plant']
    for name,closed in cases:
        adjacency=defaultdict(set)
        for edge in g['edges']:
            if edge['component_id'] in closed:continue
            # Remove all equipment internal edges while finding external supply/return paths.
            if edge.get('internal'):continue
            a,b=edge['from_node'],edge['to_node'];adjacency[a].add(b);adjacency[b].add(a)
        def reached(start):
            seen=set(start);todo=list(start)
            while todo:
                for n in adjacency[todo.pop()]-seen:seen.add(n);todo.append(n)
            return seen
        unavailable=[]
        for rack in (x for x in g['components'] if x['kind']=='compute_rack'):
            a,b=rack['ports'];ra=reached([a]);rb=reached([b]);ok=False
            for cdu in cdus:
                if cdu['id'] in closed:continue
                tcs=[p['node_id'] for p in cdu['port_details'] if p['service']=='TCS']
                if len(tcs)==2 and ((tcs[0] in ra and tcs[1] in rb) or (tcs[1] in ra and tcs[0] in rb)):ok=True
            if not ok:unavailable.append(rack['id'])
        activeplant={kind:[x['id'] for x in comps.values() if x['kind']==kind and x['id'] not in closed and x.get('zone')=='plant'] for kind in ('pump','chiller','cooling_tower')}
        scenarios.append({'name':name,'closed_components':sorted(closed),'unconnected_compute_racks':unavailable,
            'tcs_path_status':'PASS' if not unavailable else 'UNAVAILABLE','available_plant_components':activeplant,
            'capacity_status':'NOT_EVALUABLE','operational_redundancy_proven':False})
    return {'scope':'Undirected external fluid-path reachability with selected component edges removed. Does not establish flow, pressure, capacity, controls or operational redundancy. Plant availability lists are counts, not proof of complete plant operation.', 'scenarios':scenarios}
