"""Conceptual installation placement and geometric checks; no pressure solver.

All numeric clearances and attachment envelopes are project assumptions. A
placement is not structural/seismic qualification, detector commissioning or a
fabrication release. Physical inline flexibility must exist in the flow graph.
"""
from __future__ import annotations
import math
from collections import defaultdict
from types import SimpleNamespace
from standards import CATEGORY_OF

ATTACHMENT_KINDS = {'pipe_support', 'seismic_brace_transverse', 'seismic_brace_longitudinal',
                    'vent', 'drain', 'drip_tray', 'leak_detector'}
GENERATOR = 'installation-placement-v2'


def _config(graph, config=None):
    return config if config is not None else SimpleNamespace(**graph.get('metadata', {}).get('config', {}))


def _point(node):
    point = node.get('xyz_m') or node.get('route_hint_m')
    return list(map(float, point)) if point is not None and len(point) == 3 else None


def _flag(config, name, default=True):
    return bool(getattr(config, name, default))


def _cat_name(service, level):
    return CATEGORY_OF.get((service, level), CATEGORY_OF.get((service, 'main')))


def check_layout(c, profile, graph=None) -> dict:
    """Check the active project dimensions; optional graph enables OD checks.

    Deschutes constraints are separately identified reference comparisons only
    when that module is explicitly selected; project defaults are not silently
    replaced with the older profile's dimensions.
    """
    results = []
    def check(name, ok, actual, required, detail, basis='PROJECT ASSUMPTION'):
        results.append({'check': name, 'status': 'NOT_EVALUABLE' if ok is None else ('PASS' if ok else 'FAIL'),
                        'actual': actual, 'required': required, 'source': basis,
                        'parameter_status': 'assumption', 'detail': detail})
    check('Rack pitch accommodates rack width', c.rack_pitch_m >= c.rack_width_m,
          c.rack_pitch_m, c.rack_width_m, 'm centre spacing versus physical rack width')
    check('Rack front/rear service allowance fits aisle', c.aisle_width_m >= max(c.rack_front_clearance_m, c.rack_rear_clearance_m),
          c.aisle_width_m, max(c.rack_front_clearance_m, c.rack_rear_clearance_m),
          'm. Shared access aisle; simultaneous opposing service operations are not validated.')
    check('Rack manifold below header', c.manifold_elevation_m < c.header_elevation_m,
          c.manifold_elevation_m, c.header_elevation_m, 'm; geometric hierarchy only')
    if graph is not None:
        from verify import clearance_diagnostics
        geometry = clearance_diagnostics(graph, c)
        results.extend(geometry['checks'])
    else:
        check('Routed outside-surface clearances', None, None, c.pipe_clear_gap_m,
              'm. Pass routed graph as third argument; centreline elevations cannot establish surface clearance.')
    if getattr(c, 'standards_profile', 'project') == 'deschutes_module':
        from standards import LAYOUT
        check('Selected Deschutes module rack pitch', abs(c.rack_pitch_m-(LAYOUT['rack_width_m'].value+LAYOUT['rack_gap_m'].value)) < 1e-6,
              c.rack_pitch_m, LAYOUT['rack_width_m'].value+LAYOUT['rack_gap_m'].value,
              'm; reference comparison for explicitly selected module', 'OCP Deschutes profile; inspect source register')
    failures = [r for r in results if r['status'] == 'FAIL']
    return {'results': results, 'pass_count': sum(r['status']=='PASS' for r in results),
            'fail_count': len(failures), 'failures': failures,
            'derived': {'rack_pitch_m': c.rack_pitch_m,
                        'row_length_m': (c.racks_per_row-1)*c.rack_pitch_m+c.rack_width_m,
                        'supply_header_m': c.header_elevation_m,
                        'return_header_m': c.header_elevation_m+c.return_elevation_offset_m},
            'note': 'Project geometric diagnostics, not standards compliance. Structural capacities, '
                    'vendor equipment envelopes, insulation and access procedures require review.'}


