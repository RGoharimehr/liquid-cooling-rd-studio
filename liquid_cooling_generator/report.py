"""Engineering audit report generated from the exact emitted graph."""
import csv
import json
import math
from pathlib import Path
from hydraulics import FLUIDS, loss, scenario_flow, select_size


def write_report(g, preliminary, output: Path, exports: dict, trace: dict | None = None):
    h=g['hydraulics']; f=h['heat_and_flow']; c=g['metadata']['config']
    scenarios=h['scenarios'];worst=max(scenarios,key=lambda s:s['required_tcs_pump_dp_Pa'])
    initial=max(preliminary['scenarios'],key=lambda s:s['required_tcs_pump_dp_Pa'])
    p=worst['worst_tcs_path'];fluid=FLUIDS['TCS'];total=f['total_heat_W']
    doc=['# Liquid cooling reference generator — engineering report',
         '', '**ENGINEERING CONCEPT — NOT FOR CONSTRUCTION.** Generated from `graph.json`; SI units throughout. Nominal commercial pipe sizes retain inches.',
         '', '**Scope.** This is a standards-driven *layout and connectivity* generator. It produces topology, geometry, component placement and connected model exports (IFC4, PCF, P&ID, BOM, neutral Flownex). It deliberately stops short of being a flow-network solver: no pump curve, heat-exchanger map or component resistance curve is required to produce the reference design, and none is invented. Pressure-drop figures below are a sizing sanity check on assumed component losses, not a solved network — that work belongs downstream in Flownex.',
         '', '## Checkpoint 1 — Graph schema and topology',
         '', f"The primary artifact contains {len(g['nodes'])} connection nodes, {len(g['components'])} tagged physical components and {len(g['edges'])} directed hydraulic edges. `model.py` supplies annotated runnable dataclasses. `checkpoint_1_topology.json` preserves the unsized topology, and `graph.json` contains the same identities with hydraulic results and coordinates.",
         '', 'Each component owns port node IDs. A tee owns three ports and two directed internal edges, but counts once in the BOM. Components include supply/return main and row piping, drops, isolation/balancing/check valves, reducers, elbows, QDs, rack manifolds, aggregated cold-plate loads, CDU primary/secondary heat exchangers, strainers and pumps. Header function is stored in the level/group attributes. Flow arrows come from edge direction. Heat-exchanger couplings transfer heat with zero mass transfer; no TCS node is shared with FWS.',
         '', f"The redundancy group is 3 installed / 2 duty / 1 spare. Each unit needs {f['cdu_duty_heat_W']/1000:.3f} kW at the actual PG25 temperatures and flow. Every single-CDU outage closes four isolation valves and disables that assembly. Check valves prevent reverse secondary discharge. Design bore uses maximum segment demand over all three outage scenarios. All-three-online operation assumes equal load sharing. The common headers remain single points of failure; this is CDU N+1, not full distribution redundancy.",
         '', '**Checkpoint 1 summary:** one connected hydraulic representation drives all outputs; redundancy and isolation are graph data.',
         '', '## Checkpoint 2 — Heat balance, sizing and source discipline',
         '', '### Boundary conditions',
         '', 'The verified ASHRAE fifth-edition reference card, Table 3.1, describes facility-water supply envelopes. The specified 27 °C FWS boundary is W27. TCS supply is derived as 27 °C + 3 K cold-end approach = 30 °C; rack return = 42 °C; mean = 36 °C. This is not a claim of TCS W32 certification. ASHRAE does not size the pipe. RD113 now refers to S-45; that nomenclature has not been independently reconciled to a newer ASHRAE source.',
         '', '**ASSUMPTION:** 25% PG means volume fraction; Dynalene inhibited PG is the property proxy. At 36 °C = 96.8 °F, interpolation between 90 and 100 °F has weight 0.68:',
         '', f"- Density = (63.64 + 0.68 × (63.47 − 63.64)) lb/ft³ × 16.01846337396 = **{fluid['rho_kg_m3']:.6f} kg/m³**.",
         f"- Specific heat = (0.942 + 0.68 × (0.945 − 0.942)) Btu/(lb·°F) × 4186.800584852 = **{fluid['cp_J_kg_K']:.6f} J/(kg·K)**.",
         f"- Dynamic viscosity = (1.74 + 0.68 × (1.49 − 1.74)) cP = **{fluid['mu_Pa_s']:.6f} Pa·s**.",
         '', 'Source: [Dynalene PG 2020 data sheet](https://www.dynalene.com/wp-content/uploads/2020/05/Dynalene-PG-Tech-Data-Sheet-Rev1.pdf), PDF pp3–4. Exact formulation and inhibitor compatibility remain unverified.',
         '', '**ASSUMPTION:** FWS rise = 10 K, so FWS return = 37 °C and mean = 32 °C. Water properties are rounded estimates: ρ = 995 kg/m³, cp = 4178 J/(kg·K), μ = 0.000770 Pa·s. Approach does not determine FWS flow. Hot-end approach = 42 − 37 = 5 K; cold-end = 30 − 27 = 3 K. Counterflow LMTD = (5 − 3)/ln(5/3) = 3.915 K; required ideal UA per duty CDU is about '+f"{f['cdu_duty_heat_W']/((5-3)/math.log(5/3))/1000:.1f} kW/K"+' before fouling/correction. Vendor HX confirmation is missing.',
         '', '### Unit-correct calculation chain',
         '', f"Per rack: {c['rack_power_W']/1000:g} kW × {c['liquid_fraction']:g} = **{f['rack_heat_W']/1000:g} kW liquid**. Per row: × {c['racks_per_row']} = **{f['row_heat_W']/1000:g} kW**. Hall: × {c['rows']} = **{total/1000:g} kW**. Per duty CDU: hall / 2 = **{f['cdu_duty_heat_W']/1000:g} kW**. Remaining air heat = **{f['air_heat_W']/1000:g} kW**.",
         '', 'For each loop: ṁ [kg/s] = heat [W] / (cp [J/(kg·K)] × ΔT [K]); q [m³/s] = ṁ [kg/s] / ρ [kg/m³]; q [L/min] = q [m³/s] × 60000.',
         '', f"Example rack: ṁ = {f['rack_heat_W']:.0f} / ({fluid['cp_J_kg_K']:.6f} × {c['tcs_delta_K']:g}) = {f['rack_mass_kg_s']:.6f} kg/s. q = {f['rack_mass_kg_s']:.6f} / {fluid['rho_kg_m3']:.6f} = {f['rack_m3_s']:.9f} m³/s = {f['rack_m3_s']*60000:.3f} L/min.",
         '', '| Level | Liquid heat kW | Mass kg/s | Volume m³/s | Volume L/min |',
         '|---|---:|---:|---:|---:|']
    levels=[('Rack','rack',f['rack_heat_W']),('Row','row',f['row_heat_W']),
            ('CDU secondary at N','cdu_secondary',f['cdu_duty_heat_W']),
            ('CDU primary at N','cdu_primary',f['cdu_duty_heat_W'])]
    for name,key,heat in levels:
        doc.append(f"| {name} | {heat/1000:.3f} | {f[key+'_mass_kg_s']:.6f} | {f[key+'_m3_s']:.9f} | {f[key+'_m3_s']*60000:.3f} |")
    for service in ('tcs','fws'):
        doc.append(f"| {service.upper()} hall total | {total/1000:.3f} | {f[service+'_total_mass_kg_s']:.6f} | {f[service+'_total_m3_s']:.9f} | {f[service+'_total_m3_s']*60000:.3f} |")
    doc += ['',f"With all three online, each carries {total/3/1000:.3f} kW, {f['tcs_total_m3_s']/3*60000:.3f} L/min secondary and {f['fws_total_m3_s']/3*60000:.3f} L/min primary. Installed ratings and design bores still use two-duty operation.",
        '', '### Pipe sizing',
        '', "Velocity caps are **per pipe category**, not global. The CloudScale guidance, §3.4 *TCS Flow Considerations*, states a flow velocity limit of **2.7 m/s (9 ft/s)** with erosion a concern above 3 m/s; that argument is made from stainless-steel erosion-corrosion, so it is applied to the stainless TCS headers and **not** transferred to Type L copper branches, which carry a declared conservative assumption instead. Every cap, its source clause and its status are in `standards_profile.json`. Diameter is Dmin [m] = √(4q [m³/s] / (π × vmax [m/s])), rounded upward by actual inside diameter. Actual v = 4q/(πDinside²).",
        '', '**Interpretation assumption:** Type L copper is used for rack drops/branches; steel is used for main, row and CDU distribution headers. All lengths are centre-line connector-to-connector lengths, not fabrication cut lengths. Copper uses CDA Table 14.2b dimensions for ASTM B88; steel uses public manufacturer Schedule 40 end-bore dimensions consistent with ASME B36.10M. Published nominal dimensions are not hydraulic inside diameters.',
        '', '| Family | Category | Flow L/min | Cap m/s | Dmin mm | Nominal in | Actual ID mm | Actual velocity m/s | Check |',
        '|---|---|---:|---:|---:|---:|---:|---:|---|']
    sizes=[]
    cats=g['metadata']['standards']['pipe_categories']
    for name,q,catname in [('Rack branch',f['rack_m3_s'],'tcs_rack_branch'),
                           ('Row header',f['row_m3_s'],'tcs_row_header'),
                           ('CDU TCS connection',f['cdu_secondary_m3_s'],'tcs_main'),
                           ('TCS main',f['tcs_total_m3_s'],'tcs_main'),
                           ('CDU FWS connection',f['cdu_primary_m3_s'],'fws_cdu'),
                           ('FWS main',f['fws_total_m3_s'],'fws_main')]:
        cat=cats[catname];cap=cat['velocity_cap_m_s'];material=cat['catalogue']
        s=select_size(q,material,cap);v=4*q/(math.pi*s['id_m']**2)
        sizes.append((name,q,material,s,v,cap,catname))
        doc.append(f"| {name} | `{catname}` | {q*60000:.3f} | {cap:g} | {s['required_id_m']*1000:.3f} | {s['nominal_size_in']:g} | {s['id_m']*1000:.3f} | {v:.3f} | {'PASS' if v<=cap else 'FAIL'} |")
    doc += ['', 'Header bores stay constant within each family; through-flow decreases after each branch takeoff. `hydraulic_edges.csv` records the actual segment-specific maximum flow and velocity. Equipment/connector bores are placeholder hydraulic bores, not selected vendor interfaces.',
        '', '### Pressure loss and pump duty',
        '', 'Darcy–Weisbach: Δp = (fL/D + K)ρv²/2. Re = ρvD/μ. Laminar f = 64/Re; turbulent (Re ≥ 4000) Swamee–Jain f = 0.25/[log10(ε/(3.7D) + 5.74/Re^0.9)]². **ASSUMPTION:** linear transition blend from Re 2300 to 4000. EPA EPANET 2.2 §3.1 is the method source. Steel roughness ε = 0.00004572 m from EPA Table 3.2; **ASSUMPTION:** copper ε = 0.0000015 m, new/clean condition.',
        '', 'Representative EPA Table 3.3 K values: fully open gate isolation 0.2; swing check 2.5; long-radius elbow 0.6; tee run 0.6; tee branch 1.8. **ASSUMPTION:** balancing-valve base K = 2; reducer/expander K = 0.15 (referenced to smaller connected bore). Actual geometry, Cv and operating split require vendor data. Every fitting is counted once along the traversed path.',
        '', '**ASSUMED design-flow equipment losses:** rack aggregate cold plates 50 kPa; each manifold 5 kPa; each QD 10 kPa; CDU secondary HX 60 kPa; primary HX 50 kPa; each clean strainer 15 kPa. Off-design loss scales as (q/qdesign)². These are placeholders and dominate the result. Pump edges impose no passive loss; head is calculated for the passive circuit from discharge back to suction.',
        '', '| Scenario | Worst CDU | Circuit pipe length m | Straight kPa | Fittings kPa | Equipment kPa | Total kPa | Pump with 20% margin kPa | Head m of PG25 | FWS interface with margin kPa |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for s in scenarios:
        pth=s['worst_tcs_path']
        doc.append(f"| {s['name']} | {pth['cdu']} | {pth['pipe_length_m']:.3f} | {pth['straight_dp_Pa']/1000:.3f} | {pth['fitting_dp_Pa']/1000:.3f} | {pth['equipment_dp_Pa']/1000:.3f} | {pth['dp_Pa']/1000:.3f} | {s['required_tcs_pump_dp_Pa']/1000:.3f} | {s['required_tcs_pump_head_m']:.3f} | {s['required_fws_available_dp_Pa']/1000:.3f} |")
    doc += ['', f"Critical case: **{worst['name']}**, CDU {p['cdu']}; pump duty is {f['cdu_secondary_m3_s']*60000:.3f} L/min at {worst['required_tcs_pump_dp_Pa']/1000:.3f} kPa differential ({worst['required_tcs_pump_head_m']:.3f} m PG25), including assumed 20% pressure margin. This is a preliminary required duty, not a selected pump curve. The primary requirement covers the modelled FWS interface-to-interface route only, not the external plant. It includes friction with 20% margin plus 2.927 kPa for the 0.3 m higher return boundary; boundary velocities are equal, so their kinetic terms cancel.",
        '', 'This is a demand-based, controlled-flow path calculation. Flow continuity is verified; pressure-balanced flows and operating pump intersections are not solved. Balancing-valve settings, control authority and sharing curves are missing. The required head is governed by maximum hydraulic resistance, which need not be the longest physical route. Static elevation cancels around the closed TCS; fill pressure, expansion, NPSH and absolute pressure constraints remain unresolved. `critical_path.csv` gives every traversed edge and its loss contribution.',
        '', '### Published benchmark comparison and discrepancy adjudication',
        '', '| Item | This calculation | RD111 published value | Result |',
        '|---|---:|---|---|',
        f"| Rack liquid heat | {f['rack_heat_W']/1000:g} kW | 142 kW × 0.87 = 123.54 kW | Similar heat, different test input |",
        f"| Rack branch bore | {sizes[0][3]['nominal_size_in']:g} in Type L | Not in downloaded overview | UNVERIFIED |",
        f"| Row header bore | {sizes[1][3]['nominal_size_in']:g} in Sch40 | Not in downloaded overview | UNVERIFIED |",
        f"| FWS main bore | {sizes[-1][3]['nominal_size_in']:g} in Sch40 | Not in downloaded overview | UNVERIFIED |",
        '| TCS temperatures | 30 / 42 °C | 40 / 53.8889 °C | Different operating points |',
        '', 'RD111 Revision 3 and RD113 Revision 1 public summaries were downloaded. Detailed engineering packages require a contact form; no personal information was submitted. No RD111 pipe-table transcription error can be adjudicated without that table. RD113 now covers 227 kW racks, 96% liquid = 217.92 kW, TCS 45/55 °C; it is not the same test case.',
        '', '**Verified source discrepancy, separate from RD111:** Wheatland’s 5-inch steel ID table prints 5.047 in and 158.2 mm. 5.047 × 25.4 = **128.1938 mm**, also confirmed by OD minus twice wall. The generator uses the inch dimension; the metric cell is inconsistent. This is not falsely presented as an RD111 discovery.',
        '', 'The OCP-listed ROL4000 advertises 2000 kW at 3 K and 500 US gpm PG25. This case requires 2006.4 kW and about 659 US gpm per duty CDU. That published product point does not establish capacity or flow suitability. Exact Deschutes interface requirements and the requested March TCS revision remain unverified.',
        '', '**Checkpoint 2 summary:** heat and flows are calculated independently; commercial bores pass the declared cap. Pump duty depends materially on assumed equipment losses, and the requested RD111 pipe comparison remains open.',
        '', '## Checkpoint 3 — Routing and feedback',
        '', f"**ASSUMED layout parameters:** rack pitch {c['rack_pitch_m']:g} m; rack depth {c['rack_depth_m']:g} m; clear row gap {c['aisle_width_m']:g} m; row pitch {c['rack_depth_m']+c['aisle_width_m']:g} m; first rack x {c['first_rack_x_m']:g} m; supply header elevation {c['header_elevation_m']:g} m; return elevation {c['header_elevation_m']+c['return_elevation_offset_m']:g} m; manifold elevation {c['manifold_elevation_m']:g} m; supply/return row centre-line lateral separation {2*c['header_half_separation_m']:g} m; CDU pitch {c['cdu_pitch_m']:g} m. Configurable values are in `config.json`.",
        '', f"The router assigns xyz coordinates to the existing node IDs, inserts no untracked geometry, and recomputes each straight pipe length from its endpoints. Fittings were already explicit in the graph. Total modelled straight pipe = **{g['metadata']['pipe_length_m']:.3f} m**. Tee/elbow takeouts and equipment envelopes are geometric assumptions; exact fitting arc lengths and manufacturer face-to-face dimensions are unresolved.",
        '', f"Before routing, each straight pipe was assumed {c['initial_pipe_length_m']:g} m. Maximum pump estimate changed from **{initial['required_tcs_pump_dp_Pa']/1000:.3f} kPa** to **{worst['required_tcs_pump_dp_Pa']/1000:.3f} kPa**, a change of **{(worst['required_tcs_pump_dp_Pa']-initial['required_tcs_pump_dp_Pa'])/1000:+.3f} kPa**. `checkpoint_2_preliminary.json` preserves the original calculation. `graph.json` and every final export use the routed lengths.",
        '', '### Layout conformance against the standards profile',
        '', 'Layout parameters are no longer round-number assumptions. Rack width/depth/height, aisle widths, bay width, row length, ceiling height and the wall-manifold and cable elevations are OCP Deschutes §18.1–18.4 dimensions, which that specification itself marks **critical**. Deschutes §18.4 places cable Level 4 at 139.5 in and §18.2 sets a minimum ceiling of 14 ft, so the distribution-header band is fully determined: supply and return centre lines must sit between those two elevations. Every parameter, its clause and its status (critical / recommended / assumption) is in `standards_profile.json`; every override is recorded as a declared deviation.',
        '', '| Check | Result | Actual | Required | Source |',
        '|---|---|---:|---:|---|']
    lay=g['metadata'].get('layout_compliance',{'results':[],'pass_count':0,'fail_count':0})
    for rr in lay['results']:
        doc.append(f"| {rr['check']} | **{rr['status']}** | {rr['actual']:.4f} | {rr['required']:.4f} | {rr['source']} |")
    doc += ['', f"{lay['pass_count']} pass, {lay['fail_count']} fail. " + (
        'Failures are reported, not suppressed: they are the points where the supplied test case or an assumed '
        'clearance cannot be reconciled with a critical OCP dimension, and each is resolved by tuning a parameter '
        'rather than by editing code.' if lay['fail_count'] else 'No conformance failures.'),
        '', 'Geometric conformance only. OCP Deschutes explicitly excludes structural qualification for static and '
        'seismic loads from its scope and assigns it to the data centre owner; this generator does the same.',
        '', '### Installation components placed',
        '', 'Supports, bracing, vents, drains, flexible connectors and drip trays are placed from the routed geometry. '
        'They carry coordinates and a host reference but **no hydraulic edge** — a hanger is not a flow element and a '
        'vent is normally closed — so they appear in the BOM, geometry and IFC without disturbing flow continuity.',
        '', '| Object | Count | Rule and source |',
        '|---|---:|---|']
    inst=g['metadata'].get('installation',{'by_kind':{}})
    rules={'pipe_support':'Published span by nominal size (ASME B31.1 steel / MSS SP-69 copper), plus a support at every in-line fitting and valve because published spans are invalid across a concentrated load.',
           'seismic_brace_transverse':'ASCE 7 practice: transverse brace every 40 ft, and within 24 in of each change of direction.',
           'seismic_brace_longitudinal':'ASCE 7 practice: longitudinal brace every 80 ft.',
           'vent':'ASHRAE TC 9.9 TCS Coolant Integrity, Air Management: avoid localised high points without venting. Placed at every local high point in the routed geometry.',
           'drain':'Low-point drain for fill, flush and decommissioning. Normally closed.',
           'flex_connector':'ASHRAE Ch11: TCS-to-rack joints need flexible piping / service loop against seismic movement.',
           'drip_tray':'CloudScale App. A: drip trays and leak detection beneath distribution piping.'}
    for k,v in sorted(inst.get('by_kind',{}).items()):
        doc.append(f"| {k.replace('_',' ')} | {v} | {rules.get(k,'')} |")
    doc += ['', f"Total {inst.get('added_component_count',0)} installation components. Hanger length is not modelled, "
        "so the ASCE 7 exemption for pipe suspended within 12 in of structure cannot be evaluated and bracing is "
        "placed without it.",
        '', '**Checkpoint 3 summary:** real centre-line lengths feed the same hydraulic engine. Geometry remains a conceptual arrangement; clash detection, access, supports, pipe stress and precise fitting envelopes are not completed.',
        '', '## Checkpoint 4 — Design-decision traceability',
        '', 'Every design choice is registered with the document and clause that governs it, the verbatim quote '
        'that must be findable in the reference corpus, and a named check that runs against the generated graph. '
        'Three layers are verified: **evidence** (is the quote actually in the source?), **model** (does the '
        'generated design actually obey it?) and **coverage** (is the register itself sound?). Full detail in '
        '`traceability_matrix.json`.', '']
    if trace:
        s_=trace['summary']
        doc += [f"Corpus authority: **{s_['corpus_authority']}**. "
                f"{s_['decisions']} decisions · evidence {s_['evidence']} · model {s_['model']} · "
                f"**{s_['blocking_failures']} blocking failure(s)**.", '',
                '| ID | Area | Design choice | Basis | Document · clause | Evidence | Check | Measured | Required |',
                '|---|---|---|---|---|---|---|---:|---:|']
        for row in trace['traceability_matrix']:
            meas = row['measured'] if row['measured'] is not None else ''
            req = row['required'] if row['required'] is not None else ''
            mark = {'PASS':'PASS','FAIL':'**FAIL**','NO_CHECK':'—','NOT_EVALUABLE':'n/e','ERROR':'**ERROR**'}.get(row['model_status'],row['model_status'])
            ev = {'FOUND':'found','NOT_FOUND':'**NOT FOUND**','EXTERNAL_NOT_IN_DATABASE':'not in DB','NOT_APPLICABLE':'n/a','NO_CORPUS':'no corpus'}.get(row['evidence_status'],row['evidence_status'])
            doc.append(f"| {row['id']} | {row['area']} | {row['choice']} | {row['basis']} | "
                       f"{row['document']} · {row['clause']} | {ev} | {mark} | {meas} | {req} |")
        doc += ['', '**How to read the basis column.** `standard_mandate` means the source states a requirement or a '
                'hard number. `standard_guidance` means it recommends without a number. `derived` follows '
                'arithmetically from other decisions. `user_input` came with the test case and carries no standards '
                'authority. `assumption` means no source was found — these are the honest gaps. '
                '`external_standard` means the cited standard is real but is **not in this project reference '
                'database**, so its quote cannot be verified here.', '']
        if trace['blocking_failures']:
            doc += ['### Blocking conformance failures', '',
                    'These are not tuning gaps. The design as configured does not fit the referenced equipment:', '']
            for b in trace['blocking_failures']:
                d = None
                for row in trace['traceability_matrix']:
                    if row['id'] == b['id']:
                        d = row
                        break
                doc.append(f"- **{b['id']} — {d['choice'] if d else b['check']}.** Measured **{b['actual']}**, "
                           f"required **{b['expected']}** ({b['detail']}). Source: {d['document']} §{d['clause']}." if d else
                           f"- **{b['id']}** measured {b['actual']}, required {b['expected']}.")
            doc += ['', 'The generator does not suppress these. It reports them and exits with them visible, because '
                    'a reference design that silently exceeds the capacity of the equipment it references is worse '
                    'than one that refuses to pretend.', '']
        if trace['coverage_issues']:
            doc += ['### Register coverage audit', '']
            for issue in trace['coverage_issues']:
                doc.append(f"- `{issue['kind']}` — {issue['detail']}")
            doc.append('')
    doc += ['', '## Checkpoint 5 — Actual model emitters',
        '', '`emitters.py` contains runnable code. It receives only the final graph and writes:',
        '', '- Tagged graph-derived SVG P&ID sheets, shared-node cross-sheet references, directional connectors and symbol legend. Project symbols are conceptual process symbols; licensed standard compliance and full controls/instrumentation are unverified.',
        '- `valve_schedule.csv`, one-row-per-component `BOM.csv`, grouped `BOM_summary.csv`, and supporting manifests. These are graph takeoffs, excluding unmodelled supports, insulation, joints, drain/vent/expansion and procurement accessories.',
        '- Generic draft PCF with millimetre coordinates and nominal inch bores, selected for a piping/isometric workflow without an IFC runtime dependency. Exact component IDs link back to graph ports. `geometry_export_manifest.json` explicitly reports unsupported items; `geometry_network.json` retains all component ports and coordinates. PCF importer round-trip validation is outstanding, and this is not a fabrication file.',
        '- Neutral Flownex network JSON with fluid properties, nodes, loss elements, loops and thermal couplings. No proprietary native Flownex import or executable simulation is claimed. Missing items include product libraries, pump/HX/valve curves, controls, solver boundary/initial conditions and vendor-approved importer mapping.',
        f'- **IFC4** (`{exports.get("ifc_file")}`): {exports.get("ifc_element_count","-")} elements across IfcFlowSegment / IfcFlowFitting / IfcFlowController / IfcFlowMovingDevice / IfcEnergyConversionDevice / IfcFlowTreatmentDevice / IfcFlowTerminal / IfcDiscreteAccessory. Port connectivity is the point: every graph node becomes an `IfcDistributionPort`, ports are nested into their element with `IfcRelNests`, and ports sharing a node are joined with `IfcRelConnectsPorts` — {exports.get("ifc_port_connections","-")} links. Re-reading the file and traversing element→port→port→element recovers exactly two connected networks, TCS and FWS, confirming the CDU couplings transfer heat without creating a hydraulic path. Category, size, flow, velocity, the governing cap and its source clause ride along in `Pset_LCG_Hydraulic`; installation rules in `Pset_LCG_Installation`. Not validated in Revit; no clash detection, support design or fabrication review.',
        f'- **Neutral OBJ mesh** (`{exports.get("mesh_obj")}`): {exports.get("mesh_vertices","-")} vertices, '
        'material-grouped by service and by installation type so supports, braces, trays and vents can be hidden '
        'in one click. Opens directly in Blender with no add-on — a scripted Blender pipeline was deliberately '
        'not built, because it would add a dependency and a headless-render step for capability the viewer '
        'already has.',
        '', '**Checkpoint 5 summary:** working emitters share one graph. P&ID and BOM cover every modelled physical item; PCF and Flownex limitations are explicit.',
        '', '## Checkpoint 6 — Self-audit',
        '', '### Calculated, assumed and sourced',
        '', '**Calculated:** captured heat, liquid mass/volume flow, PG interpolation, minimum IDs, nominal-size selection, actual velocity/Re/friction, scenario flow allocation, routed length, path loss, pump differential/head, FWS interface loss and schedule quantities. Values are reproducible in code and detailed CSV/JSON files.',
        '', '**User supplied:** 4 × 8 racks at 132 kW and 95% liquid; 3 CDUs N+1; PG25; 12 K TCS rise; 27 °C FWS; 3 K approach; copper branches/steel headers; overhead layout. Changes through configuration are recorded in the graph.',
        '', '**Sourced:** ASHRAE facility class limits; Dynalene property table points; commercial pipe dimensions; EPA roughness and representative K values; RD111/RD113 published thermal conditions. Detailed page references, downloaded files, URLs, hashes and source corrections are recorded under `references/`.',
        '', '**Assumed:** PG volume basis/formulation; FWS 10 K rise and water properties; 2 m/s cap; layout/envelopes; copper roughness; clean conditions; component loss curves; balancing/control behavior; 20% head margin; interpretation of material allocation; aggregated rack internals. Every assumption is represented in source/code comments, configuration or provenance. No pressure/temperature rating is inferred from nominal pipe size.',
        '', '### If racks rise to 250 kW',
        '', 'At unchanged liquid fraction and ΔT, heat and flow scale by 250/132 = 1.893939. Keeping the original installed bores gives:',
        '', '| Family | Flow at 250 kW L/min | Velocity in original bore m/s | Category cap m/s | Check |',
        '|---|---:|---:|---:|---|']
    ratio=250000/c['rack_power_W']
    for name,q,material,s,v,cap,catname in sizes:
        doc.append(f"| {name} | {q*ratio*60000:.3f} | {v*ratio:.3f} | {cap:g} | {'FAIL' if v*ratio>cap else 'PASS'} |")
    doc += ['', f"Hall liquid heat becomes {total*ratio/1e6:.3f} MW and each duty CDU needs {f['cdu_duty_heat_W']*ratio/1e6:.3f} MW. Rack flow becomes {f['rack_m3_s']*ratio*60000:.3f} L/min. Installed CDU capacity, HX UA, branch/QD/manifold curves, pumps and pressure ratings must be revisited. Fixed-bore quadratic component losses rise by roughly {ratio**2:.3f}×; friction also changes with Re. Resizing may exceed the verified catalogue (currently through 14-inch steel), in which case the CLI stops with an explicit error. Changing only the rack-power parameter does not certify new hardware.",
        '', '### What is incomplete, and what a reviewing engineer would reject first',
        '', 'A reviewer would first reject the claim that this is buildable: selected CDU/HX/pump curves, cold-plate/QD pressure loss and ratings, precise Deschutes interfaces, coolant cleanliness/material compatibility, expansion/relief/fill/drain/vent arrangements, leak detection and control sequences are absent. Carbon steel in a liquid-to-chip TCS needs explicit OEM cleanliness/corrosion approval. The current conceptual routing has not passed clash or fabrication checks. Common-header failure defeats distribution redundancy.',
        '', 'The hydraulic engine enforces demand-flow conservation and computes path losses; it does not solve coupled nonlinear pressure/flow/pump/control behavior. Balancing valves are present, but final settings and off-design authority are unresolved. Pump margin is assumed; pressure rating, NPSH, static fill pressure, fouling and transient analyses remain open. The BOM omits unmodelled installation accessories. PCF is generic and partial; Flownex output is a neutral network description with a gaps list. RD111 diameter adjudication and exact OCP compliance could not be completed from accessible sources.',
        '', '**Checkpoint 6 summary:** the software pipeline is runnable and internally checked; the result is a reviewable reference-design concept with explicit engineering hold points.',
        '', '## Source records',
        '', 'See [`engineering_sources.md`](../references/engineering_sources.md) and [`sources_benchmarks.md`](../references/sources_benchmarks.md), plus their JSON manifests. Those records identify exact source pages and versions, and distinguish downloaded final documents from mutable working copies.',
        '', '## Reproduction',
        '', 'From the project folder: `python3 run.py --config config.json --out outputs`. No third-party packages are required. Run `python3 -m unittest discover -s tests -v` for invariant and regression checks.', '']
    (output/'engineering_report.md').write_text('\n'.join(doc),encoding='utf-8')
    fields=['id','component_id','service','level','kind','from_node','to_node','design_flow_m3_s',
            'nominal_size_in','id_m','required_id_m','length_m','velocity_m_s','Re','friction_factor','K',
            'straight_dp_Pa','fitting_dp_Pa','equipment_dp_Pa','dp_Pa']
    with (output/'hydraulic_edges.csv').open('w',newline='') as stream:
        w=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(g['edges'])
    edges={e['id']:e for e in g['edges']}
    with (output/'critical_path.csv').open('w',newline='') as stream:
        w=csv.DictWriter(stream,fieldnames=['sequence','scenario']+fields,extrasaction='ignore');w.writeheader()
        for j,eid in enumerate(p['edge_ids'],1):
            e=edges[eid];q=scenario_flow(e,worst['active_cdus'])
            w.writerow({**e,**loss(e,q),'design_flow_m3_s':q,'sequence':j,'scenario':worst['name']})


def routing_svg(g,path):
    """Standalone vector isometric review figure; renderer reads only the graph."""
    import html
    nodes={n['id']:n for n in g['nodes']}
    c=g['metadata']['config'];h=g['hydraulics']['heat_and_flow']
    maxhead=max(v['required_tcs_pump_dp_Pa'] for v in g['hydraulics']['scenarios'])
    def project(p):
        x,y,z=p;return (x*.87-y*.5, x*.30+y*.36-z*.90)
    coords={n:project(d['xyz_m']) for n,d in nodes.items()};xs,ys=zip(*coords.values())
    scale=min(1200/(max(xs)-min(xs)),690/(max(ys)-min(ys)))
    def xy(n):
        p=coords[n];return (80+(p[0]-min(xs))*scale,130+(p[1]-min(ys))*scale)
    s=['<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="980" viewBox="0 0 1400 980">',
       '<rect width="1400" height="980" fill="#f5f7fa"/>',
       '<text x="50" y="48" font-family="sans-serif" font-size="28" font-weight="bold" fill="#182c3b">Liquid cooling | routed graph</text>',
       f'<text x="50" y="80" font-family="sans-serif" font-size="16" fill="#506273">{c["rows"]} rows × {c["racks_per_row"]} racks · overhead supply / return · 3 CDUs in N+1 · centre-line concept</text>']
    for e in sorted(g['edges'],key=lambda e:e['service']):
        a,b=xy(e['from_node']),xy(e['to_node']);col='#147eb3' if e['service']=='TCS' else '#ba7321'
        stroke=2 if e['kind']=='pipe' else 3.2
        tip=f"{e['component_id']} | {e['kind']} | {e['nominal_size_in']:g} in | {e['design_flow_m3_s']*60000:.1f} L/min"
        s.append(f'<line x1="{a[0]:.2f}" y1="{a[1]:.2f}" x2="{b[0]:.2f}" y2="{b[1]:.2f}" stroke="{col}" stroke-width="{stroke}" opacity=".8"><title>{html.escape(tip)}</title></line>')
    for comp in g['components']:
        if comp['kind']=='rack_load':
            a,b=[xy(n) for n in comp['ports']];x=(a[0]+b[0])/2;y=(a[1]+b[1])/2
            s.append(f'<rect x="{x-13:.1f}" y="{y-8:.1f}" width="26" height="16" rx="3" fill="#d6eaf3" stroke="#176c9c"><title>Row {comp["row"]} Rack {comp["rack"]}</title></rect>')
    s.append('<rect x="950" y="160" width="395" height="450" rx="14" fill="white" stroke="#d7dfe6"/>')
    values=[('REFERENCE RUN',None),('Liquid heat',f'{h["total_heat_W"]/1e6:.4f} MW'),
            ('TCS flow',f'{h["tcs_total_m3_s"]*60000:,.0f} L/min'),
            ('FWS flow',f'{h["fws_total_m3_s"]*60000:,.0f} L/min'),
            ('TCS temperatures',f'{c["tcs_supply_C"]:g} / {c["tcs_supply_C"]+c["tcs_delta_K"]:g} °C'),
            ('Duty per CDU',f'{h["cdu_duty_heat_W"]/1e6:.4f} MW'),
            ('Preliminary pump Δp',f'{maxhead/1000:.1f} kPa'),
            ('Routed straight pipe',f'{g["metadata"]["pipe_length_m"]:.2f} m')]
    for j,(label,value) in enumerate(values):
        yy=198+j*48
        s.append(f'<text x="975" y="{yy}" font-family="sans-serif" font-size="15" fill="#506273">{html.escape(label)}</text>')
        if value:s.append(f'<text x="1320" y="{yy}" text-anchor="end" font-family="sans-serif" font-size="17" font-weight="bold" fill="#182c3b">{html.escape(value)}</text>')
    s += ['<text x="50" y="900" font-family="sans-serif" font-size="17" fill="#147eb3">Blue: TCS PG25</text>',
          '<text x="250" y="900" font-family="sans-serif" font-size="17" fill="#ba7321">Amber: FWS water</text>',
          '<text x="50" y="937" font-family="sans-serif" font-size="16" fill="#8d4337">ENGINEERING CONCEPT — NOT FOR CONSTRUCTION. Vendor envelopes and clash checks pending.</text></svg>']
    path.write_text('\n'.join(s),encoding='utf-8')
