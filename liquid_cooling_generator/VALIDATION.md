# Validation record — 14 September 2026

The full engine suite passed **110 tests and 15 subtests** using `.venv-ifc/bin/python -m pytest -q`. All frontend scripts passed: zone-interaction, zone-draft, agent (12 tests), finder, and engine/Pyodide. TypeScript passed. The three shipped presets generated and exported 1,586, 2,877 and 2,256 components in Pyodide.

## Current repair regressions

- Active pipeline N+0/N+1/N+2 cases enumerate the correct CDU outage combinations; inactive units and their isolation paths are removed. Scenario heat is conserved within each pod.
- Global N+2 with only two CDUs per independent pod explicitly reports unavailable pods and unserved heat, fails required connectivity checks, and marks affected equipment duties unresolved. Relaxing the declared outage count repairs the same editable concept.
- Browser imports preserve explicit air-cooled/water-cooled plant choices for missing, v1 and v2 schema markers. Legacy files with no plant retain boundary scope. Unknown keys and unsupported versions are rejected.
- Draft arrangement tests cover repeated moves, independent zone edits, four rotations, repeated flips, world origin/rotation transforms, overlap detection, and no-op selection without changing applied inputs.
- The browser no longer invokes the zone auto-apply API. The older atomic Python API remains covered for compatibility; its tests do not define the current UI behavior.

In the local in-app browser, the actual zone selector, Rotate 90°, Flip X and Flip Y worked before generation. Three rotations, repeat flips, two pointer drags, one-action Undo, and a pod keyboard move accumulated in a draft without starting a worker. Apply ran once for the full draft and reported a specific FWS elbow clash. Further draft changes and Apply repaired that same design without changing presets; normal downloads became enabled at hash prefix `b266d04580f7`. The package action started, but a browser reload prevented confirmation of its completion. Engine exports passed independently; no current browser ZIP was inspected on disk. The final production build passed.

## Verified engine coverage

- Air-cooled and water-cooled plant circuits, independent TCS pods, connected four-port CDUs and separate heat-transfer relationships.
- Aggregate CRAH/wall-coil FWS connections and the residual compute, network and additional air-load ledger. Air heat is counted once in chiller duty and is excluded from CDU/TCS duty.
- Six crossing-pair regressions, explicit reducer turns, coaxial connectors, actual port bores and pipe/fitting/equipment-envelope diagnostics.
- Whole-pod and equipment-zone rotation/mirroring, world origins, network rotation applied once, read-only overlap rejection and vendor minimum service envelopes.
- Declared footprints include physical geometry and service reservations, including rotated reservations. Zone preflight and Apply both reject encroachment.
- Prescribed-flow conservation, actual-ID commercial size rounding, Reynolds/friction/Darcy-Weisbach losses, approximate pump head/power, valve Kv/Cv and unresolved data handling. The reported 0.27400255055565675 m³/s steel case rounds up to NPS 16 at a 3 m/s limit.
- Versioned configuration migration, stable identities, applied-configuration hashes, IFC4 schema/EXPRESS and geometry checks, PCF equipment reporting, source references and schedules.
- Headless equipment matching follows RD calculations; incomplete or disputed catalogue data cannot count as qualified. Independent catalogue updates and stale-search rejection are covered.

## Blocked-design export regression

An intentionally infeasible commercial-size demand still produces an editable applied concept with `exportable=false`. Standard complete ZIP, IFC, graph and native Revit handoff exports reject that design. A diagnostic review ZIP remains available and contains:

- Applied configuration and matching hash, `graph-review-only.json`, geometry findings and preliminary sizing.
- BOM, connection schedule, source register and equipment requirements/candidate status.
- `REVIEW_ONLY.txt` and explicit `REVIEW_ONLY_NOT_CLEARED_FOR_IMPORT` statuses.

The review ZIP contains no IFC, PCF, native Flownex project or native Revit handoff file. A stale hash is rejected. Correcting the sizing input produces a new exportable design and invalidates downloads tied to the old hash. These transitions and archive contents passed the automated regression.

## Browser observations