def extrema_targets(graph) -> dict:
    """Find every routed high/low plateau over ALL hydraulic component kinds.

    A connected horizontal plateau needs one conceptual vent/drain if every
    adjoining segment descends/ascends. Tee centres are included, so branches
    and equipment endpoints cannot disappear from the local-extrema test.
    Internal equipment traps and valve-isolated volumes remain unmodelled.
    """
    nodes = {n['id']: _point(n) for n in graph.get('nodes', [])}
    points = {k: v for k, v in nodes.items() if v is not None}
    adj = defaultdict(set); hosts = defaultdict(set)
    comps = {c['id']: c for c in graph.get('components', [])}
    active = {e['component_id'] for e in graph.get('edges', [])}
    for cid in sorted(active):
        comp = comps.get(cid, {}); ports = [n for n in comp.get('ports', []) if n in points]
        if len(ports) < 2 or comp.get('attachment'): continue
        center = comp.get('center_m') or comp.get('center_xyz_m')
        if comp.get('kind') in ('tee','elbow') and center is not None:
            virtual = '@center:' + cid; points[virtual] = list(map(float, center))
            pairs = [(virtual, n) for n in ports]
            hosts[virtual].add(cid)
        else:
            pairs = [(e['from_node'],e['to_node']) for e in graph['edges']
                     if e['component_id']==cid and e['from_node'] in points and e['to_node'] in points]
        for a,b in pairs:
            adj[a].add(b);adj[b].add(a);hosts[a].add(cid);hosts[b].add(cid)
    seen=set(); output={'high_points': [], 'low_points': []}
    for start in sorted(adj):
        if start in seen: continue
        plateau=set(); pending=[start]; z=points[start][2]
        while pending:
            n=pending.pop()
            if n in plateau: continue
            plateau.add(n);seen.add(n)
            pending.extend(q for q in adj[n] if q not in plateau and abs(points[q][2]-z)<=1e-6)
        neighbors={q for n in plateau for q in adj[n] if q not in plateau}
        if not neighbors: continue
        deltas=[points[n][2]-z for n in neighbors]
        kind='high_points' if all(d < -1e-6 for d in deltas) else ('low_points' if all(d > 1e-6 for d in deltas) else None)
        if not kind: continue
        # Prefer a real junction point, then a pipe host for service accessibility.
        chosen=min(plateau,key=lambda n:(n.startswith('@'), -len(adj[n]), n))
        cid=min(hosts[chosen],key=lambda h:(comps[h].get('kind')!='pipe', h))
        output[kind].append({'id': ('HIGH:' if kind=='high_points' else 'LOW:')+min(plateau),
                             'node_ids':sorted(plateau),'point_m':points[chosen],
                             'host_component':cid,'service':comps[cid].get('service','')})
    return output


def leak_targets(graph):
    """Conservative project placement scope, not a sensor range calculation."""
    return [c for c in graph.get('components', []) if
            (c.get('kind')=='pipe' and c.get('level') in ('row','main')) or
            c.get('kind') in ('rack_load','cdu_primary','cdu_secondary')]


class _Placer:
    def __init__(self, graph):
        self.g=graph;self.nodes={n['id']:n for n in graph['nodes']};self.added=[]
        self.ids={c['id'] for c in graph['components']};self.count=defaultdict(int)
    def xyz(self,nid): return _point(self.nodes[nid])
    def attach(self,kind,xyz,host,extra=None):
        service=host.get('service',''); prefix={'pipe_support':'SUP','seismic_brace_transverse':'SBT',
            'seismic_brace_longitudinal':'SBL','vent':'AV','drain':'DR','drip_tray':'DT','leak_detector':'LD'}[kind]
        base=f'{service}-{prefix}';self.count[base]+=1;cid=f'{base}-{self.count[base]:04d}'
        while cid in self.ids:
            self.count[base]+=1;cid=f'{base}-{self.count[base]:04d}'
        self.ids.add(cid)
        nid='ATT:'+cid
        if nid in self.nodes: raise ValueError(f'Attachment node ID collision: {nid}')
        node={'id':nid,'kind':'attachment_point','xyz_m':list(xyz),'route_hint_m':list(xyz),'service':service,'generated_by':GENERATOR}
        self.g['nodes'].append(node);self.nodes[nid]=node
        comp={'id':cid,'tag':cid,'kind':kind,'ports':[nid],'service':service,'level':host.get('level',''),
              'row':host.get('row'),'rack':host.get('rack'),'cdu':host.get('cdu'),
              'schematic_group':f'{service}-INSTALLATION-{host.get("level","")}',
              'attachment':True,'hydraulic_element':False,'host_component':host['id'],'xyz_m':list(xyz),
              'generated_by':GENERATOR,'status':'conceptual',
              'assumptions':['PROJECT ASSUMPTION: conceptual location/envelope; vendor and structural qualification absent']}
        comp.update(extra or {});self.g['components'].append(comp);self.added.append(comp);return comp


