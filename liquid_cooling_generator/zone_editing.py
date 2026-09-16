"""Move complete cooling pods, each with its own facility-water collector.

A pod carries its CDUs, its TCS distribution and its FWS collector, and meets the
facility at one connection point; only the pair of links from the facility trunk
to that point is rerouted when the pod is arranged somewhere else.

Call relocate_pods before plant generation and relocate_equipment after layout.equipment.
Routes are explicit concept routes and remain subject to ordinary collision checks.
"""
from math import cos, sin, radians, isfinite
from route_planning import emit as emit_links
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
    """Transform each moved pod with its own FWS collector, then relink it.

    A pod used to leave its facility-water collector behind: every CDU's branch
    was deleted and rebuilt as its own elevated lane from a pinned tee out to
    wherever that CDU had gone, and because all the lanes left from the same
    column they were stacked 0.8 m apart to miss each other. Eight CDUs put the
    last lane at 11.76 m on RD113, through a 6.5 m ceiling, so the pod could not
    be arranged at all.

    The collector is part of the pod now, so it travels with it and nothing has
    to be rebuilt. What is left is one pair of links per pod from the trunk,
    which share a single fly-over height because each pod leaves on its own
    column.
    """
    b = builder
    if b.g['metadata'].get('pod_relocation_applied'):
        return b.g['metadata']['pod_transforms']
    specs = _specs(b)
    bypod = {spec['pod']: spec for spec in specs}
    components = list(b.g['components'])

    def owner(comp):
        """The pod this component travels with, or None if it stays put."""
        if comp['kind'] == 'cdu' or comp.get('cdu'):
            # A CDU's own branch pieces go with it whichever service they carry.
            return b.cdus[comp['cdu']-1]
        if comp.get('zone_pod'):
            return comp['zone_pod']
        return comp['pod'] if comp.get('service') == 'TCS' else None

    node_pods = {}
    for comp in components:
        pod = owner(comp)
        if pod in bypod:
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

    links = b.g['metadata'].pop('fws_pod_links', [])
    radius = b.c.bend_radius_m
    lead = max(1.0, 3*radius+.05)
    outward = [float(v) for v in b.g['metadata'].get('fws_interface_dir', [0, 1, 0])]
    column = {pod: index for index, pod in enumerate(sorted({link['pod'] for link in links}))}
    for link in links:
        spec = bypod[link['pod']]
        b.current_pod = link['pod']
        group = (None, None, None)
        trunk, end = link['trunk'], link['pod_end']
        bx, by, bz = b.xyz(trunk)
        tx, ty, tz = b.xyz(end)
        # The collector's open end keeps facing the interface through the
        # transform, so approach it along that direction rather than assuming +Y.
        face = transform_zone_vector(outward, spec)
        approach = [[tx, ty, tz][k]+face[k]*lead for k in range(3)]
        # Rise and descend on the moved pod's own lane, which is clear at the
        # takeoff because the pod has left it. Everything the link crosses on the
        # way is facility water at the one header pair, whatever pod it serves,
        # so 0.7 m over the return clears all of it: arranging a pod adds one
        # height, not one height per CDU. A second pod arranged at the same time
        # takes the next. Only a pod arranged past the TCS spine has to clear the
        # pod headers as well, and that needs the ceiling to allow it.
        slot = column[link['pod']]
        top = b.c.header_elevation_m+b.c.return_elevation_offset_m+.7
        if max(bx, approach[0]) > -1.0:
            top = max(top, b.c.header_elevation_m+(b.c.pod_count-1)*b.c.pod_elevation_spacing_m
                           + b.c.return_elevation_offset_m+.7)
        top += (.35 if link['label'] == 'fr' else 0.)+slot*.7
        xx = approach[0]
        path = [[xx, by, bz], [xx, by, top]]
        if abs(approach[1]-by) < 2*radius+.02:
            # The pod came to rest level with its own takeoff. Step the corridor
            # clear of it so both turns have room for their bends.
            step = by-outward[1]*(2*radius+.6)
            path += [[xx, step, top], [approach[0], step, top]]
        path += [[approach[0], approach[1], top], approach]
        # An arranged pod's link crosses whatever the arrangement left in the way,
        # which is exactly what the lane router is for. The fly-over above stays
        # the lane it has to beat.
        # `face` already points out of the collector's open port, which is what
        # the router wants at that end, the same as the plant's tie-ins.
        key = f"FWS-pod-{link['pod']}-{link['label']}"
        try:
            if link['label'] == 'fs':
                emit_links(b, b.c, [(key, trunk, end, (1, 0, 0), tuple(face), path)], 'FWS', group=group)
            else:
                emit_links(b, b.c, [(key, end, trunk, tuple(face), (1, 0, 0), list(reversed(path)))], 'FWS', group=group)
        except ValueError as exc:
            raise ValueError(f"Cooling pod {link['pod']} cannot be arranged there: its {link['label']} "
                             f"connection has no explicit route back to the facility trunk ({exc})") from exc

    # Drop obsolete branch nodes, retaining Builder.n so new node numbers stay unique.
    used = {nid for comp in b.g['components'] for nid in comp.get('ports', [])}
    b.g['nodes'] = [node for node in b.g['nodes'] if node['id'] in used]
    b.g['metadata']['pod_transforms'] = specs
    b.g['metadata']['pod_relocation_applied'] = True
    b.g['metadata']['pod_relocation_scope'] = 'Moved each pod with its own TCS and FWS collectors and relinked it to the facility trunk. Reconnected routes require collision/ceiling review.'
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
    air = graph['metadata'].get('air_cooling', {})
    for kind, label, members, anchor, rotation in [
            ('network_zone', 'Network racks', [comp for comp in graph['components'] if comp['kind'] == 'network_rack'],
             graph['layout']['network_origin_m'], getattr(config,'network_rotation_deg',0)),
            ('air_cooling', 'Air units', [comp for comp in graph['components'] if comp['kind'] == 'air_unit'],
             air.get('origin_m') or [0., 0., 0.], 0),
            ('plant', 'Cooling plant', [comp for comp in graph['components'] if comp.get('zone') == 'plant' and comp.get('size_m')],
             [config.plant_origin_x_m, config.plant_origin_y_m, config.plant_elevation_m], config.plant_rotation_deg)]:
        if members:
            prefix = {'network_zone':'network','air_cooling':'air'}.get(kind,'plant')
            zone = {'id': kind, 'kind': kind, 'label': label, 'anchor_m': anchor,
                    'rotation_deg': rotation, 'bounds_m': _bounds(members),
                    'flip_x':getattr(config,prefix+'_flip_x',False), 'flip_y':getattr(config,prefix+'_flip_y',False),
                    'equipment_ids': [comp['id'] for comp in members], 'coordinate_frame': 'layout'}
            # The air strip is placed relative to whatever else the design
            # generated, so it moves and does not turn: there is no origin to
            # rotate a conceptual load bank about that would mean anything.
            if kind != 'air_cooling':
                zone.update({'rotation_parameter':prefix+'_rotation_deg', 'flip_x_parameter':prefix+'_flip_x',
                             'flip_y_parameter':prefix+'_flip_y'})
            zones.append(zone)
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
        prefix={'network_zone':'network','air_cooling':'air'}.get(zone['kind'],'plant')
        if prefix=='plant':candidate.update(plant_origin_x_m=new_anchor[0],plant_origin_y_m=new_anchor[1])
        else:
            candidate[prefix+'_offset_x_m']+=new_anchor[0]-old_anchor[0]
            candidate[prefix+'_offset_y_m']+=new_anchor[1]-old_anchor[1]
        # A zone that declares no rotation parameter does not turn; setting one
        # would invent a config key and reject the whole proposal.
        if zone.get('rotation_parameter'):
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