Historical version 6 behavior, superseded by draft arrangement above: on 13 September, local in-app browser cold startup, Manual-mode Apply and catalogue search completed (100 of 330 component duties had candidates, with unresolved qualification retained). A no-op handle click preserved the applied model. Two consecutive pointer drags moved pod 1 from x=0 to 0.5 m and 1.0 m without another Apply; the final hash prefix was `655852bfcf3e`. Handles and download controls remained usable. An overlapping move was rejected with named equipment/service-access conflicts and retained that design. The full-package action reached “Download prepared from the applied design.” Cancelling another package operation retained the model and download buttons. Browser retry after cancellation was interrupted by a page reload; restored-session export and repeated browser-number round trips passed the Python regressions. The current browser download was not independently inspected on disk.

On 9 September, actual in-app browser module-worker cold startup and Apply completed successfully. A 90-degree plant rotation was accepted by top-view placement preflight and Apply regenerated an exportable model with hash `d71dfbb7b4c4914439e1a44a2ce657bee0cd6b9427dddfd77a299cf65e7fdfcf`. The browser saved `graph-json-bundle.zip`; ZIP integrity passed and its graph carried that exact applied hash. The final frontend build and Pyodide preset checks passed. This record does not imply that every interactive scenario was repeated in both browsers.

Chrome computer-use access was unavailable. Current Chrome interactive startup, cancellation and download checks are **NOT TESTED**.

Earlier deployed version 3 acceptance remains historical: Site source commit `60b0b933512e8c4821835a79b4c6b55118060638` completed a live preliminary design, pod drag and Apply. Saved complete and IFC4 ZIPs carried the matching applied hash. The complete ZIP had 106 files and passed ZIP integrity; its IFC4 had 1,486 elements and 1,514 ports with no IfcOpenShell schema/EXPRESS findings or geometry failures. Those counts describe that older release, not the current air-unit model.

## Remaining application validation and scope

The native add-in now targets **Revit 2027 and .NET 10**. Its source, installation script, mapping metadata and import guide are included. Compilation against the actual Revit 2027 SDK, native MEP connectivity/editability and import into licensed Windows Revit remain **NOT TESTED**.

Official Flownex SE 2025 Release 3 documentation identifies Revit 2026 support. Revit 2027 compatibility of the installed Network Builder remains **UNCONFIRMED**, and an actual Flownex transfer and component-library mapping remain **NOT TESTED**. No native Flownex project is fabricated. IFC4 coordination geometry and connected-port metadata do not establish native editable Revit MEP behavior.

Design actions test three deterministic plant-routing preferences and accept a shorter candidate only after generator checks pass. This is bounded route improvement, not global layout optimization. Sizing remains a prescribed-flow screen rather than a balanced hydraulic or transient network solver.

Air coils share the declared FWS circuit in the current template. Their actual capacity at the entering water/air conditions is unresolved; warm CDU facility water can require a separate colder circuit. Manufacturer hose limits, performance curves, fluid/material compatibility and service requirements require the selected equipment's data. Source guidance does not establish equipment-specific compliance, and the supplied books are not distributed with the site.

## Independent acceptance harness — `validate_design.py`

`python3 -m pytest tests` proves the engine is self-consistent: it calls the
engine's own functions and compares the answers with recorded expectations. It
cannot see a wrong formula that both sides share, a term silently dropped from
an export, or two blocks of one artifact answering the same question
differently.

`validate_design.py` closes that gap. It imports no calculation code. Every
number is re-derived from the graph's raw data — node coordinates, routed
lengths, selected bores, declared fluid properties, declared K values and
pressure allocations — using the relations written out longhand in
`SIZING_BASIS.md`, then compared with what the engine reported.

```sh
python3 validate_design.py --config presets/compact.json --sizing-mode preliminary
python3 validate_design.py --all-presets --plant-type water_cooled
python3 validate_design.py --graph outputs/my-design/graph.json      # audit a delivered package
python3 validate_design.py --config presets/compact.json --sweep     # behavioural probes
python3 validate_design.py --all-presets --json findings.json        # machine-readable
```

