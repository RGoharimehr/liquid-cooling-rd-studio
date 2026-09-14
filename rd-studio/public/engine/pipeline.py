"""Shared CLI/browser pipeline. All outputs are generated from one connected graph."""
from dataclasses import asdict,replace
import hashlib
import html
import json
from pathlib import Path
import shutil
import tempfile
from model import Config,build_profile
from topology import route_graph
from network_v2 import generate
from sizing import apply_sizes
from layout import equipment
from placement import place_installation,check_layout
from emitters import emit_all
from ifc4 import component_mesh


def dump(path,value):
    Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def plan_svg(g):
    boxes=g['layout']['equipment_envelopes'];points=[n['xyz_m'] for n in g['nodes']]
    points += [p for b in boxes for p in b.get('mesh',{}).get('vertices',[])]
    xmin=min(p[0] for p in points)-1;ymin=min(p[1] for p in points)-1
    w=max(p[0] for p in points)-xmin+1;h=max(p[1] for p in points)-ymin+1
    svg=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{xmin} {ymin} {w} {h}"><rect x="{xmin}" y="{ymin}" width="{w}" height="{h}" fill="#f5f8f5"/>']
    for b in boxes:
        x,y,_=b['center_m'];dx,dy,_=b['size_m'];color={'compute_rack':'#293f4e','network_rack':'#8b71aa','cdu':'#74a4ae','chiller':'#737f99','cooling_tower':'#879fa8'}.get(b['kind'],'#74a4ae')
        svg.append(f'<rect transform="rotate({b.get("rotation_deg",0)} {x} {y})" x="{x-dx/2}" y="{y-dy/2}" width="{dx}" height="{dy}" fill="{color}"><title>{html.escape(b["id"])}</title></rect>')
    nodes={n['id']:n['xyz_m'] for n in g['nodes']}
    for c in g['components']:
        if c.get('attachment') or c.get('size_m') or len(c.get('ports',[]))<2:continue
        pts=[nodes[p] for p in c['ports']];color={'TCS':'#108f8a','FWS':'#d39340','CWS':'#557eb6'}.get(c['service'],'#667777')
        svg.append(f'<polyline points="'+ ' '.join(f'{p[0]},{p[1]}' for p in pts)+f'" fill="none" stroke="{color}" stroke-width=".035"><title>{html.escape(c["id"])}</title></polyline>')
    return ''.join(svg)+'</svg>'


