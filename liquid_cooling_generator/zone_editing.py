"""Move complete cooling pods while retaining fixed facility collector connections.

Call relocate_pods before plant generation and relocate_equipment after layout.equipment.
Routes are explicit concept routes and remain subject to ordinary collision checks.
"""
from math import cos, sin, radians, isfinite
from zone_geometry import (transform_zone_point, transform_zone_vector, transform_zone_geometry,
                           transform_spec, move_component, equipment_corners, placement_checks)


def _transform(point, spec, vector=False):
    return transform_zone_vector(point, spec) if vector else transform_zone_point(point, spec)


def _move_component(comp, spec):
    move_component(comp, spec)
    comp['pod_rotation_deg'] = spec['rotation_deg']


def _specs(builder):
    c = builder.c
    origins = getattr(c, 'pod_origins_m', [])
    rotations = getattr(c, 'pod_rotations_deg', [])
    flips_x = getattr(c, 'pod_flip_x', [])
    flips_y = getattr(c, 'pod_flip_y', [])
    if not isinstance(origins, list) or (origins and len(origins) != c.pod_count):
        raise ValueError('pod_origins_m must be empty or contain one [x, y] anchor per pod')
    if not isinstance(rotations, list) or (rotations and len(rotations) != c.pod_count):
        raise ValueError('pod_rotations_deg must be empty or contain one rotation per pod')
    for values in (flips_x, flips_y):
        if not isinstance(values, list) or (values and (len(values) != c.pod_count or any(type(v) is not bool for v in values))):
            raise ValueError('Pod flips must be empty or contain one true/false value per pod')
    result = []
    for pod in range(1, c.pod_count+1):
        rows = [i for i, value in enumerate(builder.rows) if value == pod]
        if not rows:
            raise ValueError(f'Cooling pod {pod} has no assigned compute row')
        original = [0.0, min(builder.layout['compute_row_y_m'][i] for i in rows), 0.0]
        anchor = origins[pod-1] if origins else original[:2]
        if (not isinstance(anchor, list) or len(anchor) != 2 or
                any(type(v) not in (float, int) or not isfinite(v) for v in anchor)):
            raise ValueError(f'Cooling pod {pod} anchor must contain two finite coordinates')
        rotation = (rotations[pod-1] % 360) if rotations else 0
        if type(rotation) not in (float, int) or rotation not in (0, 90, 180, 270):
            raise ValueError('Pod rotations must be 0, 90, 180, or 270 degrees')
        flip_x, flip_y = (flips_x[pod-1] if flips_x else False), (flips_y[pod-1] if flips_y else False)
        result.append({'pod': pod, 'original_anchor_m': original,
                       'anchor_m': [float(anchor[0]), float(anchor[1]), 0.0],
                       'rotation_deg': int(rotation), 'flip_x': flip_x, 'flip_y': flip_y,
                       'moved': bool(rotation or flip_x or flip_y or list(anchor) != original[:2])})
    return result


