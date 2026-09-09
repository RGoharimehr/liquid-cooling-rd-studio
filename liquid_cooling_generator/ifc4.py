"""Pure-stdlib IFC4 export with a Pyodide-compatible STEP writer.

emit_ifc(graph, outdir, profile=None) consumes the routed, SI graph. A component's
mesh={vertices:[[world x,y,z]], faces:[[zero-based indices]]} overrides fallback
concept geometry. Geometry, graph port ownership and service assignment are
independent: coincident coordinates do not make a fluid connection. This is an
exchange/coordination model, not a promise of native editable Revit MEP families.
"""
from __future__ import annotations
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import uuid

_ALPHABET = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$'
_NAMESPACE = uuid.UUID('8a9201a1-f6ef-534f-bb32-26a071f14fbf')
MAP = {
    'cdu': ('IfcHeatExchanger', 'IfcHeatExchangerType', 'PLATE'),
    'chiller': ('IfcChiller', 'IfcChillerType', 'NOTDEFINED'),
    'air_unit': ('IfcUnitaryEquipment', 'IfcUnitaryEquipmentType', 'AIRHANDLER'),
    'control_valve': ('IfcValve', 'IfcValveType', 'REGULATING'),
    'cooling_tower': ('IfcCoolingTower', 'IfcCoolingTowerType', 'NOTDEFINED'),
    'pipe': ('IfcPipeSegment', 'IfcPipeSegmentType', 'RIGIDSEGMENT'),
    'elbow': ('IfcPipeFitting', 'IfcPipeFittingType', 'BEND'),
    'tee': ('IfcPipeFitting', 'IfcPipeFittingType', 'JUNCTION'),
    'reducer': ('IfcPipeFitting', 'IfcPipeFittingType', 'TRANSITION'),
    'quick_disconnect': ('IfcPipeFitting', 'IfcPipeFittingType', 'CONNECTOR'),
    'rack_manifold': ('IfcPipeFitting', 'IfcPipeFittingType', 'JUNCTION'),
    'isolation_valve': ('IfcValve', 'IfcValveType', 'ISOLATING'),
    'balancing_valve': ('IfcValve', 'IfcValveType', 'DOUBLEREGULATING'),
    'check_valve': ('IfcValve', 'IfcValveType', 'CHECK'),
    'vent': ('IfcValve', 'IfcValveType', 'AIRRELEASE'),
    'drain': ('IfcValve', 'IfcValveType', 'DRAWOFFCOCK'),
    'pump': ('IfcPump', 'IfcPumpType', 'CIRCULATOR'),
    'cdu_primary': ('IfcHeatExchanger', 'IfcHeatExchangerType', 'PLATE'),
    'cdu_secondary': ('IfcHeatExchanger', 'IfcHeatExchangerType', 'PLATE'),
    'rack_load': ('IfcCoil', 'IfcCoilType', 'NOTDEFINED'),
    'strainer': ('IfcFilter', 'IfcFilterType', 'STRAINER'),
    'expansion_tank': ('IfcTank', 'IfcTankType', 'EXPANSION'),
    'air_separator': ('IfcInterceptor', 'IfcInterceptorType', 'NOTDEFINED'),
    'flex_connector': ('IfcPipeSegment', 'IfcPipeSegmentType', 'FLEXIBLESEGMENT'),
}
ACCESSORIES = {'pipe_support', 'seismic_brace_transverse', 'seismic_brace_longitudinal', 'drip_tray'}
ENCLOSURES = {'compute_rack', 'network_rack', 'cdu_enclosure', 'rack', 'cdu', 'clearance_zone'}


def stable_guid(key, project_id='liquid-cooling-reference'):
    """IFC compressed GUID: the 128 UUID bits encoded as 22 base-64 digits."""
    n = uuid.uuid5(_NAMESPACE, str(project_id) + '/' + str(key)).int
    chars = []
    for _ in range(22):
        chars.append(_ALPHABET[n & 63]); n >>= 6
    return ''.join(reversed(chars))


class _Raw(str):
    """Trusted generated STEP token; user strings must never use this class."""


def _enum(value):
    if not value.isidentifier() or not value.isupper():
        raise ValueError('Invalid generated IFC enumeration')
    return _Raw('.' + value + '.')


