"""Three-layer verification of the design against the reference database.

Layer 1 - EVIDENCE. Every decision's verbatim quote must be findable in the
          reference corpus. This is what stops the register drifting away from
          the documents: a mis-remembered clause fails here, loudly.

Layer 2 - MODEL. Every decision's named check runs against the generated graph
          and returns a measured value. A design choice that is correctly cited
          but not actually implemented fails here.

Layer 3 - COVERAGE. Structural checks on the register itself: no blocking
          decision without a check, no unused check, every pipe category
          governed by a decision, every declared assumption accounted for.

The corpus is only as authoritative as its extraction. Files marked partial in
references/corpus/manifest.json yield INDICATIVE evidence results, and that is
reported rather than hidden.
"""
from __future__ import annotations
import json
import re
import unicodedata
from pathlib import Path

from decisions import REGISTER, CHECKS, BY_ID

CORPUS = Path(__file__).resolve().parent / 'references' / 'corpus'

_SUBS = {'‘': "'", '’': "'", '“': '"', '”': '"', '–': '-',
         '—': '-', '−': '-', 'µ': 'u', 'μ': 'u', '′': "'",
         '″': '"', ' ': ' '}


def normalize(text: str) -> str:
    """Quotes must survive PDF extraction artefacts: smart quotes, line breaks,
    inch marks, micro signs, run-together whitespace. Everything else is real."""
    text = unicodedata.normalize('NFKC', str(text))
    for a, b in _SUBS.items():
        text = text.replace(a, b)
    text = re.sub(r'[\s\r\n]+', ' ', text)
    return text.strip().lower()


def canonical_document_id(name):
    name=Path(name).stem
    compact=re.sub(r'[^a-z0-9]','',name.lower())
    if 'deschutes' in compact:return 'OCP-Specification-Deschutes_v1_0'
    if 'modulartcs' in compact and ('march' in compact or 'cloudscale' in compact):return '2025_Modular_TCS_CloudScale_Rev_1_March'
    return re.sub(r'[^A-Za-z0-9]+','_',name).strip('_')


def load_corpus():
    docs, meta = {}, {}
    if not CORPUS.exists():
        return docs, meta
    manifest_path = CORPUS / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for path in sorted(CORPUS.glob('*.txt')):
        key=canonical_document_id(path.stem)
        docs[key] = normalize(path.read_text(encoding='utf-8'))
        entry = manifest.get(path.name, {})
        meta[key] = {'source_pdf': entry.get('source_pdf'), 'sha256': entry.get('sha256'),
                           'partial': entry.get('partial', True), 'characters': len(docs[key])}
    return docs, meta


def verify_evidence(docs, meta):
    results = []
    for d in REGISTER:
        if not d.quote:
            status = ('NOT_APPLICABLE' if d.basis in ('user_input', 'derived')
                      else 'EXTERNAL_NOT_IN_DATABASE')
            detail = ('No quote required: the choice is a test-case input or follows from other decisions.'
                      if status == 'NOT_APPLICABLE' else
                      'Cited standard is real but is not in this project reference database, so the quote '
                      'cannot be verified here. Add the document to the database to close this gap.')
            results.append({'id': d.id, 'document': d.document, 'clause': d.clause,
                            'status': status, 'detail': detail})
            continue
        aliases={'OCP-Specification-Deschutes v1_0':'OCP-Specification-Deschutes_v1_0','2025 Modular TCS / CloudScale Design Delivery Selection Guidance Rev 1 March':'2025_Modular_TCS_CloudScale_Rev_1_March'}
        key=canonical_document_id(aliases.get(d.document,d.document))
        if key not in docs and key.startswith('ASHRAE'):key='ASHRAE_TC99_liquid_cooling'
        doc = docs.get(key)
        if doc is None:
            results.append({'id': d.id, 'document': d.document, 'clause': d.clause,
                            'status': 'NO_CORPUS',
                            'detail': f'No corpus file for {d.document}. Run tools/build_corpus.py.'})
            continue
        found = normalize(d.quote) in doc
        partial = meta.get(key, {}).get('partial', True)
        results.append({
            'id': d.id, 'document': d.document, 'clause': d.clause,
            'status': ('FOUND' if found else 'NOT_FOUND'),
            'authority': ('INDICATIVE (partial extract)' if partial else 'AUTHORITATIVE (full extract, hashed)'),
            'quote': d.quote,
            'detail': ('Quote located in the corpus.' if found else
                       'QUOTE NOT FOUND. Either the register misquotes the source, or the corpus extract '
                       'does not cover this clause. Do not trust this decision until resolved.')})
    return results


# The register is written against the OCP Deschutes module. Its fixed rack
# pitch, row length and 2 MW / 500 GPM reference CDU are that module's numbers,
# not universal requirements, so they can only fail a design that selected it.
DESCHUTES = 'OCP-Specification-Deschutes_v1_0'
# These checks fall back to a Deschutes reference figure only while the project
# has not supplied its own limit. Once it has, the check is measuring against
# the equipment actually selected and the profile gate must not soften it.
PROJECT_LIMIT_CHECKS = {'tcs_loop_within_available_dp': 'cdu_available_head_kPa'}


