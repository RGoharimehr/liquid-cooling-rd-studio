"""Stateful worker API: preview once, serialize only on request; no flow solver."""
import base64
import csv
from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path
import tempfile
import zipfile
from model import Config
from pipeline import build, emit

_session = None

def _json(value):
    return json.dumps(value, allow_nan=False, separators=(',', ':'))

def _applied(config_hash):
    if _session is None or _session[2] != config_hash:
        raise ValueError('This equipment search belongs to another design. Apply the current parameters.')
    return _session[0]

def zone_edit(config_hash, edit_json):
    graph = _applied(config_hash)
    from zone_editing import propose_zone_edit
    edit = json.loads(edit_json)
    if not isinstance(edit, dict) or set(edit)-{'zone_id','anchor_m','rotation_deg','flip_x','flip_y'}:
        raise ValueError('Unsupported zone edit. Choose a zone, then move, rotate or flip it.')
    zone_id = edit.pop('zone_id', None)
    return _json(propose_zone_edit(graph, Config.from_dict(graph['metadata']['config']), zone_id, **edit))

def optimize_routes(config_json):
    from design_actions import optimize_routes as optimize
    return _json(optimize(Config.from_dict(json.loads(config_json))))

def find_equipment(config_hash, catalogue_csv, catalogue_metadata_json):
    """Headless tool call after RD calculates duties and applies standard sizes."""
    graph = _applied(config_hash)
    from headless_selection import select_requirements
    report = select_requirements(graph['metadata']['equipment_requirements'], catalogue_csv,
                                 json.loads(catalogue_metadata_json))
    graph['metadata']['equipment_finder'] = report
    return _json(report)

def finder_unavailable(config_hash, message):
    graph = _applied(config_hash)
    report = {'schema_version':'1.0','applied_config_hash':config_hash,'status':'unavailable',
              'message':str(message),'items':[],
              'scope':'RD calculations and geometry are unchanged. No current catalogue search result is available.'}
    graph['metadata']['equipment_finder'] = report
    return _json(report)

def _finder_exports(graph, out):
    for name, value in [('equipment_requirements.json', graph['metadata'].get('equipment_requirements', {})),
                        ('equipment_candidates.json', graph['metadata'].get('equipment_finder',
                         {'status':'not_searched','applied_config_hash':graph['metadata'].get('config_hash')}))]:
        (out/name).write_text(_json(value), encoding='utf-8')

def preview(config_json):
    global _session
    data = json.loads(config_json)
    config = Config.from_dict(data) if hasattr(Config, 'from_dict') else Config(**data)
    graph, profile = build(config)
    from verify import run
    verification = run(graph, config, profile)
    graph['metadata']['verification'] = verification['summary']
    canonical = asdict(config)
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, allow_nan=False).encode()).hexdigest()
    graph['metadata']['config_hash'] = digest
    graph['metadata']['config'] = canonical
    blocked = verification['summary'].get('blocking_failures', 0)
    _session = (graph, profile, digest, blocked)
    services = sorted({c['service'] for c in graph['components'] if c.get('service') in ('FWS','TCS','CWS')})
    return _json({'graph': graph, 'config': canonical, 'config_hash': digest, 'exportable': not blocked,
                  'available_files': ['network.ifc', 'BOM.csv', 'graph.json', 'revit_handoff.json'] + ['network_'+s+'.pcf' for s in services]})