def relocate_pods(builder):
    """Transform TCS/CDUs, then reconnect moved CDU FWS ports to fixed collectors."""
    b = builder
    if b.g['metadata'].get('pod_relocation_applied'):
        return b.g['metadata']['pod_transforms']
    specs = _specs(b)
    bypod = {spec['pod']: spec for spec in specs}
    components = list(b.g['components'])
    removed_ids = set()
    reconnect = []
    # Discover fixed collector roots before removing any per-CDU FWS components.
    owners = {}
    for comp in components:
        for nid in comp.get('ports', []):
            owners.setdefault(nid, []).append(comp)
    for cdu in [comp for comp in components if comp['kind'] == 'cdu']:
        pod = b.cdus[cdu['cdu']-1]
        if not bypod[pod]['moved']:
            continue
        external = [comp for comp in components if comp.get('cdu') == cdu['cdu']
                    and comp.get('service') == 'FWS' and comp['kind'] != 'cdu']
        ext_ids = {comp['id'] for comp in external}
        root_roles = {}
        for comp in external:
            if comp['kind'] != 'reducer':
                continue
            for index, nid in enumerate(comp['ports']):
                if any(other['id'] not in ext_ids and other['id'] != cdu['id']
                       and other.get('service') == 'FWS' for other in owners[nid]):
                    # Supply reducer starts at its collector; return reducer ends there.
                    root_roles['fs' if index == 0 else 'fr'] = nid
        if set(root_roles) != {'fs', 'fr'}:
            raise ValueError(f"Cannot relocate {cdu['id']}: expected two identifiable FWS collector branches")
        reconnect.append((cdu, root_roles, ext_ids))
        removed_ids.update(ext_ids)

    node_pods = {}
    for comp in components:
        pod = comp.get('pod')
        if comp.get('kind') == 'cdu':
            pod = b.cdus[comp['cdu']-1]
        if pod in bypod and (comp.get('service') == 'TCS' or comp['kind'] == 'cdu'):
            for nid in comp.get('ports', []):
                if nid in node_pods and node_pods[nid] != pod:
                    raise ValueError('Independent pods cannot share a fluid node: '+nid)
                node_pods[nid] = pod
            if bypod[pod]['moved']:
                _move_component(comp, bypod[pod])
    for nid, pod in node_pods.items():
        if bypod[pod]['moved']:
            node = b.n[nid]
            node['route_hint_m'] = _transform(node['route_hint_m'], bypod[pod])
            if node.get('xyz_m') is not None:
                node['xyz_m'] = _transform(node['xyz_m'], bypod[pod])
    b.g['components'] = [comp for comp in components if comp['id'] not in removed_ids]
    b.g['edges'] = [edge for edge in b.g['edges'] if edge['component_id'] not in removed_ids]

    for cdu, roots, replaced in reconnect:
        group = (None, None, cdu['cdu'])
        b.current_pod = b.cdus[cdu['cdu']-1]
        valves = []
        for label, port_index in [('fs', 0), ('fr', 1)]:
            root = roots[label]
            port = cdu['ports'][port_index]
            bx, by, bz = b.xyz(root)
            tx, ty, tz = b.xyz(port)
            if label == 'fs':
                red, _ = b.part(root, [bx+.35, by, bz], 'reducer', 'FWS', 'cdu', b.fixed(0), group)
                start, valve = b.part(red, [bx+.65, by, bz], 'isolation_valve', 'FWS', 'cdu', b.fixed(0), group)
            else:
                start = b.node([bx+.65, by, bz], 'FWS')
                red, valve = b.part(start, [bx+.35, by, bz], 'isolation_valve', 'FWS', 'cdu', b.fixed(0), group)
                b.component('reducer', [red, root], 'FWS', 'main', b.fixed(0), group)
            valves.append(valve['id'])
            # Each CDU/circuit gets a separate elevated lane; geometry and ceiling
            # validation decides whether this concept route is physically feasible.
            radius = b.c.bend_radius_m
            lead = max(1.0, 3*radius+.05)
            top = max(bz, tz, b.c.header_elevation_m+b.c.return_elevation_offset_m) + 1.0
            top += (.35 if label == 'fr' else 0.0)
            spec=bypod[b.current_pod]
            if spec['rotation_deg'] or spec.get('flip_x') or spec.get('flip_y') or abs(spec['anchor_m'][1]-spec['original_anchor_m'][1])>.5:top+=(cdu['cdu']-1)*.8
            xx = bx+.65+lead
            yy = min(by, ty)-lead-(.4 if label == 'fr' else 0.0)
            path = [[xx, by, bz], [xx, by, top], [xx, yy, top],
                    [tx, yy, top], [tx, ty, top]]
            try:
                if label == 'fs':
                    b.route_path(start, port, path, 'FWS', 'cdu', b.fixed(0), group)
                else:
                    b.route_path(port, start, list(reversed(path)), 'FWS', 'cdu', b.fixed(0), group)
            except ValueError as exc:
                raise ValueError(f"{cdu['id']} {label} relocation cannot fit an explicit route: {exc}") from exc
        for coupling in b.g['couplings']:
            if coupling['id'] == cdu['id']:
                for key in ('isolation_components', 'component_ids'):
                    coupling[key] = [cid for cid in coupling.get(key, []) if cid not in replaced] + valves
    # Drop obsolete branch nodes, retaining Builder.n so new node numbers stay unique.
    used = {nid for comp in b.g['components'] for nid in comp.get('ports', [])}
    b.g['nodes'] = [node for node in b.g['nodes'] if node['id'] in used]
    b.g['metadata']['pod_transforms'] = specs
    b.g['metadata']['pod_relocation_applied'] = True
    b.g['metadata']['pod_relocation_scope'] = 'Fixed FWS collectors; moved TCS and CDU envelopes. Reconnected routes require collision/ceiling review.'
    return specs