def _step(value):
    if value is None: return '$'
    if isinstance(value, _Raw): return str(value)
    if isinstance(value, bool): return '.T.' if value else '.F.'
    if isinstance(value, int): return str(value)
    if isinstance(value, float):
        if not math.isfinite(value): raise ValueError('IFC numbers must be finite')
        result = format(value, '.15g')
        return result if '.' in result or 'e' in result.lower() else result + '.'
    if isinstance(value, (list, tuple)): return '(' + ','.join(_step(x) for x in value) + ')'
    if not isinstance(value, str): raise TypeError(f'Unsupported STEP type: {type(value)}')
    # X2 uses UTF-16 code units, including surrogate pairs for supplementary chars.
    escaped = ''.join(ch.replace("'", "''").replace('\\', '\\\\') if 32 <= ord(ch) < 127
                      else ('\\X2\\' + f'{ord(ch):04X}' if ord(ch) <= 0xFFFF else '\\X4\\' + f'{ord(ch):08X}') + '\\X0\\' for ch in value)
    return "'" + escaped + "'"


class _Writer:
    def __init__(self, project_id):
        self.lines = []
        self.project_id = project_id
        self.owner = None

    def add(self, cls, *args):
        reference = _Raw('#' + str(len(self.lines) + 1))
        self.lines.append(str(reference) + '=' + cls.upper() + '(' + ','.join(_step(a) for a in args) + ');')
        return reference

    def root(self, cls, key, name=None, description=None, *args):
        return self.add(cls, stable_guid(key, self.project_id), self.owner, name, description, *args)

    def point(self, xyz):
        return self.add('IfcCartesianPoint', tuple(float(x) for x in xyz))

    def placement(self, xyz=(0., 0., 0.), parent=None, axis=None):
        z = self.add('IfcDirection', tuple(_unit(axis))) if axis else None
        x = self.add('IfcDirection', tuple(_perp(_unit(axis)))) if axis else None
        frame = self.add('IfcAxis2Placement3D', self.point(xyz), z, x)
        return self.add('IfcLocalPlacement', parent, frame)

    def pset(self, key, name, properties, owner=None):
        values = []
        for label, value in sorted(properties.items()):
            if value is None or value == '': continue
            if isinstance(value, bool): val = _Raw('IFCBOOLEAN(' + _step(value) + ')')
            elif isinstance(value, (int, float)): val = _Raw('IFCREAL(' + _step(float(value)) + ')')
            else:
                value = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')) if isinstance(value, (dict, list, tuple)) else str(value)
                val = _Raw('IFCTEXT(' + _step(value) + ')')
            values.append(self.add('IfcPropertySingleValue', label, None, val, None))
        if not values: return None
        ps = self.root('IfcPropertySet', 'pset/' + key, name, None, values)
        if owner is not None:
            self.root('IfcRelDefinesByProperties', 'properties/' + key, None, None, [owner], ps)
        return ps

    def text(self):
        return ("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('LCG reference layout; IFC4'),'2;1');\n"
                "FILE_NAME('network.ifc','2000-01-01T00:00:00',('LCG'),('LCG'),'LCG stdlib prototype','LCG','');\n"
                "FILE_SCHEMA(('IFC4'));\nENDSEC;\nDATA;\n" + '\n'.join(self.lines) + '\nENDSEC;\nEND-ISO-10303-21;\n')


def _sub(a, b): return [a[i] - b[i] for i in range(3)]
def _cross(a, b): return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
def _dot(a, b): return sum(x*y for x, y in zip(a, b))
def _unit(a):
    length = math.sqrt(_dot(a, a))
    if length < 1e-12: raise ValueError('Zero-length direction')
    return [x/length for x in a]
def _perp(a): return _unit(_cross(a, (0., 0., 1.) if abs(a[2]) < .9 else (1., 0., 0.)))


def _box(center, size):
    if len(center) != 3 or len(size) != 3 or any(float(x) <= 0 for x in size):
        raise ValueError('Envelope center_m and positive size_m must each contain three values')
    v = [[float(center[j]) + sign[j]*float(size[j])/2 for j in range(3)] for sign in
         [(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)]]
    return {'vertices': v, 'faces': [[0,3,2,1],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]]}


