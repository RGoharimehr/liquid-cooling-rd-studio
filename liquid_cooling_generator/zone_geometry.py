"""Rigid plan transforms and equipment/service-envelope placement checks.

Local zone rotation is orthogonal so fittings retain their physical takeoffs.
Mirrors act in the unrotated zone axes, then rotation is applied.
"""
from math import cos, sin, radians, isfinite


def transform_spec(anchor_m, rotation_deg=0, flip_x=False, flip_y=False, original_anchor_m=None):
    if type(rotation_deg) not in (int, float) or not isfinite(rotation_deg) or rotation_deg % 90:
        raise ValueError('Zone rotation must be a finite multiple of 90 degrees')
    if type(flip_x) is not bool or type(flip_y) is not bool:
        raise ValueError('Zone flips must be true or false')
    if len(anchor_m) not in (2, 3) or any(type(v) not in (int, float) or not isfinite(v) for v in anchor_m):
        raise ValueError('Zone anchor requires finite x and y coordinates')
    anchor = list(anchor_m) if len(anchor_m) == 3 else [*anchor_m, 0.]
    return {'anchor_m': anchor, 'original_anchor_m': list(original_anchor_m or anchor),
            'rotation_deg': int(rotation_deg % 360), 'flip_x': flip_x, 'flip_y': flip_y}


def transform_zone_vector(point, spec, inverse=False):
    co, si = round(cos(radians(spec['rotation_deg']))), round(sin(radians(spec['rotation_deg'])))
    sx, sy = (-1 if spec.get('flip_x') else 1), (-1 if spec.get('flip_y') else 1)
    x, y, z = point
    if inverse:
        return [sx*(co*x+si*y), sy*(-si*x+co*y), z]
    x, y = sx*x, sy*y
    return [co*x-si*y, si*x+co*y, z]


def transform_zone_point(point, spec):
    relative = [point[k]-spec['original_anchor_m'][k] for k in range(3)]
    moved = transform_zone_vector(relative, spec)
    return [moved[k]+spec['anchor_m'][k] for k in range(3)]


def move_component(comp, spec):
    for key in ('center_m', 'xyz_m'):
        if comp.get(key) is not None:
            comp[key] = transform_zone_point(comp[key], spec)
    if comp.get('size_m') and spec['rotation_deg'] % 180:
        comp['size_m'] = [comp['size_m'][1], comp['size_m'][0], comp['size_m'][2]]
    if comp.get('port_directions'):
        comp['port_directions'] = {key: transform_zone_vector(value, spec)
                                   for key, value in comp['port_directions'].items()}
    comp.update(zone_rotation_deg=spec['rotation_deg'], zone_flip_x=spec.get('flip_x', False),
                zone_flip_y=spec.get('flip_y', False))


def transform_zone_geometry(nodes, components, anchor_m, rotation_deg=0, flip_x=False, flip_y=False):
    spec = transform_spec(anchor_m, rotation_deg, flip_x, flip_y)
    for node in nodes:
        for key in ('route_hint_m', 'xyz_m'):
            if node.get(key) is not None:
                node[key] = transform_zone_point(node[key], spec)
    for comp in components:
        move_component(comp, spec)
    return spec


def equipment_corners(item):
    """Footprint corners after an optional final world rotation.

    Orthogonal local zone transforms swap size_m before mesh generation. The
    separate rotation_deg is only the final whole-layout rotation.
    """
    center, size = item.get('center_m'), item.get('size_m')
    if center is None or size is None:
        return []
    angle = radians(item.get('rotation_deg', 0))
    co, si = cos(angle), sin(angle)
    return [[center[0]+co*x-si*y, center[1]+si*x+co*y]
            for x,y in [(-size[0]/2,-size[1]/2), (size[0]/2,-size[1]/2),
                        (size[0]/2,size[1]/2), (-size[0]/2,size[1]/2)]]


def polygons_overlap(a, b, tolerance=1e-7):
    """Separating axes; touching boundaries are allowed, penetration is not."""
    if not a or not b:
        return False
    for poly in (a, b):
        for p, q in zip(poly, poly[1:]+poly[:1]):
            nx, ny = -(q[1]-p[1]), q[0]-p[0]
            length = (nx*nx+ny*ny)**.5
            if length < 1e-12:
                continue
            nx, ny = nx/length, ny/length
            aa = [v[0]*nx+v[1]*ny for v in a]
            bb = [v[0]*nx+v[1]*ny for v in b]
            if min(max(aa), max(bb))-max(min(aa), min(bb)) <= tolerance:
                return False
    return True


def placement_checks(equipment, clearances=(), footprint=None, polygons=None):
    """Check actual bodies, reserved service space, and optional site boundary."""
    bodies = [item for item in equipment if item.get('center_m') is not None
              and item.get('size_m') is not None and not item.get('attachment')]
    polygons = polygons or {}
    corners = {item['id']: polygons.get(item['id'], equipment_corners(item)) for item in [*bodies, *clearances]}
    checks = []
    for index, a in enumerate(bodies):
        for b in bodies[index+1:]:
            az, bz = a['center_m'][2], b['center_m'][2]
            if abs(az-bz) >= (a['size_m'][2]+b['size_m'][2])/2-1e-7:
                continue
            if polygons_overlap(corners[a['id']], corners[b['id']]):
                checks.append({'check':'Equipment envelopes do not overlap', 'status':'FAIL',
                               'components':[a['id'], b['id']],
                               'detail':'Move or rotate one zone, or increase equipment pitch. Physical bodies overlap.'})
    for zone in clearances:
        host = zone.get('host', '')
        for box in bodies:
            if box['id'] == host or (host.startswith('IT-R') and box['id'].startswith(host+'-')):
                continue
            # The reservation is a plan access area at the host floor elevation.
            floor = zone.get('floor_elevation_m', 0.)
            if box['center_m'][2]-box['size_m'][2]/2 > floor+2.5:
                continue
            if polygons_overlap(corners[zone['id']], corners[box['id']]):
                checks.append({'check':'Equipment preserves service access', 'status':'FAIL',
                               'components':[host, box['id']], 'clearance_zone':zone['id'],
                               'detail':'Move the obstructing zone or increase spacing to preserve the larger of the project allowance and declared vendor minimum.'})
    if footprint:
        x, y, width, depth = footprint
        for item in [*bodies, *clearances]:
            poly = corners[item['id']]
            if any(p[0] < x-1e-7 or p[1] < y-1e-7 or p[0] > x+width+1e-7 or p[1] > y+depth+1e-7 for p in poly):
                checks.append({'check':'Equipment and access fit site footprint', 'status':'FAIL',
                               'components':[item.get('host', item['id'])],
                               'detail':'Move the zone inside the declared footprint, or change the footprint dimensions or world origin.'})
    return checks