def place_installation(graph, profile, config=None) -> dict:
    """Place enabled accessories. Idempotent for objects generated here.

    Run after diameter assignment and routing. Equipment envelopes may be added
    before or after placement; final diagnostics must run after equipment().
    """
    c=_config(graph,config)
    graph['components'][:]=[x for x in graph['components'] if x.get('generated_by')!=GENERATOR]
    graph['nodes'][:]=[x for x in graph['nodes'] if x.get('generated_by')!=GENERATOR]
    pl=_Placer(graph); original=list(graph['components']); comps={x['id']:x for x in original}
    bycomp=defaultdict(list)
    for edge in graph['edges']:bycomp[edge['component_id']].append(edge)
    unresolved=[]
    for comp in original:
        if comp.get('kind')!='pipe' or len(comp.get('ports',[]))!=2: continue
        es=bycomp[comp['id']]
        if not es: continue
        edge=es[0];a,b=map(pl.xyz,comp['ports'])
        if a is None or b is None:continue
        length=math.dist(a,b);cat=_cat_name(comp.get('service'),comp.get('level'))
        if cat not in profile.categories:continue
        nps=edge.get('nominal_size_in') or comp.get('nominal_size_in')
        if not nps:
            unresolved.append({'component_id':comp['id'],'reason':'No assigned nominal bore for support/bracing lookup'});continue
        if _flag(c,'include_supports'):
            span=float(profile.support_span_m(cat,float(nps)))
            n=max(1,math.ceil(length/span)) if length>1e-9 else 0
            for i in range(n):
                t=(i+.5)/n;point=[a[k]+(b[k]-a[k])*t for k in range(3)]
                pl.attach('pipe_support',point,comp,{'max_span_m':span,'supported_length_m':length/n,
                          'station_m':length*t,'nominal_size_in':nps,
                          'span_source':profile.categories[cat].support_span_source,
                          'notes':'Published preliminary span selection; midpoint spacing and end cantilevers only. No structural sizing.'})
        if _flag(c,'include_seismic_braces',False) and float(nps)>=profile.categories[cat].seismic_brace_min_nps_in.value:
            for kind,key in (('seismic_brace_transverse','seismic_transverse_spacing_m'),('seismic_brace_longitudinal','seismic_longitudinal_spacing_m')):
                spacing=float(profile[key]);n=max(1,math.ceil(length/spacing))
                for i in range(n):
                    t=(i+.5)/n
                    pl.attach(kind,[a[k]+(b[k]-a[k])*t for k in range(3)],comp,
                              {'spacing_m':spacing,'station_m':t*length,'notes':'PROJECT ASSUMPTION: preliminary per-segment brace layout; hazard, loads, anchors and exemptions unverified.'})
    if _flag(c,'include_supports'):
        for comp in original:
            if comp.get('kind') in ('elbow','tee','isolation_valve','balancing_valve','check_valve','strainer') and comp.get('ports'):
                point=pl.xyz(comp['ports'][0])
                if point is not None:pl.attach('pipe_support',point,comp,{'reason':'concentrated fitting/valve load','notes':'Conceptual fitting support; load/anchor design unverified.'})
    targets=extrema_targets(graph)
    for collection,kind,flag in (('high_points','vent','include_vents'),('low_points','drain','include_drains')):
        if not _flag(c,flag):continue
        for target in targets[collection]:
            pl.attach(kind,target['point_m'],comps[target['host_component']],
                      {'normal_position':'normally closed','target_point_id':target['id'],
                       'covered_node_ids':target['node_ids'],'notes':'One conceptual attachment per routed extremum plateau. Internal traps and valve-isolated volumes are unverified.'})
    for comp in original:
        ports=comp.get('ports',[])
        pts=[pl.xyz(n) for n in ports]
        if not pts or any(p is None for p in pts):continue
        point=[sum(p[k] for p in pts)/len(pts) for k in range(3)]
        od=max([float(e.get('od_m') or 0) for e in bycomp.get(comp['id'],[])]+[float(comp.get('od_m') or 0)])
        point[2]=max(.01,point[2]-od/2-.10)
        if _flag(c,'include_drip_trays') and comp.get('kind')=='pipe' and comp.get('level') in ('row','main'):
            pl.attach('drip_tray',point,comp,{'notes':'Conceptual tray below piping; a tray does not detect leakage.'})
    if _flag(c,'include_leak_detection'):
        for comp in leak_targets(graph):
            pts=[pl.xyz(n) for n in comp.get('ports',[])]
            if not pts or any(p is None for p in pts):continue
            point=[sum(p[k] for p in pts)/len(pts) for k in range(3)];point[2]=max(.01,point[2]-.15)
            pl.attach('leak_detector',point,comp,{'monitored_component_ids':[comp['id']],
                      'detection_technology':'conceptual point sensor','sensor_selection_status':'unselected',
                      'notes':'Sensor object explicitly modelled; sensing extent, cable route, controller, alarms and commissioning remain unresolved.'})
    if _flag(c,'include_flex_connectors') and not any(x.get('kind')=='flex_connector' and len(x.get('ports',[]))==2 for x in original):
        unresolved.append({'requirement':'inline rack flexibility',
                           'reason':'Only two-port inline flex_connector graph elements establish flexibility. Placement does not create one-port hose placeholders.'})
    tally=defaultdict(int)
    for comp in pl.added:tally[comp['kind']]+=1
    report={'added_component_count':len(pl.added),'by_kind':dict(sorted(tally.items())),
            'attachments_are_hydraulic_elements':False,'extrema_targets':targets,'unresolved':unresolved,
            'enabled_controls':{name:getattr(c,name,None) for name in ('include_supports','include_seismic_braces','include_vents','include_drains','include_drip_trays','include_leak_detection','include_flex_connectors')},
            'note':'Conceptual installation placement; actual inline flexible elements belong to the hydraulic graph. No structural, leak-detection performance or standards compliance claim.'}
    graph.setdefault('metadata',{})['installation']=report
    return report