Exit status is 1 when any check fails, so it drops into CI unchanged.

| Group | What it re-derives |
| --- | --- |
| `thermal` | heat ledger closes and counts each load once; `Q = P/(ρ·cp·ΔT)` or the L/min-per-kW basis per service; condenser heat `= P·(1+1/COP)`; declared vs implied ΔT |
| `continuity` | signed node balance away from declared boundaries; equipment shares sum back to each circuit total |
| `hydraulic` | `v = 4Q/πD²`, `Re = ρvD/μ`, Colebrook **residual** (not a second call to the same solver), `Δp = f·L/D·ρv²/2`, `Δp = K·ρv²/2`, loss counted once, K referenced to a bore its own flow passes through, velocity limits |
| `pump` | the path is a closed circuit from pump outlet back to its inlet; reported loss equals the sum of its own edges; `H = Δp/ρg`; `P = Q·Δp/η`; margin applied once; closed loops add no static lift; no single fitting dominates the budget |
| `valve` | `Kv = Q[m³/h]·√(SG/Δp[bar])`, `Cv(US) = 1.156·Kv` |
| `catalogue` | selected ID `= (OD − 2·wall)` from the named standard; the recommendation is the smallest bore meeting the limit and no larger; nothing is capped at the biggest size and marked passing |
| `geometry` | routed length equals the node-to-node distance; every straight pipe is axis aligned; losses use routed lengths, not the 1 m placeholder |
| `agreement` | two blocks of one artifact give one answer: `graph.hydraulics` vs `preliminary_sizing`, applied edge bores vs the calculated selection, `BOM.csv` columns vs the sizing that produced them |
| `redundancy` | every requested outage combination is enumerated and connectivity checked; an outage duty is never divided by installed units; an unavailable pod produces a blocking finding |
| `sweep` | doubling load doubles prescribed flow; halving ΔT doubles heat-balance flow; a looser velocity limit never grows a pipe; at a fixed bore head responds to flow, and the friction share of the pump budget is reported |

What it does **not** do: it takes velocity caps, fitting K values, equipment
pressure allocations, fluid properties and efficiencies as declared project
assumptions and only checks that the engine applied them consistently. It does
not balance the network, intersect a pump curve, or certify anything.

## Engine defect fixes — branch `claude/engine-defect-fixes`

Eight defects found by the independent harness and by reading the calculation
path. All eight are closed; the full suite (104 tests, 15 subtests) still passes,
and `validate_design.py` reports 82 of 82 checks passing on every preset.