def build(config):
    config.validate();profile=build_profile(config)
    g=generate(config,profile);route_graph(g)
    sizing_config=replace(config,sizing_mode='manual') if config.sizing_mode=='preliminary' else config
    apply_sizes(g,sizing_config)
    if config.sizing_mode=='preliminary':
        from preliminary_sizing import evaluate as estimate
        recommendations=estimate(g,config)
        missing=[f for f in recommendations['size_families'] if not f.get('selection')]
        # Keep the rough graph reviewable when one family exceeds the verified catalogue.
        sizing_config=replace(sizing_config,**recommendations['suggested_config'])
        apply_sizes(g,sizing_config)
    equipment(g,config)
    from zone_editing import relocate_equipment,footprint_check
    relocate_equipment(g,config)
    from contract import finalize_equipment, attach_contract, transform_layout
    finalize_equipment(g,config)
    attach_contract(g,config)
    if config.sizing_mode in ('preliminary','manual'):
        from preliminary_sizing import evaluate as estimate
        manual=config.sizing_mode=='manual'
        estimates=estimate(g,config,use_applied_sizes=manual)
        estimates['geometry_modified']=not manual and all(f.get('selection') for f in estimates['size_families'])
        estimates['scope']=('Manual commercial pipe sizes retained; flow, pressure loss, pump head and valve duties evaluated at those bores. ' if manual else 'Catalogue sizes applied to uniform pipe families; routed geometry is checked separately. ')+'Prescribed-flow estimates, not a balanced network solution.'
        g['metadata']['preliminary_sizing']=estimates
        byedge={e['edge_id']:e for e in estimates['edge_estimates']}
        for edge in g['edges']:
            item=byedge.get(edge['id'],{})
            edge['flow_m3_s']=item.get('flow_m3_s') or 0
            edge['design_flow_m3_s']=item.get('design_flow_m3_s') or 0
            edge['preliminary_dp_Pa']=item.get('total_dp_Pa')
            edge['velocity_m_s']=item.get('velocity_m_s')
            edge['velocity_cap_pass']=item.get('velocity_cap_pass')
            # apply_sizes zeroes these before the coefficients are chosen. Put
            # the applied values back, or every consumer of the graph - the BOM,
            # the cost model, the Flownex mapping - reads a loss of zero.
            edge['K']=item.get('loss_K',0.) or 0.
            edge['K_reference_id_m']=item.get('K_reference_id_m')
            edge['flow_regime']=item.get('flow_regime')
            edge['friction_factor']=item.get('friction_factor')
            edge['hydraulic_result_basis']='Prescribed flow and preliminary Darcy-Weisbach estimate; network not balanced'
            edge['provenance']['flow']=edge['hydraulic_result_basis']
        g['hydraulics'].update(mode=config.sizing_mode,flow_assignment='prescribed; see preliminary_sizing',network_pressure_solve_performed=False,
            dimension_basis=estimates['dimension_basis'])
    from connectivity import evaluate
    g['metadata']['connectivity_scenarios']=evaluate(g,config)
    place_installation(g,profile)
    layout=check_layout(config,profile,g)
    g['metadata']['layout_compliance']=layout
    from placement import installation_diagnostics
    g['metadata']['installation_diagnostics']=installation_diagnostics(g,config,profile)
    for comp in g['components']:comp['mesh']=component_mesh(g,comp)
    g['metadata']['mesh_warnings']=[{'component':c['id'],'warnings':c['mesh']['warnings']} for c in g['components'] if c['mesh'].get('warnings')]
    from guidance import evaluate_guidance, source_register
    g['metadata']['guidance']=evaluate_guidance(config,g)
    g['provenance']['source_register']=source_register()
    from geometry_checks import diagnose
    g['metadata']['geometry_diagnostics']=diagnose(g,config)
    transform_layout(g,config)
    from zone_geometry import placement_checks
    placement=placement_checks(g['layout']['equipment_envelopes'],g['layout']['clearance_zones'])
    g['metadata']['geometry_diagnostics']['checks']+=placement
    g['metadata']['geometry_diagnostics']['blocking_failures']+=len(placement)
    if config.sizing_mode=='preliminary':
        missing=[f for f in g['metadata']['preliminary_sizing']['size_families'] if not f.get('selection')]
        for f in missing:g['metadata']['geometry_diagnostics']['checks'].append({'check':'Commercial size for '+f['family'],'status':'FAIL','actual':f['design_flow_m3_s'],'required':'Verified size within the velocity limit','detail':f['reason'],'actions':f.get('diagnostic',{}).get('actions',[])})
        g['metadata']['geometry_diagnostics']['blocking_failures']+=len(missing)
    footprint=footprint_check(g,config);g['metadata']['footprint_diagnostics']=footprint
    g['metadata']['geometry_diagnostics']['checks']+=footprint['checks']
    g['metadata']['geometry_diagnostics']['blocking_failures']+=sum(x['status']=='FAIL' for x in footprint['checks'])
    try:
        from parameters import catalog
        g['provenance']['tuning_parameters']=catalog()
    except ImportError:pass
    from equipment_requirements import build_requirements
    g['metadata']['equipment_requirements'] = build_requirements(g, config)
    return g,profile