def installation_diagnostics(graph,config,profile):
    comps=graph['components'];targets=extrema_targets(graph);checks=[]
    def check(name,actual,expected,enabled=True):
        checks.append({'check':name,'actual':actual,'required':expected,'status':('PASS' if actual==expected else 'FAIL') if enabled else 'DISABLED','source':'Project installation choice; conceptual geometry only'})
    for kind,flag,target in [('vent','include_vents','high_points'),('drain','include_drains','low_points')]:
        needed={p['id'] for p in targets[target]};covered={c.get('target_point_id') for c in comps if c['kind']==kind}
        check('All routed '+kind+' plateaus covered',len(needed&covered),len(needed),getattr(config,flag))
    needed={c['id'] for c in leak_targets(graph)}
    covered={p for c in comps if c['kind']=='leak_detector' for p in c.get('monitored_component_ids',[])}
    check('Leak sensors at liquid equipment',len(needed&covered),len(needed),config.include_leak_detection)
    edgeids={e['component_id'] for e in graph['edges']}
    for r in range(1,config.rows+1):
        for k in range(1,config.racks_per_row+1):
            count=sum(c['kind']=='flex_connector' and c.get('row')==r and c.get('rack')==k and len(c['ports'])==2 and c['id'] in edgeids for c in comps)
            check(f'R{r:02} rack {k:02} inline flexibility',count,2,config.include_flex_connectors)
    return {'checks':checks,'fail_count':sum(c['status']=='FAIL' for c in checks),'note':'Closed vent/drain attachment locations are conceptual. No structural or detector performance validation.'}