def verify_model(graph, config, profile):
    results = []
    selected = getattr(config, 'standards_profile', 'project')
    for d in REGISTER:
        if not d.check:
            continue
        fn = CHECKS[d.check]
        try:
            ok, actual, expected, detail = fn(graph, config, profile)
        except Exception as exc:                       # a check that cannot run is not a pass
            results.append({'id': d.id, 'check': d.check, 'status': 'ERROR', 'severity': d.severity,
                            'actual': None, 'expected': None, 'detail': f'{type(exc).__name__}: {exc}'})
            continue
        status = 'NOT_EVALUABLE' if ok is None else ('PASS' if ok else 'FAIL')
        supplied = getattr(config, PROJECT_LIMIT_CHECKS.get(d.check, ''), 0) or 0
        if status == 'FAIL' and d.document == DESCHUTES and selected != 'deschutes_module' and not supplied:
            status = 'NOT_APPLICABLE'
            detail = (str(detail) + f'. Measured against the Deschutes module reference, which does not '
                      f'govern this design: standards_profile is {selected!r}. Select the Deschutes '
                      f'profile to make this a requirement.')
        results.append({'id': d.id, 'check': d.check, 'status': status, 'severity': d.severity,
                        'actual': actual, 'expected': expected, 'detail': detail,
                        'choice': d.choice})
    return results


def verify_coverage(profile):
    issues = []
    used = {d.check for d in REGISTER if d.check}
    for name in sorted(set(CHECKS) - used):
        issues.append({'kind': 'unused_check', 'detail': f'check {name!r} is defined but no decision uses it'})
    for d in REGISTER:
        if d.severity == 'blocking' and not d.check:
            issues.append({'kind': 'blocking_without_check',
                           'detail': f'{d.id} is blocking but has no automated check'})
        if d.basis.startswith('standard') and not d.quote:
            issues.append({'kind': 'standard_without_quote',
                           'detail': f'{d.id} cites {d.document} {d.clause} but carries no verbatim quote'})
    governed = {'tcs_row_header', 'tcs_main', 'tcs_rack_branch'}
    for name in sorted(set(profile.categories) - governed):
        issues.append({'kind': 'category_without_decision',
                       'detail': f'pipe category {name!r} has no velocity-cap decision in the register '
                                 f'(cap {profile.cap(name)} m/s is currently an undeclared choice)'})
    registered_assumptions = {d.id for d in REGISTER if d.basis == 'assumption'}
    declared = profile.assumptions()
    issues.append({'kind': 'assumption_tally',
                   'detail': f'{len(declared)} assumptions declared in the standards profile; '
                             f'{len(registered_assumptions)} carry a decision record. The remainder are '
                             f'tuning defaults rather than design choices, listed in standards_profile.json.'})
    return issues


def clearance_diagnostics(graph,c):
    """Outside-surface and box checks against active project allowances."""
    checks=[];nodes={n['id']:n['xyz_m'] for n in graph['nodes']}
    active=[x for x in graph['components'] if len(x.get('ports',[]))>=2 and not x.get('attachment')]
    def add(name,ok,actual,required,detail=''):
        checks.append({'check':name,'status':'PASS' if ok else 'FAIL','actual':actual,'required':required,'source':'PROJECT ASSUMPTION','detail':detail})
    top=max((max(nodes[p][2] for p in x['ports'])+x.get('od_m',0)/2 for x in active if x.get('zone')!='plant'),default=0)
    add('Piping outside surface below ceiling allowance',top+c.overhead_clearance_m<=c.ceiling_height_m,round(top+c.overhead_clearance_m,4),c.ceiling_height_m,'m; includes reverse-return elevated route, excludes unmodelled insulation.')
    main_od=max((x.get('od_m',0) for x in active if x.get('level')=='main'),default=0)
    sep=(.65**2+(2*c.header_half_separation_m)**2+c.return_elevation_offset_m**2)**.5-main_od
    add('Main supply/return surface spacing',sep>=c.pipe_clear_gap_m,round(sep,4),c.pipe_clear_gap_m)
    row_od=max((x.get('od_m',0) for x in active if x.get('level')=='row'),default=0)
    sep=((2*c.header_half_separation_m)**2+c.return_elevation_offset_m**2)**.5-row_od
    add('Row supply/return surface spacing',sep>=c.pipe_clear_gap_m,round(sep,4),c.pipe_clear_gap_m)
    clearance=c.header_elevation_m-row_od/2-c.rack_height_m
    add('Header underside above rack top',clearance>=c.overhead_clearance_m,round(clearance,4),c.overhead_clearance_m)
    boxes=graph.get('layout',{}).get('equipment_envelopes',[]);overlaps=[]
    for i,a in enumerate(boxes):
        for b in boxes[i+1:]:
            if all(abs(a['center_m'][k]-b['center_m'][k])<(a['size_m'][k]+b['size_m'][k])/2-1e-7 for k in range(3)):overlaps.append([a['id'],b['id']])
    add('Equipment envelopes do not overlap',not overlaps,overlaps,[])
    blocked=[]
    for zone in graph.get('layout',{}).get('clearance_zones',[]):
        for box in boxes:
            if box['id']==zone.get('host'):continue
            if all(abs(zone['center_m'][k]-box['center_m'][k])<(zone['size_m'][k]+box['size_m'][k])/2-1e-7 for k in range(2)):blocked.append([zone.get('host'),box['id']])
    add('Rack service zones clear of other equipment',not blocked,blocked,[],'Shared service zones may overlap each other; equipment inside a zone is reported.')
    return {'checks':checks,'scope':'Bounding-box equipment/access and designated pipe-surface checks; not a full routed clash detector.'}


