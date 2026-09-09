# RD code review and repairs — 9 September 2026

The RD generator owns geometry, duties, commercial size selection and preliminary loss estimates. The headless finder reads independently published catalogue data and returns candidates; it cannot alter RD duty or silently choose a part.

| Reported issue | Repair and scope |
|---|---|
| Redundant or ineffective inputs | Added one semantic contract per exposed parameter with its effect and combined dependencies. Legacy pressure/flow knobs remain hidden. Nominal sizes are selected from the chosen material catalogue. Reference presets load geometry; reference checks only change diagnostics; rack arrangement, CDU gallery and return-pipe order have separate descriptions in one Arrangement group. |
| Hidden inactive placement | Custom CDU Y is only active for a custom gallery. Global placement is shown against a fixed world-origin marker; plan and export use the same coordinates. |
| Vendor clearance | Physical service envelopes use the larger of project allowance and declared vendor minimum. Obstructing equipment is reported; zero vendor data remains unassigned. |
| Pod count errors | UI count edits repair incompatible arrays and spare counts, with a visible explanation. Balance pod assignments restores automatic grouping. Explicit imported arrays still receive validation rather than silently being discarded. |
| Pipe catalogue failure | Steel Schedule 40 dimensions include verified larger commercial sizes. The reported 0.27400255 m³/s rounds to NPS16 at3m/s. Beyond-catalogue requirements show required ID, largest supported capacity and remedies. They retain a concept preview and diagnostic export. |
| Blocked export prevents work | Valid geometry keeps normal exports. Infeasible concepts can download a labelled review-only graph/config/diagnostics ZIP and continue editing. It does not pretend to be a checked native MEP import. |
| Rotation, mirroring and overlaps | Pod, network and plant transforms retain port orientation. Plan controls preflight equipment, service and footprint overlap before staging; Apply performs full pipe checks. Rotation/mirror routes use sufficient collector lead length. |
| Air heat missing | Residual compute + actual network + additional room heat appears once in plant load, separately from CDU liquid heat. Two-port CRAH/wall-coil envelopes have explicit parallel FWS piping. Per-unit count, extra heat, branch size and pressure budget are tunable. |
| AI only comments | A no-model design action builds and compares three plant corridor alternatives. Only a shorter candidate passing generator checks is offered for staging. The optional local model remains a parameter proposal interface and cannot execute arbitrary code. |
| Revit version/guide | Native source targets Revit2027/.NET10 and validates that target. A step-by-step Windows build/install/import guide and pipe-dimension checklist ship in each handoff. Actual Windows import and Flownex transfer are still untested. |

## Measured examples

Compact:32 compute racks,8 network racks,3 CDUs. Plant heat4,384kW =4,012.8kW liquid +371.2kW air. Manual and preliminary configurations pass the active geometry checks.

Water-cooled compact route action: plant pipe346.26m →324.42m (21.84m saved), elbows56 →55, zero blocking checks in the accepted trial. This is a bounded corridor search, not a proof of global optimality or hydraulic performance.

Regression coverage includes commercial-size failure, air heat and connectivity, rotation/mirrors, world transforms, vendor service geometry, rejection of overlapping moves, combined control dependencies, stale hashes, headless catalogue updates and export behavior. See tests and the release validation record for exact executed checks.

## Physical and application limits

Air units initially share the declared FWS water supply. A warm-water CDU supply is not automatically suitable for air cooling: actual entering water/air conditions, airflow, coil performance and possibly a separate colder loop remain vendor/project design work. The interface and exports explicitly preserve this unresolved condition.

The finder offers evidence-qualified shortlists only. Generic multi-circuit CDU/chiller catalogue fields do not establish each side's flow, coolant, pressure, port size or operating-point capacity.

The official Flownex SE2025 Release3 notice establishes Revit2026 support. Revit2027 Network Builder compatibility must be confirmed with Flownex before transfer. No Windows execution or end-to-end transfer result is claimed from this macOS environment.
