"""Graph reachability under component isolation; no capacity/redundancy solver."""
from collections import defaultdict

def evaluate(g,c):
    comps={x['id']:x for x in g['components']};couplings=g['couplings']
    cdus=[x for x in g['components'] if x['kind']=='cdu']
    scenarios=[];checks=[]
    cases=[(case['name'],set(case.get('closed_components',[]))|set(case.get('disabled_components',[])),case)
           for case in g.get('scenarios',[])]
    if not cases:cases=[('all_online',set(),{'kind':'operating'})]
    cases += [(x['id']+'_isolated',{x['id']}|set(next((a['isolation_components'] for a in couplings if a.get('primary_component')==x['id']),[])),{'kind':'diagnostic'}) for x in cdus]
    cases += [(x['id']+'_isolated',{x['id']},{'kind':'diagnostic'}) for x in g['components'] if x['kind'] in ('pump','chiller','cooling_tower') and x.get('zone')=='plant']
    for name,closed,source in cases:
        adjacency=defaultdict(set)
        for edge in g['edges']:
            if edge['component_id'] in closed:continue
            # Remove all equipment internal edges while finding external supply/return paths.
            if edge.get('internal'):continue
            a,b=edge['from_node'],edge['to_node'];adjacency[a].add(b);adjacency[b].add(a)
        # Label each connected region once; exhaustive outage combinations must
        # not traverse the entire hall again for every individual rack.
        regions={}
        for start in list(adjacency):
            if start in regions:continue
            region=len(regions);regions[start]=region;todo=[start]
            while todo:
                for node in adjacency[todo.pop()]:
                    if node not in regions:regions[node]=region;todo.append(node)
        def connected(a,b):return a in regions and b in regions and regions[a]==regions[b]
        unavailable=[]
        for rack in (x for x in g['components'] if x['kind']=='compute_rack'):
            a,b=rack['ports'];ok=False
            for cdu in cdus:
                if cdu['id'] in closed:continue
                tcs=[p['node_id'] for p in cdu['port_details'] if p['service']=='TCS']
                if len(tcs)==2 and ((connected(a,tcs[0]) and connected(b,tcs[1])) or (connected(a,tcs[1]) and connected(b,tcs[0]))):ok=True
            if not ok:unavailable.append(rack['id'])
        activeplant={kind:[x['id'] for x in comps.values() if x['kind']==kind and x['id'] not in closed and x.get('zone')=='plant'] for kind in ('pump','chiller','cooling_tower')}
        required=source.get('kind') in ('operating','design')
        scenarios.append({'name':name,'kind':source.get('kind'),'required_design_check':required,
            'closed_components':sorted(closed),'active_cdus':[x['cdu'] for x in cdus if x['id'] not in closed],
            'offline_cdus':[x['cdu'] for x in cdus if x['id'] in closed],
            'unconnected_compute_racks':unavailable,'pod_states':source.get('pod_states',{}),
            'unserved_heat_W':source.get('unserved_heat_W'),
            'tcs_path_status':'PASS' if not unavailable else 'UNAVAILABLE','available_plant_components':activeplant,
            'capacity_status':'NOT_EVALUABLE','operational_redundancy_proven':False})
        if required and unavailable:
            checks.append({'check':'CDU outage connectivity: '+name,'status':'FAIL','actual':unavailable,
                'required':'Every compute rack retains external supply/return paths to an active CDU in its own pod',
                'detail':f'{len(unavailable)} rack(s) lose their CDU path with units {scenarios[-1]["offline_cdus"]} offline. Independent pods cannot borrow CDU capacity from another pod.',
                'actions':['Add and assign enough CDUs to each affected pod to retain one after the requested simultaneous outages.',
                           'Review row/CDU pod assignments or reduce Simultaneous CDU outages only if the project requirement changes.']})
    return {'scope':'Undirected external fluid-path reachability with selected component edges removed. Required cases include all configured simultaneous CDU outages; additional single-equipment isolation cases are diagnostic. Does not establish flow, pressure, capacity, controls or operational redundancy. Plant availability lists are counts, not proof of complete plant operation.',
        'scenarios':scenarios,'checks':checks,'blocking_failures':len(checks)}
