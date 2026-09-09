"""Native Revit import contract and explicit Flownex mapping handoff."""
import json,csv,shutil
from pathlib import Path

REVIT_TARGET = '2027'
COMPATIBILITY = {
    'requested_revit': REVIT_TARGET,
    'revit_addin_framework': '.NET 10',
    'flownex_documented_release': 'SE 2025 Release 3 (9.0.4)',
    'flownex_documented_revit': '2026',
    'flownex_revit_2027_status': 'NOT_CONFIRMED_BY_VENDOR_SOURCE',
    'checked_on': '2026-09-09',
    'revit_source': 'https://help.autodesk.com/cloudhelp/2027/ENU/Revit-WhatsNew/files/GUID-8D7A4715-EAF8-4BD1-BE78-061F900D0BCE.htm',
    'flownex_source': 'https://flownex.com/news/flownex-se-2025-release-3/',
    'next_step': 'Confirm that the installed Flownex Network Builder explicitly supports Revit 2027 before attempting native transfer. The Revit import and Flownex transfer are separate validation gates.',
}

def emit_handoff(graph,outdir):
    out=Path(outdir);out.mkdir(parents=True,exist_ok=True)
    physical=[c for c in graph['components'] if not c.get('attachment')]
    ports=[{**p,'component_id':c['id']} for c in physical for p in c.get('port_details',[])]
    nodes={p['node_id']:[] for p in ports}
    for p in ports:nodes[p['node_id']].append(p['id'])
    package={'schema_version':'2.0','target':{'revit':REVIT_TARGET,'dotnet':'10.0','flownex':'Official Revit Network Builder; Revit 2027 compatibility unverified'},'units':'m; nominal inches',
      'compatibility':COMPATIBILITY,
      'config_hash':graph['metadata']['config_hash'],'config':graph['metadata']['config'],
      'components':[{k:v for k,v in c.items() if k!='mesh'} for c in physical], 'connections':[{'node_id':n,'ports':p} for n,p in nodes.items()],
      'fluid_paths':graph['edges'],'thermal_couplings':graph['couplings'],'guidance':graph['metadata'].get('guidance'),
      'import_status':{'revit':'NOT_TESTED_IN_TARGET_APPLICATION','flownex':'NOT_TESTED_IN_TARGET_APPLICATION'},
      'unsupported_installation_items':[{'component_id':x['id'],'kind':x['kind'],'status':'COORDINATION_ONLY','reason':'Installation marker or attachment; retained in IFC/BOM/graph, requires native vendor mapping.'} for x in graph['components'] if x.get('attachment')],
      'preflight':{'geometry_blocking_findings':graph['metadata'].get('geometry_diagnostics',{}).get('blocking_failures',0),
      'required':'Revit 2027, .NET 10 SDK to build the add-in, native PipeType with catalogue ID/OD matching revit_pipe_catalogue.csv and an unhosted Mechanical Equipment family template. Follow revit/README.md. Revit 2027 compatibility of the installed Flownex Network Builder must be confirmed separately.'}}
    (out/'revit_handoff.json').write_text(json.dumps(package,indent=2,allow_nan=False))
    mappings=[]
    for c in physical:
        kind=c['kind'];target='pipe' if kind in ('pipe','flex_connector') else 'two-fluid heat exchanger + TCS pump' if kind=='cdu' else 'aggregate heat load' if kind in ('compute_rack','air_unit') else 'evaporator / condenser' if kind=='chiller' else 'heat rejection boundary' if kind=='cooling_tower' else kind
        mappings.append({'component_id':c['id'],'kind':kind,'target_function':target,'native_library_id':None,'status':'TARGET_LIBRARY_MAPPING_REQUIRED' if kind!='pipe' else 'GEOMETRY_TRANSFER_REQUIRES_TARGET_VERIFICATION'})
    (out/'flownex_mapping.json').write_text(json.dumps({'target':'Official Revit Network Builder; select a release supporting Revit 2027','compatibility':COMPATIBILITY,'mappings':mappings,'solver_run':False,'native_project_created':False,'notes':'Preserve each separate FWS, CWS and TCS pod circuit. This is a human-readable mapping checklist, not an executable Network Builder configuration. Map physical equipment functions in Flownex; manufacturer performance data are intentionally unassigned.'},indent=2))
    with (out/'connection_schedule.csv').open('w',newline='') as f:
        fields=['id','component_id','node_id','circuit_id','service','nominal_size_in','od_m','id_m','xyz_m','outward'];w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(ports)
    (out/'import_status.json').write_text(json.dumps(package['import_status'],indent=2))
    catalogue={}
    for component in physical:
        if component['kind']!='pipe':continue
        for port in component.get('port_details',[]):
            key=(component.get('material','unspecified'),port.get('nominal_size_in'),port.get('id_m'),port.get('od_m'))
            catalogue.setdefault(key,set()).add(component['id'])
    with (out/'revit_pipe_catalogue.csv').open('w',newline='') as f:
        writer=csv.writer(f)
        writer.writerow(['material','nominal_size_in','inside_diameter_mm','outside_diameter_mm','required_pipe_type','component_ids'])
        for (material,nominal,inside,outside),ids in sorted(catalogue.items(),key=lambda item:str(item[0])):
            writer.writerow([material,nominal,None if inside is None else inside*1000,None if outside is None else outside*1000,'Set the matching native PipeType name in revit/import-settings.json','; '.join(sorted(ids))])
    src=Path(__file__).parent/'revit'
    if src.exists():
        for p in src.rglob('*'):
            if p.is_file() and not any(x in p.parts for x in ('bin','obj')):
                dest=out/'revit'/p.relative_to(src);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
    return {'revit_handoff':'revit_handoff.json','flownex_mapping':'flownex_mapping.json','connection_schedule':'connection_schedule.csv','revit_pipe_catalogue':'revit_pipe_catalogue.csv','revit_guide':'revit/README.md','revit_target':REVIT_TARGET,'flownex_revit_2027_status':COMPATIBILITY['flownex_revit_2027_status'],'native_import_tested':False}