def _sweep(centers, tangents, radii, inner_radii=None, sides=16, normal=None):
    # Parallel planar frames; each fallback path is a straight line or planar bend.
    normal = _unit(normal) if normal else _perp(_unit(tangents[0]))
    verts, faces = [], []
    layers = [radii] + ([inner_radii] if inner_radii and all(x > 0 for x in inner_radii) else [])
    m = len(centers)
    for radii_layer in layers:
        for p, tangent, radius in zip(centers, tangents, radii_layer):
            u, w = normal, _cross(_unit(tangent), normal)
            for i in range(sides):
                angle = 2*math.pi*i/sides
                verts.append([p[j] + radius*(math.cos(angle)*u[j]+math.sin(angle)*w[j]) for j in range(3)])
    for layer in range(len(layers)):
        base = layer*m*sides
        for k in range(m-1):
            for i in range(sides):
                a=base+k*sides+i; b=base+k*sides+(i+1)%sides
                face=[a,b,b+sides,a+sides]
                faces.append(face if layer == 0 else face[::-1])
    if len(layers) == 2:
        inner = m*sides
        for k, reverse in [(0, True), (m-1, False)]:
            for i in range(sides):
                a=k*sides+i; b=k*sides+(i+1)%sides
                face=[a,b,inner+b,inner+a]
                faces.append(face[::-1] if reverse else face)
    else:
        faces.append(list(reversed(range(sides))))
        faces.append(list(range((m-1)*sides,m*sides)))
    return {'vertices': verts, 'faces': faces}


def _cylinder(a, b, od, inside=0., end_od=None, end_inside=None):
    axis = _unit(_sub(b, a))
    return _sweep([a,b], [axis,axis], [od/2,(end_od or od)/2],
                  [inside/2,(inside if end_inside is None else end_inside)/2])


def _join(meshes):
    result = {'vertices': [], 'faces': []}
    for mesh in meshes:
        n = len(result['vertices']); result['vertices'].extend(mesh['vertices'])
        result['faces'].extend([[i+n for i in face] for face in mesh['faces']])
    return result