def emit(graph,profile,out):
    from placement import installation_diagnostics
    from verify import run as verify_run
    config=Config(**graph['metadata']['config'])
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    exports=emit_all(graph,out,profile)
    graph['metadata']['emission']=exports
    trace=verify_run(graph,config,profile)
    graph['metadata']['verification']=trace['summary']
    graph['metadata']['emission']['status']='Draft generated; review traceability and geometric findings'
    dump(out/'traceability_matrix.json',trace)
    dump(out/'layout_compliance.json',graph['metadata']['layout_compliance'])
    dump(out/'installation_diagnostics.json',graph['metadata']['installation_diagnostics'])
    dump(out/'standards_profile.json',profile.manifest())
    dump(out/'config_used.json',asdict(config))
    dump(out/'export_manifest.json',exports)
    dump(out/'source_register.json',graph['provenance'].get('source_register',[]))
    dump(out/'guidance_diagnostics.json',graph['metadata'].get('guidance',{}))
    dump(out/'geometry_diagnostics.json',graph['metadata'].get('geometry_diagnostics',{}))
    dump(out/'connectivity_scenarios.json',graph['metadata'].get('connectivity_scenarios',{}))
    dump(out/'preliminary_sizing.json',graph['metadata'].get('preliminary_sizing',{'status':'Manual dimensions; preliminary sizing not selected'}))
    dump(out/'equipment_requirements.json',graph['metadata'].get('equipment_requirements',{}))
    dump(out/'equipment_candidates.json',graph['metadata'].get('equipment_finder',
         {'status':'not_searched','applied_config_hash':graph['metadata'].get('config_hash')}))
    from handoff import emit_handoff
    emit_handoff(graph,out)
    # Rewrite graph-derived JSON after emission/verification metadata is final.
    from emitters import _emit_geometry,_emit_flownex,_edge_index
    _emit_geometry(graph,out,_edge_index(graph));_emit_flownex(graph,out)
    dump(out/'graph.json',graph)
    (out/'routing_overview.svg').write_text(plan_svg(graph))
    report=['# Reference layout engineering review','',f'{config.rows*config.racks_per_row} compute racks; {config.network_rows*config.network_racks_per_row} air-cooled network racks; {config.cdu_count} CDU envelopes.',f'Layout: {config.layout_style}. Return topology: {config.return_topology}. CDU placement: {config.cdu_placement}.','', 'This is a parameterized reference layout, not a pressure or network solver. Manual mode retains selected commercial bores while estimating declared flows and pressure losses; preliminary mode also rounds pipe sizes. Nominal dimensions are catalogue values; equipment and fitting envelopes are conceptual.','', '## Installation and sources','', 'Every web control has a source or project-assumption label. Reference-specific dimensions are not universal installation requirements. The Deschutes checks apply only when that module profile is explicitly selected. Consult traceability_matrix.json, layout_compliance.json and installation_diagnostics.json for measured findings.', '', 'RD113 R0 spatial preset uses the page-5 diagram: 64 AI and 24 network racks, of which 8 are 40 kW. The prose and table conflict with this count. Its central network pod is air cooled. Cooling pods are independently assigned. Electrical infrastructure is outside this model.', '', '## Export handoff','', 'IFC4: typed physical objects, owned connected ports, separate FWS/TCS systems, and conceptual meshes. Import/link in Revit for coordination; IFC objects are not guaranteed native editable Revit MEP families. Confirm your Revit/IFC version and mapping.', '', 'PCF: pipes, bends, tees, valves, reducers and labelled MISC-COMPONENT inline placeholders. Map placeholders to the installed target component library. PCF is a generic interchange draft, not yet validated in licensed Flownex. No native Flownex .fnm is emitted.', '', 'JSON: complete connection graph, SI coordinates, equipment IDs, elevations, bores and source metadata. OBJ uses the same geometry as IFC and the web 3D view.','',f'Verification summary: {json.dumps(trace["summary"])}']
    (out/'ENGINEERING_REVIEW.md').write_text('\n'.join(report)+'\n')
    dump(out/'sha256_manifest.json',{str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name!='sha256_manifest.json'})
    return graph


def run(config,out):
    """Stage into a fresh directory; never validate or keep stale owned outputs."""
    out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
    graph,profile=build(config)
    with tempfile.TemporaryDirectory(prefix='.rd-stage-',dir=out.parent) as temp:
        stage=Path(temp);emit(graph,profile,stage)
        old=out/'sha256_manifest.json'
        owned=set(json.loads(old.read_text())) if old.exists() else set()
        out.mkdir(parents=True,exist_ok=True)
        for name in owned:
            path=(out/name).resolve()
            if path.is_relative_to(out.resolve()) and not (stage/name).exists() and path.is_file():path.unlink()
        for path in stage.rglob('*'):
            if path.is_file():
                dest=out/path.relative_to(stage);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dest)
    return graph