def _bounds(items):
    points = []
    for item in items:
        if item.get('center_m') is not None and item.get('size_m') is not None:
            center, size = item['center_m'], item['size_m']
            points.extend([[center[k]+sign*size[k]/2 for k in range(3)] for sign in (-1, 1)])
    if not points:
        return None
    return {'min': [min(p[k] for p in points) for k in range(3)],
            'max': [max(p[k] for p in points) for k in range(3)]}


def relocate_equipment(graph, config):
    """Move later-created compute boxes/service zones; advertise draggable anchors."""
    specs = graph['metadata'].get('pod_transforms', [])
    if not specs:
        raise ValueError('Call relocate_pods before relocate_equipment')
    if graph['layout'].get('pod_equipment_relocated'):
        return graph['layout']['editable_zones']
    rows = graph['metadata'].get('pod_assignments', {}).get('rows')
    if rows is None:
        explicit = getattr(config, 'row_pod_assignments', [])
        rows = explicit or [min(config.pod_count, i*config.pod_count//config.rows+1) for i in range(config.rows)]
    bypod = {spec['pod']: spec for spec in specs}
    for comp in graph['components']:
        if comp['kind'] == 'compute_rack':
            pod = rows[comp['row']-1]
            comp['pod'] = pod
            if bypod[pod]['moved']:
                _move_component(comp, bypod[pod])
    for zone in graph['layout'].get('clearance_zones', []):
        host = zone.get('host', '')
        if host.startswith('IT-R'):
            row = int(host[4:6])
            pod = rows[row-1]
            zone['pod'] = pod
            if bypod[pod]['moved']:
                _move_component(zone, bypod[pod])
    zones = []
    for spec in specs:
        members = [comp for comp in graph['components'] if comp.get('pod') == spec['pod']
                   and comp['kind'] in ('compute_rack', 'cdu')]
        zones.append({'id': f"pod-{spec['pod']}", 'kind': 'cooling_pod',
                      'pod': spec['pod'], 'label': f"Cooling pod {spec['pod']}",
                      'anchor_m': spec['anchor_m'], 'original_anchor_m': spec['original_anchor_m'],
                      'rotation_deg': spec['rotation_deg'], 'flip_x':spec.get('flip_x',False), 'flip_y':spec.get('flip_y',False), 'bounds_m': _bounds(members),
                      'equipment_ids': [comp['id'] for comp in members],
                      'coordinate_frame': 'layout', 'origin_parameter': 'pod_origins_m',
                      'rotation_parameter': 'pod_rotations_deg', 'flip_x_parameter':'pod_flip_x', 'flip_y_parameter':'pod_flip_y'})
    for kind, label, members, anchor, rotation in [
            ('network_zone', 'Network racks', [comp for comp in graph['components'] if comp['kind'] == 'network_rack'],
             graph['layout']['network_origin_m'], getattr(config,'network_rotation_deg',0)),
            ('plant', 'Cooling plant', [comp for comp in graph['components'] if comp.get('zone') == 'plant' and comp.get('size_m')],
             [config.plant_origin_x_m, config.plant_origin_y_m, config.plant_elevation_m], config.plant_rotation_deg)]:
        if members:
            prefix = 'network' if kind == 'network_zone' else 'plant'
            zones.append({'id': kind, 'kind': kind, 'label': label, 'anchor_m': anchor,
                          'rotation_deg': rotation, 'bounds_m': _bounds(members),
                          'flip_x':getattr(config,prefix+'_flip_x',False), 'flip_y':getattr(config,prefix+'_flip_y',False),
                          'rotation_parameter':prefix+'_rotation_deg', 'flip_x_parameter':prefix+'_flip_x', 'flip_y_parameter':prefix+'_flip_y',
                          'equipment_ids': [comp['id'] for comp in members], 'coordinate_frame': 'layout'})
    graph['layout']['editable_zones'] = zones
    graph['layout']['pod_equipment_relocated'] = True
    return zones


def footprint_check(graph, config):
    """Check world-coordinate mesh/envelope extents after the final layout transform."""
    width = getattr(config, 'site_footprint_width_m', 0)
    depth = getattr(config, 'site_footprint_depth_m', 0)
    if width <= 0 and depth <= 0:
        return {'status': 'NOT_EVALUABLE', 'checks': [], 'detail': 'Site footprint is not declared'}
    if width <= 0 or depth <= 0:
        return {'status': 'FAIL', 'checks': [], 'detail': 'Declare both positive site footprint dimensions'}
    x = config.site_footprint_origin_x_m
    y = config.site_footprint_origin_y_m
    checks = []
    for comp in graph['components']:
        points = comp.get('mesh', {}).get('vertices', []) if comp.get('mesh') else []
        if not points and comp.get('size_m') and comp.get('center_m'):
            bounds = _bounds([comp])
            points = [bounds['min'], bounds['max']]
        if not points:
            continue
        low = [min(p[k] for p in points) for k in range(2)]
        high = [max(p[k] for p in points) for k in range(2)]
        outside = low[0] < x-1e-8 or low[1] < y-1e-8 or high[0] > x+width+1e-8 or high[1] > y+depth+1e-8
        if outside:
            checks.append({'check': 'Declared site footprint', 'component': comp['id'], 'status': 'FAIL',
                           'actual': {'min': low, 'max': high},
                           'required': {'min': [x, y], 'max': [x+width, y+depth]},
                           'detail': 'Component geometry extends beyond the declared footprint'})
    # The reservation is part of the usable footprint too. Keep Apply consistent
    # with the zone editor, including rotated service envelopes in world space.
    checks.extend(placement_checks([], graph['layout'].get('clearance_zones', []),
                                   footprint=(x, y, width, depth)))
    return {'status': 'FAIL' if checks else 'PASS', 'checks': checks,
            'coordinate_frame': 'world', 'detail': 'Checks declared physical extents; does not establish property-line or planning compliance'}


def propose_zone_edit(graph, config, zone_id, *, anchor_m=None, rotation_deg=None, flip_x=None, flip_y=None):
    """Read-only world-coordinate placement trial; full routing follows Apply."""
    from dataclasses import asdict
    from copy import deepcopy
    zones=graph['layout'].get('editable_zones',[])
    zone=next((z for z in zones if z['id']==zone_id),None)
    if zone is None:raise ValueError('Select one of the generated equipment zones before arranging it.')
    if anchor_m is not None and (not isinstance(anchor_m,list) or len(anchor_m) not in (2,3) or any(type(v) not in (int,float) or not isfinite(v) for v in anchor_m)):
        raise ValueError('Zone location needs finite x and y coordinates in metres.')
    angle=radians(config.layout_rotation_deg);co,si=cos(angle),sin(angle)
    def local(p):
        x,y=p[0]-config.layout_origin_x_m,p[1]-config.layout_origin_y_m
        return [x*co+y*si,-x*si+y*co,p[2] if len(p)>2 else 0.]
    def world(p):return [co*p[0]-si*p[1]+config.layout_origin_x_m,si*p[0]+co*p[1]+config.layout_origin_y_m,p[2]]
    old_anchor=list(zone.get('anchor_layout_m',local(zone['anchor_m'])))
    new_anchor=local(anchor_m) if anchor_m is not None else old_anchor
    new_anchor[2]=old_anchor[2]
    old=transform_spec(old_anchor,zone.get('rotation_deg',0),zone.get('flip_x',False),zone.get('flip_y',False))
    new=transform_spec(new_anchor,old['rotation_deg'] if rotation_deg is None else rotation_deg,
                       old['flip_x'] if flip_x is None else flip_x,old['flip_y'] if flip_y is None else flip_y)
    candidate=asdict(config);member_ids=set(zone['equipment_ids'])
    if zone.get('pod'):
        pods=sorted((z for z in zones if z.get('pod')),key=lambda z:z['pod']);idx=zone['pod']-1
        for key,value,default in [('pod_origins_m',new_anchor[:2],lambda z:list(z.get('anchor_layout_m',local(z['anchor_m'])))[:2]),
                                  ('pod_rotations_deg',new['rotation_deg'],lambda z:z.get('rotation_deg',0)),
                                  ('pod_flip_x',new['flip_x'],lambda z:z.get('flip_x',False)),
                                  ('pod_flip_y',new['flip_y'],lambda z:z.get('flip_y',False))]:
            values=deepcopy(candidate[key]) or [default(z) for z in pods];values[idx]=value;candidate[key]=values
    else:
        prefix='network' if zone['kind']=='network_zone' else 'plant'
        if prefix=='network':
            candidate['network_offset_x_m']+=new_anchor[0]-old_anchor[0];candidate['network_offset_y_m']+=new_anchor[1]-old_anchor[1]
        else:candidate.update(plant_origin_x_m=new_anchor[0],plant_origin_y_m=new_anchor[1])
        candidate.update({prefix+'_rotation_deg':new['rotation_deg'],prefix+'_flip_x':new['flip_x'],prefix+'_flip_y':new['flip_y']})
    def belongs(item):
        if item['id'] in member_ids:return True
        host=item.get('host','')
        return host in member_ids or (host.startswith('IT-R') and any(cid.startswith(host+'-') for cid in member_ids))
    def moved(p):
        relative=[local([*p,0.])[i]-old_anchor[i] for i in range(3)]
        unrotated=transform_zone_vector(relative,old,inverse=True)
        rotated=transform_zone_vector(unrotated,new)
        return world([rotated[i]+new_anchor[i] for i in range(3)])[:2]
    bodies=[c for c in graph['components'] if c.get('size_m') and not c.get('attachment')]
    clearances=graph['layout'].get('clearance_zones',[])
    polygons={item['id']:[moved(p) for p in equipment_corners(item)] for item in [*bodies,*clearances] if belongs(item)}
    footprint=None
    if config.site_footprint_width_m and config.site_footprint_depth_m:footprint=(config.site_footprint_origin_x_m,config.site_footprint_origin_y_m,config.site_footprint_width_m,config.site_footprint_depth_m)
    checks=placement_checks(bodies,clearances,footprint,polygons)
    hosts={z.get('host') for z in clearances if belongs(z)}
    checks=[r for r in checks if (member_ids|hosts).intersection(r.get('components',[]))]
    for r in checks:r['detail']=' / '.join(r.get('components',[]))+': '+r['detail']
    return {'valid':not checks,'config':candidate,'zone_id':zone_id,'checks':checks,
            'changes':{k:v for k,v in candidate.items() if v!=getattr(config,k)},
            'scope':'Equipment footprints and service access preflight. Apply design checks the full routed piping.'}