def _triangulate(vertices, polygon):
    """Ear clipping for simple planar polygons; preserves supplied winding."""
    if len(polygon) == 3: return [polygon]
    normal = [0.,0.,0.]
    for i in range(len(polygon)):
        a,b=vertices[polygon[i]],vertices[polygon[(i+1)%len(polygon)]]
        n=_cross(a,b);normal=[normal[j]+n[j] for j in range(3)]
    drop=max(range(3),key=lambda i:abs(normal[i]));axes=[i for i in range(3) if i!=drop]
    pts={i:[vertices[i][j] for j in axes] for i in polygon}
    cross2=lambda a,b,c:(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    area=sum(pts[polygon[i]][0]*pts[polygon[(i+1)%len(polygon)]][1]-pts[polygon[(i+1)%len(polygon)]][0]*pts[polygon[i]][1] for i in range(len(polygon)))
    sign=1 if area>0 else -1;remaining=list(polygon);out=[]
    while len(remaining)>3:
        found=False
        for j,b in enumerate(remaining):
            a,c=remaining[j-1],remaining[(j+1)%len(remaining)]
            if sign*cross2(pts[a],pts[b],pts[c])<=1e-16:continue
            if any(all(sign*cross2(pts[x],pts[y],pts[p])>=-1e-16 for x,y in [(a,b),(b,c),(c,a)])
                   for p in remaining if p not in (a,b,c)):continue
            out.append([a,b,c]);remaining.pop(j);found=True;break
        if not found: raise ValueError('Cannot triangulate degenerate, nonplanar or self-intersecting polygon')
    return out+[remaining]


def _prepare_mesh(mesh):
    vertices=[[float(x) for x in p] for p in mesh['vertices']]
    if not vertices or any(len(p)!=3 or not all(math.isfinite(x) for x in p) for p in vertices):
        raise ValueError('Mesh vertices must be finite XYZ coordinates')
    triangles=[]
    for face in mesh['faces']:
        if len(face)<3 or len(set(face))!=len(face) or any(isinstance(i,bool) or not isinstance(i,int) or i<0 or i>=len(vertices) for i in face):
            raise ValueError('Mesh faces require unique valid zero-based integer indices')
        triangles.extend(_triangulate(vertices,list(face)))
    if not triangles: raise ValueError('Mesh must contain faces')
    directed=Counter()
    for a,b,c in triangles:
        n=_cross(_sub(vertices[b],vertices[a]),_sub(vertices[c],vertices[a]))
        if _dot(n,n)<1e-24: raise ValueError('Mesh contains zero-area triangle')
        for x,y in [(a,b),(b,c),(c,a)]:directed[x,y]+=1
    closed=all(directed[a,b]==1 and directed[b,a]==1 for a,b in directed)
    return vertices, [[i+1 for i in t] for t in triangles], closed


def _fallback_mesh(comp, pts, od, inside, port_od):
    kind=comp.get('kind');size=comp.get('size_m');center=comp.get('center_m')
    if size is not None and center is not None: return _box(center,size), 'declared_envelope'
    if kind in ENCLOSURES:
        raise ValueError(f"{comp['id']}: enclosure requires center_m and size_m or a mesh")
    if comp.get('attachment') or kind in ACCESSORIES or len(pts)<2:
        center=center or comp.get('xyz_m') or (pts[0] if pts else None)
        if center is None: raise ValueError(f"{comp['id']}: no geometry location")
        return _box(center, [.08,.08,.08]), 'concept_attachment_marker'
    a,b=pts[:2]
    if math.dist(a,b)<1e-8: return _box(a,[max(od,.05)]*3),'concept_coincident_port_marker'
    if kind=='tee' and len(pts)==3:
        if center is None: raise ValueError(f"{comp['id']}: tee fallback requires center_m")
        return _join([_cylinder(center,p,port_od[i],0.) for i,p in enumerate(pts)]),'concept_tee_overlapping_branch_solids'
    if kind=='elbow' and center is not None:
        r0=_sub(center,b);r1=_sub(center,a)
        if abs(_dot(_unit(r0),_unit(r1)))>1e-6:
            raise ValueError(f"{comp['id']}: fallback elbow requires orthogonal arms; supply a mesh")
        origin=[a[i]+b[i]-center[i] for i in range(3)];centers=[];tangents=[]
        for k in range(13):
            t=math.pi*k/24
            centers.append([origin[i]+math.cos(t)*r0[i]+math.sin(t)*r1[i] for i in range(3)])
            tangents.append([-math.sin(t)*r0[i]+math.cos(t)*r1[i] for i in range(3)])
        if min(math.dist(a,center),math.dist(b,center))<=od/2:
            return _join([_cylinder(a,center,od,inside),_cylinder(center,b,od,inside)]), 'rough_miter_fallback_bend_radius_below_OD_half'
        return _sweep(centers,tangents,[od/2]*13,[inside/2]*13,normal=_cross(r0,r1)), 'concept_curved_bend'
    if kind=='reducer':
        return _cylinder(a,b,port_od[0],0.,end_od=port_od[1]),'concept_reducer_envelope'
    if kind in ('pipe','flex_connector'): return _cylinder(a,b,od,inside),'concept_pipe_od_id'
    # Connectors plus a body envelope distinguish equipment from adjacent pipes.
    midpoint=[(a[i]+b[i])/2 for i in range(3)]
    body=_box(midpoint,[max(od*1.6,.12)]*3)
    return _join([_cylinder(a,b,od),body]),'concept_equipment_body_with_connectors'


def component_mesh(graph: dict, component: dict) -> dict:
    """Shared world-coordinate geometry for IFC, OBJ and a browser renderer.

    Returns vertices, zero-based polygon faces, geometry_basis and warnings.
    Does not modify the graph. Pass this dictionary as component['mesh'] to
    emit_ifc to preserve precisely the same surface and provenance in IFC.
    Supplied meshes are validated and returned unchanged except added metadata.
    """
    if component.get('mesh') is not None:
        result=dict(component['mesh'])
        _prepare_mesh(result)
        result.setdefault('geometry_basis','supplied_component_mesh')
        result.setdefault('warnings',[])
        return result
    nodes={n['id']:n for n in graph.get('nodes',[])}
    edges=defaultdict(list)
    connected=defaultdict(list)
    for e in graph.get('edges',[]):edges[e['component_id']].append(e)
    for c in graph.get('components',[]):
        if c.get('attachment') or c.get('hydraulic_element') is False or c['kind'] in ACCESSORIES or (c['kind'] in ENCLOSURES and not c.get('port_details')):continue
        for nid in c.get('ports',[]):connected[nid].append(c)
    def diameter(c,key='od_m'):
        return float(c.get(key) or next((e[key] for e in edges[c['id']] if e.get(key)),0.) or (0.05 if key=='od_m' else 0.))
    pts=[]
    for nid in component.get('ports',[]):
        n=nodes[nid];point=n.get('xyz_m') or n.get('route_hint_m')
        if point is None or len(point)!=3 or not all(math.isfinite(float(x)) for x in point):raise ValueError(f'{nid}: invalid coordinates')
        pts.append([float(x) for x in point])
    od=diameter(component);inside=diameter(component,'id_m')
    if od<=0 or inside<0 or inside>=od:raise ValueError(f"{component['id']}: require 0 <= ID < OD")
    port_od=[]
    for nid in component.get('ports',[]):
        explicit=(component.get('port_od_m') or {}).get(nid)
        others=[diameter(other) for other in connected[nid] if other['id']!=component['id']]
        port_od.append(float(explicit or (others[0] if others else od)))
    mesh,basis=_fallback_mesh(component,pts,od,inside,port_od)
    _prepare_mesh(mesh)
    mesh['geometry_basis']=basis
    mesh['warnings']=(['Bend takeout is below OD/2; rough overlapping miter segments replace the self-intersecting curved envelope. Increase routing takeout or supply fitting mesh.']
                      if basis.startswith('rough_miter_fallback') else [])
    return mesh


def emit_ifc(graph: dict, outdir: Path, profile=None) -> dict:
    """Emit network.ifc and ifc_manifest.json without importing native packages.

    Rejects malformed references, mixed-service shared nodes, duplicate IDs,
    zero/invalid mesh geometry, and more than two component ports at one graph
    node (insert an explicit tee). Mechanical attachments do not acquire fluid
    ports. Supports arbitrary supplied mesh geometry; fallbacks are conceptual.
    """
    metadata=graph.get('metadata',{});project_id=metadata.get('project_id',metadata.get('graph_id','liquid-cooling-reference'))
    w=_Writer(project_id)
    components=list(graph.get('components',[]));nodes={n['id']:n for n in graph.get('nodes',[])}
    if len(nodes)!=len(graph.get('nodes',[])):raise ValueError('Duplicate graph node ID')
    ids=[c['id'] for c in components]
    if len(set(ids))!=len(ids):raise ValueError('Duplicate graph component ID')
    edges=defaultdict(list);connected=defaultdict(list)
    for edge in graph.get('edges',[]):
        if edge['component_id'] not in ids or edge['from_node'] not in nodes or edge['to_node'] not in nodes:
            raise ValueError('Edge references unknown component/node')
        edges[edge['component_id']].append(edge)
    for comp in components:
        ports=comp.get('ports',[])
        if len(set(ports))!=len(ports) or any(p not in nodes for p in ports):raise ValueError(f"{comp['id']}: invalid component ports")
        if comp.get('attachment') or comp.get('hydraulic_element') is False or comp['kind'] in ACCESSORIES or (comp['kind'] in ENCLOSURES and not comp.get('port_details')):continue
        for p in ports:connected[p].append(comp)
    for nid, cs in connected.items():
        if len(cs)>2:raise ValueError(f'{nid}: more than two component ports; insert an explicit junction fitting')
        if len({next((p['service'] for p in c.get('port_details',[]) if p['node_id']==nid),c.get('service','')) for c in cs})>1:raise ValueError(f'{nid}: fluid services share a graph node')

    person=w.add('IfcPerson',None,'Generator',None,None,None,None,None,None)
    org=w.add('IfcOrganization',None,'Liquid cooling generator',None,None,None)
    user=w.add('IfcPersonAndOrganization',person,org,None)
    app=w.add('IfcApplication',org,'1.0','LCG stdlib IFC4 exporter','LCG')
    w.owner=w.add('IfcOwnerHistory',user,app,None,_enum('NOCHANGE'),None,None,None,0)
    origin=w.point([0.,0.,0.]);world=w.add('IfcAxis2Placement3D',origin,None,None)
    context=w.add('IfcGeometricRepresentationContext',None,'Model',3,1e-6,world,None)
    body=w.add('IfcGeometricRepresentationSubContext','Body','Model',_Raw('*'),_Raw('*'),_Raw('*'),_Raw('*'),context,None,_enum('MODEL_VIEW'),None)
    units=w.add('IfcUnitAssignment',[w.add('IfcSIUnit',_Raw('*'),_enum(t),None,_enum(n)) for t,n in [('LENGTHUNIT','METRE'),('AREAUNIT','SQUARE_METRE'),('VOLUMEUNIT','CUBIC_METRE')]])
    project=w.root('IfcProject','project',metadata.get('name','Liquid cooling reference design'),None,None,None,None,[context],units)
    site_place=w.placement();building_place=w.placement(parent=site_place);storey_place=w.placement(parent=building_place)
    site=w.root('IfcSite','site','Site',None,None,site_place,None,None,_enum('ELEMENT'),None,None,None,None,None)
    building=w.root('IfcBuilding','building','Data hall',None,None,building_place,None,None,_enum('ELEMENT'),None,None,None)
    storey=w.root('IfcBuildingStorey','storey','Data hall level',None,None,storey_place,None,None,_enum('ELEMENT'),0.)
    for label,a,b in [('site',project,site),('building',site,building),('storey',building,storey)]:
        w.root('IfcRelAggregates','aggregate/'+label,None,None,a,[b])
    profile_data=profile.manifest() if profile is not None and callable(getattr(profile,'manifest',None)) else profile
    w.pset('project','LCG_ReferenceDesign',{'ProjectId':project_id,'Purpose':'Configurable reference layout; downstream refinement',
           'Status':metadata.get('status','Engineering concept'), 'ConfigJSON':metadata.get('config'),
           'ProvenanceJSON':graph.get('provenance'), 'StandardsProfileJSON':profile_data},project)
    styles={}
    for name,rgb,transparency in [('TCS',(.05,.48,.78),0.),('FWS',(.75,.45,.12),0.),('equipment',(.22,.28,.34),.15),('clearance',(.3,.85,.65),.8),('other',(.5,.5,.55),0.)]:
        colour=w.add('IfcColourRgb',None,*rgb)
        shading=w.add('IfcSurfaceStyleRendering',colour,transparency,None,None,None,None,None,None,_enum('NOTDEFINED'))
        styles[name]=w.add('IfcSurfaceStyle',name,_enum('BOTH'),[shading])

    elements={};type_groups={};materials=defaultdict(list);services=defaultdict(list);ports_by_node=defaultdict(list);manifest_components=[]
    def xyz(nid):
        n=nodes[nid];p=n.get('xyz_m') or n.get('route_hint_m')
        if p is None or len(p)!=3 or not all(math.isfinite(float(x)) for x in p):raise ValueError(f'{nid}: invalid coordinates')
        return [float(x) for x in p]
    def diameter(c,key='od_m'):
        return float(c.get(key) or next((e[key] for e in edges[c['id']] if e.get(key)),0.) or (0.05 if key=='od_m' else 0.))

    for c in components:
        cid=c['id'];kind=c['kind'];tag=c.get('tag',cid);service=c.get('service','')
        nonhydraulic=bool(c.get('attachment') or c.get('hydraulic_element') is False or kind in ACCESSORIES or (kind in ENCLOSURES and not c.get('port_details')))
        cls,type_cls,predefined=MAP.get(kind,('IfcDiscreteAccessory','IfcDiscreteAccessoryType','NOTDEFINED') if kind in ACCESSORIES else ('IfcBuildingElementProxy','IfcBuildingElementProxyType','USERDEFINED'))
        pts=[xyz(nid) for nid in c.get('ports',[])];od=diameter(c);inside=diameter(c,'id_m')
        if od<=0 or inside<0 or inside>=od:raise ValueError(f'{cid}: require 0 <= ID < OD')
        port_od=[]
        for nid in c.get('ports',[]):
            explicit=(c.get('port_od_m') or {}).get(nid)
            others=[diameter(other) for other in connected[nid] if other['id']!=cid]
            port_od.append(float(explicit or (others[0] if others else od)))
        if c.get('mesh') is not None:mesh=c['mesh'];basis=mesh.get('geometry_basis','supplied_component_mesh')
        else:mesh=component_mesh(graph,c);basis=mesh['geometry_basis']
        verts,triangles,closed=_prepare_mesh(mesh)
        points=w.add('IfcCartesianPointList3D',verts)
        tess=w.add('IfcTriangulatedFaceSet',points,None,closed,triangles,None)
        colour='clearance' if kind=='clearance_zone' else 'equipment' if kind in ENCLOSURES else service if service in styles else 'other'
        w.add('IfcStyledItem',tess,[styles[colour]],None)
        shape=w.add('IfcShapeRepresentation',body,'Body','Tessellation',[tess])
        representation=w.add('IfcProductDefinitionShape',None,None,[shape])
        placement=w.placement(parent=storey_place)
        element=w.root(cls,'component/'+cid,tag,kind.replace('_',' '),kind,placement,representation,tag,_enum(predefined))
        elements[cid]=element
        es=edges[cid];edge0=es[0] if es else {};material=c.get('material') or edge0.get('material') or 'unspecified'
        sizes=c.get('port_sizes_in') or c.get('port_nominal_size_in') or {}
        props={'ComponentId':cid,'Kind':kind,'Service':service,'Level':c.get('level'),'Row':c.get('row'),'Rack':c.get('rack'),'CDU':c.get('cdu'),
               'NodeIds':c.get('ports',[]),'NominalSizeInch':c.get('nominal_size_in') or edge0.get('nominal_size_in'),
               'PortNominalSizesInch':sizes,'OutsideDiameter_m':od,'InsideDiameter_m':inside,'PortOutsideDiameters_m':dict(zip(c.get('ports',[]),port_od)),
               'Material':material,'Status':c.get('status','conceptual'),'HydraulicElement':not nonhydraulic,
               'HostComponent':c.get('host_component'),'GeometryBasis':basis,'MeshClosed':closed,'SourceProvenance':c.get('provenance'),
               'EdgeProvenance':{e['id']:e.get('provenance',{}) for e in es},'Assumptions':c.get('assumptions'),'GeometryWarnings':mesh.get('warnings'),
               'EnvelopeCenter_m':c.get('center_m') if c.get('size_m') else None,'EnvelopeSize_m':c.get('size_m')}
        w.pset('component/'+cid,'LCG_Component',props,element)
        type_props={k:props[k] for k in ['Kind','NominalSizeInch','OutsideDiameter_m','InsideDiameter_m','Material']}
        type_props['PortSizePatternInch']=sorted(sizes.values())
        type_key=json.dumps([type_cls,predefined,type_props],sort_keys=True,separators=(',',':'))
        if type_key not in type_groups:
            tp=w.pset('type/'+type_key,'LCG_TypeDefinition',type_props)
            type_ent=w.root(type_cls,'type/'+type_key,kind+' / '+str(type_props['NominalSizeInch'])+' in / '+material,None,None,[tp] if tp else None,None,None,kind,_enum(predefined))
            type_groups[type_key]=[type_ent,[]]
        type_groups[type_key][1].append(element)
        if material!='unspecified':materials[material].append(element)
        if service and not nonhydraulic:
            for circuit in {p.get('circuit_id',p.get('service',service)) for p in c.get('port_details',[])} or {service}:services[circuit].append(element)
        port_records=[];port_entities=[]
        if not nonhydraulic:
            for i,nid in enumerate(c.get('ports',[])):
                roles=sum((1 if e['to_node']==nid else 0)-(1 if e['from_node']==nid else 0) for e in es)
                flow='SOURCEANDSINK' if metadata.get('schema_version')=='2.0' else 'SOURCE' if roles>0 else 'SINK' if roles<0 else 'SOURCEANDSINK'
                center=c.get('center_m') if kind in ('tee','elbow') else None
                outward=_sub(pts[i],center) if center else _sub(pts[i],pts[1-i]) if len(pts)==2 else None
                if outward and math.sqrt(_dot(outward,outward))<1e-10:outward=None
                detail=next((p for p in c.get('port_details',[]) if p['node_id']==nid),{})
                outward=detail.get('outward',outward);portkey=detail.get('id',cid+'/'+nid)
                port=w.root('IfcDistributionPort','port/'+portkey,tag+':'+nid,None,None,w.placement(pts[i],placement,outward),None,_enum(flow),_enum('PIPE'),_enum('CHILLEDWATER'))
                port_entities.append(port);ports_by_node[nid].append((cid,port,flow,service))
                w.pset('port/'+cid+'/'+nid,'LCG_Port',{'ComponentId':cid,'GraphNodeId':nid,'Service':detail.get('service',service),'Circuit':detail.get('circuit_id',service),'NominalSizeInch':sizes.get(nid),'OutsideDiameter_m':port_od[i]},port)
                port_records.append({'node_id':nid,'guid':stable_guid('port/'+portkey,project_id),'direction':flow})
            if port_entities:w.root('IfcRelNests','ports/'+cid,None,None,element,port_entities)
        manifest_components.append({'component_id':cid,'ifc_class':cls,'guid':stable_guid('component/'+cid,project_id),'ports':port_records,'geometry_basis':basis,'geometry_warnings':mesh.get('warnings',[]),'mesh_closed':closed,'triangles':len(triangles)})
    if elements:w.root('IfcRelContainedInSpatialStructure','containment',None,None,list(elements.values()),storey)
    for key,(type_ent,items) in type_groups.items():w.root('IfcRelDefinesByType','typed/'+key,None,None,items,type_ent)
    for name,items in sorted(materials.items()):
        material=w.add('IfcMaterial',name,None,None)
        w.root('IfcRelAssociatesMaterial','material/'+name,None,None,items,material)
    connections=0
    for nid,entries in sorted(ports_by_node.items()):
        if len(entries)<2:continue
        a,b=entries
        if a[2]=='SINK' and b[2]=='SOURCE':a,b=b,a
        if a[2]==b[2] and a[2]!='SOURCEANDSINK':raise ValueError(f'{nid}: graph connects two {a[2]} ports')
        w.root('IfcRelConnectsPorts','connection/'+nid,None,'Shared graph node '+nid,a[1],b[1],None)
        connections+=1
    for service,items in sorted(services.items()):
        system=w.root('IfcDistributionSystem','system/'+service,service,None,None,service,_enum('CHILLEDWATER'))
        w.root('IfcRelAssignsToGroup','system-members/'+service,None,None,items,None,system)
        w.root('IfcRelServicesBuildings','system-building/'+service,None,None,system,[building])
    couplings=0
    for coupling in graph.get('couplings',[]):
        members=[elements[coupling[k]] for k in ['primary_component','secondary_component'] if coupling.get(k) in elements]
        if len(members)!=2:raise ValueError('Thermal coupling must reference two exported components')
        members=list(dict.fromkeys(members))
        key=coupling['id'];group=w.root('IfcGroup','coupling/'+key,key,'Heat transfer association only; no fluid connection','THERMAL_COUPLING_ONLY')
        w.root('IfcRelAssignsToGroup','coupling-members/'+key,None,None,members,None,group)
        w.pset('coupling/'+key,'LCG_ThermalCoupling',coupling,group);couplings+=1
    outdir=Path(outdir);outdir.mkdir(parents=True,exist_ok=True)
    (outdir/'network.ifc').write_text(w.text(),encoding='ascii')
    manifest={'ifc_file':'network.ifc','ifc_schema':'IFC4','ifc_element_count':len(elements),'ifc_port_count':sum(len(x['ports']) for x in manifest_components),
              'ifc_port_connections':connections,'ifc_systems':len(services),'ifc_type_objects':len(type_groups),'ifc_untyped_elements':0,'ifc_skipped_count':0,
              'ifc_thermal_coupling_groups':couplings,'ifc_components':manifest_components,
              'ifc_status':'IFC4 coordination geometry and explicit graph connectivity; no native Revit family or importer validation implied.'}
    (outdir/'ifc_manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return manifest