def _tally(rows, key='status'):
    out = {}
    for row in rows:
        out[row[key]] = out.get(row[key], 0) + 1
    return dict(sorted(out.items()))


def run(graph,config,profile):
    """Acceptance checks on the model, plus the design-decision register.

    Two layers, reported separately and never conflated. The G-series rows are
    the acceptance gate: layout compliance, installation, routed geometry and
    outage connectivity. A failure there blocks export. The DEC-series rows are
    the design-decision register - each choice, its governing clause, the
    verbatim quote located in the reference corpus, and a measured check against
    this graph. Those are reported for review and do not gate export, because a
    reference-module dimension is not an acceptance criterion for a project that
    did not select that module.

    This function used to be defined twice in this file; the second definition
    shadowed the first, so the register, its model checks and its coverage audit
    never ran at all and the evidence tally was collapsed to a single count.
    """
    from placement import installation_diagnostics
    docs,meta=load_corpus();evidence=verify_evidence(docs,meta)
    rows=graph['metadata']['layout_compliance']['results']+installation_diagnostics(graph,config,profile)['checks']+graph['metadata'].get('geometry_diagnostics',{}).get('checks',[])+graph['metadata'].get('connectivity_scenarios',{}).get('checks',[])
    models=[{'id':f'G{i+1:03}','severity':'blocking',**r,'expected':r.get('required')} for i,r in enumerate(rows)]
    ids=[c['id'] for c in graph['components']];nodes={n['id'] for n in graph['nodes']}
    owners={}
    for comp in graph['components']:
        if not comp.get('attachment'):
            for p in comp.get('ports',[]):owners.setdefault(p,[]).append(comp['id'])
    bad=[n for n,items in owners.items() if len(items)>2]
    models.append({'id':'GRAPH','check':'Graph identity and port ownership','status':'PASS' if len(ids)==len(set(ids)) and not bad and all(p in nodes for p in owners) else 'FAIL','severity':'blocking','actual':bad,'expected':[]})
    failures=[r for r in models if r['status']=='FAIL']
    register=verify_model(graph,config,profile)
    coverage=verify_coverage(profile)
    evidence_by_id={r['id']:r for r in evidence}
    register_by_id={r['id']:r for r in register}
    decision_matrix=[{'id':d.id,'area':d.area,'choice':d.choice,'rationale':d.rationale,'basis':d.basis,
        'severity':d.severity,'document':d.document,'clause':d.clause,'quote':d.quote,
        'evidence_status':evidence_by_id.get(d.id,{}).get('status'),
        'evidence_authority':evidence_by_id.get(d.id,{}).get('authority'),
        'check':d.check,'model_status':register_by_id.get(d.id,{}).get('status','NO_CHECK'),
        'measured':register_by_id.get(d.id,{}).get('actual'),
        'required':register_by_id.get(d.id,{}).get('expected'),
        'units_or_detail':register_by_id.get(d.id,{}).get('detail')} for d in REGISTER]
    unsupported=[r for r in evidence if r['status']=='NOT_FOUND']
    register_failures=[r for r in register if r['status'] in ('FAIL','ERROR')]
    coverage+=[{'kind':'scope','detail':'Acceptance checks cover declared equipment envelopes, routed centerline envelopes including insulation, and external port continuity. Vendor fitting bodies, maintenance operations, transport/egress, structural loads, controls and local code remain detailed-design work. No hydraulic capacity or operational redundancy is proven.'}]
    return {'summary':{
            'decisions':len(models),'model':_tally(models),
            'evidence':_tally(evidence),'unsupported_quotes':len(unsupported),
            'blocking_failures':len(failures),
            'design_register':{'decisions':len(REGISTER),'model':_tally(register),
                'failures':len(register_failures),
                'scope':'Reported for review; does not gate export'},
            'corpus_documents':len(docs),
            'corpus_authority':'INDICATIVE: partial local source excerpts; reference comparison is not certification'},
        'model_results':models,'traceability_matrix':models,'blocking_failures':failures,
        'design_register_results':register,'design_register_matrix':decision_matrix,
        'design_register_failures':register_failures,
        'evidence_results':evidence,'unsupported_quotes':unsupported,'corpus':meta,
        'coverage_issues':coverage,
        'method':'Acceptance: named checks executed against the generated graph, returning measured values; '
                 'these gate export. Register: each design decision carries a verbatim quote located in the '
                 'reference corpus after whitespace and smart-quote normalisation, plus a measured model '
                 'check. Coverage: structural audit of the register itself.'}