| # | Defect | Fix | Measured effect |
| --- | --- | --- | --- |
| F1 | A reducer's K was referenced to the smallest bore on **any** edge touching its nodes — at a branch takeoff, a perpendicular leg from a different pipe family. Trunk flow through a branch bore gave 48.5 m/s. | The candidate bores are now restricted to neighbours carrying the same design flow, so a coefficient can only reference a bore its own flow passes through. A reference velocity above twice the family limit is reported as `K_REFERENCE_IMPLAUSIBLE` instead of being produced silently. The neighbour scan is indexed by node, removing a quadratic pass. | `FWS-MAIN-R-002` 176.4 kPa → 0.32 kPa. FWS pump head 45.35 m → 24.66 m; TCS 23.62 m → 21.76 m. |
| F2 | `graph["hydraulics"]["heat_and_flow"]` used hard-coded PG25 properties and always assumed heat balance, ignoring `flow_input_mode` and the entered fluid properties. At `flow_lpm_per_kw = 2.0` it reported 4 988.7 L/min while the pipes were sized for 8 025.6. | `heat_flows` now derives flow from the configuration's own properties and selected basis, and records `tcs_flow_basis` and `implied_tcs_delta_K`. | The two blocks agree to 1e-12 on every preset, and a regression test in `test_pipeline.py` pins them together. |
| F3 | `verify.py` defined `run()` twice; the second shadowed the first, so the decision register, its model checks and its coverage audit never ran, and the evidence tally was collapsed to one count. | One `run()` reporting two layers that are never conflated: the G-series acceptance checks that gate export, and the DEC-series design register reported for review. Register checks measured against the OCP Deschutes module are `NOT_APPLICABLE` unless that profile is selected. | 48 decisions now evaluate: 23 PASS, 8 NOT_APPLICABLE, 4 NOT_EVALUABLE, 0 FAIL, 0 ERROR. Evidence reports 40 FOUND, 0 NOT_FOUND. |
| F3a | `tcs_loop_within_available_dp` read `hydraulics["scenarios"]`, which no live path writes, and raised `KeyError`. The design had no loop-pressure acceptance check anywhere. | Reads the preliminary pump screens. | Restored: 32.2 psi measured against 80 psi available. |
| F3b | `parallel_cdus_on_common_header` looked for a scenario literally named `all_three_online`; the engine emits `all_online`. | Matches on the scenario's `kind`. | Passes for any CDU count. |
| F3c | `cdu_has_expansion_tank` / `cdu_has_air_separator` counted standalone components only, while the generator declares those provisions inside the CDU assembly. | Counts standalone units plus CDUs declaring the function. | Passes; the declared provision is visible in the measured value. |
| F3d | `seismic_braces_present` failed whenever bracing was switched off. | `NOT_EVALUABLE` when `include_seismic_braces` is false. | A configuration choice is no longer reported as a violation. |
| F4 | `BOM.csv` read `edge["dp_Pa"]` and `edge["K"]`; the live path writes `preliminary_dp_Pa`, and `apply_sizes` zeroes `K` before the coefficients are chosen. Every row exported zero. | The pipeline writes the applied `K`, `K_reference_id_m`, friction factor and regime back onto the edge; the emitter reads `preliminary_dp_Pa`. | 532 edges carry their real coefficient; no priced component exports a zero drop. The harness now builds the actual BOM row rather than guessing the key. |
| F5 | The route optimiser's advertised pump-energy term summed `straight_dp_Pa + fitting_dp_Pa`, fields only the retired path wrote, so it was always exactly zero. | Reads `preliminary_dp_Pa`, and the basis string states that the flows are per-family envelopes, making the term an upper bound useful for comparing two routes of the same design. | 0 W → 115.8 kW dissipation, 715 853 NPV on the compact water-cooled preset. |
| F6 | `cws_static_lift_m` defaults to `0.0` and the guard tested `is None`, so an open tower circuit with no lift reported a complete duty. | Zero is treated as unassigned on an open circuit. | CWS pumps report `INCOMPLETE_LOWER_BOUND` until a lift and nozzle pressure are entered. |
| F7 | `sizing_mode="heat_balance"` was reachable from the CLI and JSON import and built a design with no pressure, pump or valve results at all. | Rejected at validation with a message naming the replacement; `Config.from_dict` migrates existing files to `preliminary`. | The mode cannot produce a stripped design any more. |
| F8 | `report.py` was unreachable and raised `KeyError` if called. `hydraulics.analyze / size_graph / longest_path / loss / friction / FLUIDS / scenario_flow`, `topology.generate / Builder.route / racks / rack / distribution / collectors / cdu_assembly / cdu / collector` were all dead — and were the reason F2, F4 and F5 read fields the live path had stopped writing. | Deleted. `sync-engine.py` now also removes browser copies of engine modules that no longer exist upstream, and warns instead of failing when `node_modules` is absent. | `hydraulics.py` 241 → 102 lines; one implementation per question. |

### Knowing what to validate

`validate_design.py --design-space` inventories the configurable choices by
studio section: 2 204 496 combinations of the choice lists, 144 473 849 856 once
the installation and routing toggles are counted, with every numeric input
moving continuously on top of that.

Five of those axes change geometry or the calculation path rather than moving a
number — `layout_style`, `return_topology`, `cdu_placement`, `plant_type` and
`sizing_mode` — which is 108 distinct designs. `validate_design.py --matrix`
builds and checks all of them. The remaining axes move numbers the checks
already re-derive from first principles, so a passing matrix plus the
first-principles checks covers the space without enumerating it.