def export_file(name, config_hash):
    if _session is None:
        raise ValueError('Apply the design again to prepare an export.')
    graph, profile, digest, blocked = _session
    if digest != config_hash:
        raise ValueError('This download belongs to a different design. Apply the current parameters.')
    if blocked and name!='review':
        raise ValueError('Resolve the blocking geometry findings before exporting this design.')
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        if name == 'review':
            # Explicit diagnostic handoff stays available for infeasible concepts.
            # It contains no native/import geometry that could be confused with a checked design.
            for filename,value in [('config_used.json',graph['metadata']['config']),('graph-review-only.json',graph),('geometry_diagnostics.json',graph['metadata'].get('geometry_diagnostics',{})),('preliminary_sizing.json',graph['metadata'].get('preliminary_sizing',{})),('source_register.json',graph.get('provenance',{}).get('source_register',[])),('import_status.json',{'applied_config_hash':digest,'revit':'REVIEW_ONLY_NOT_CLEARED_FOR_IMPORT','flownex':'REVIEW_ONLY_NOT_CLEARED_FOR_IMPORT'})]:
                (out/filename).write_text(_json(value))
            from emitters import _emit_schedules, _edge_index
            _emit_schedules(graph,out,_edge_index(graph))
            with (out/'connection_schedule.csv').open('w',newline='') as stream:
                fields=['id','component_id','node_id','circuit_id','service','nominal_size_in','od_m','id_m','xyz_m','outward']
                writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader()
                writer.writerows({**port,'component_id':component['id']} for component in graph['components'] if not component.get('attachment') for port in component.get('port_details',[]))
            _finder_exports(graph,out)
            (out/'REVIEW_ONLY.txt').write_text('Diagnostic concept package. Not cleared for native MEP or hydraulic import. Correct listed findings and Apply design before normal exports.')
            stream=io.BytesIO()
            with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(out.iterdir()):archive.writestr(path.name,path.read_bytes())
            content=stream.getvalue();filename='rd-review-only.zip';mime='application/zip'
        elif name == 'zip':
            emit(graph, profile, out)
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
                for path in sorted(out.rglob('*')):
                    if path.is_file(): archive.writestr(str(path.relative_to(out)), path.read_bytes())
            content = stream.getvalue(); filename = 'reference-design.zip'; mime = 'application/zip'
        else:
            from emitters import _emit_schedules, _emit_geometry, _edge_index
            if name == 'network.ifc':
                from ifc4 import emit_ifc
                emit_ifc(graph, out, profile)
            elif name.startswith('network_') and name.endswith('.pcf'):
                _emit_geometry(graph, out, _edge_index(graph))
            elif name == 'BOM.csv': _emit_schedules(graph, out, _edge_index(graph))
            elif name == 'graph.json': (out/name).write_text(_json(graph))
            elif name == 'revit_handoff.json':
                from handoff import emit_handoff
                emit_handoff(graph, out)
            else: raise ValueError('Unsupported export format: '+name)
            path = out/name
            if not path.is_file(): raise ValueError('This design has no '+name+' output.')
            # Every format travels with its applied inputs and handoff diagnostics.
            from handoff import emit_handoff
            _emit_schedules(graph,out,_edge_index(graph));emit_handoff(graph,out)
            for filename,value in [('config_used.json',graph['metadata']['config']),('source_register.json',graph['provenance']['source_register']),('geometry_diagnostics.json',graph['metadata']['geometry_diagnostics']),('connectivity_scenarios.json',graph['metadata']['connectivity_scenarios']),('preliminary_sizing.json',graph['metadata'].get('preliminary_sizing',{'status':'Manual dimensions'}))]:
                (out/filename).write_text(_json(value))
            _finder_exports(graph, out)
            stream=io.BytesIO()
            with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED,compresslevel=3) as archive:
                for item in sorted(out.rglob('*')):
                    if item.is_file():archive.writestr(str(item.relative_to(out)),item.read_bytes())
            content=stream.getvalue();filename=name.replace('.','-')+'-bundle.zip';mime='application/zip'
        return _json({'name': filename, 'mime': mime, 'config_hash': digest, 'base64': base64.b64encode(content).decode()})

def generate(config_json):
    """Compatibility API for older scripts. New browser uses preview/export_file."""
    result = json.loads(preview(config_json))
    result['files'] = {}
    if result['exportable']:
        for name in result['available_files']:
            if name == 'revit_handoff.json' and not (Path(__file__).parent/'handoff.py').exists(): continue
            item = json.loads(export_file(name, result['config_hash']))
            with zipfile.ZipFile(io.BytesIO(base64.b64decode(item['base64']))) as bundle:
                result['files'][name] = bundle.read(name).decode()
        result['zip'] = json.loads(export_file('zip',result['config_hash']))['base64']
    return _json(result)
