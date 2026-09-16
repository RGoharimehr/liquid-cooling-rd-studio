# Liquid-cooling reference-design generator

A parameter-driven reference layout for chiller plant → facility water → four-port CDU → aggregate direct-to-chip rack connections. Compute and air-cooled network racks are separate. Independent cooling pods, equipment zones and routing geometry share one versioned graph across the browser, CLI and exports.

## Use

The web studio uses **Apply design** for typed parameter edits. Pending edits do not change the applied model; normal downloads wait until those edits are applied or discarded. **Discard pending changes** restores the applied inputs. Generation runs in a module worker with bundled Pyodide; cancellation stops the worker and retains the last applied model. The next operation restores its hash-bound worker session automatically. Every download is a ZIP containing the requested format, applied configuration, BOM, connection schedule, source register and diagnostics.

In **Plan**, enable **Arrange zones**. Drag a cooling pod, network-rack zone or plant; arrow keys move a focused zone in 0.25 m steps. Use Rotate 90°, Flip X and Flip Y for the selected zone. All changes accumulate in an editable draft. **Undo arrangement change** reverses one draft action. Equipment previews move immediately while piping remains the last applied route; **Apply design** reroutes and validates the complete draft. Conflicts remain visible and editable until corrected. Footprint width/depth constrain world-coordinate physical extents; zero disables the boundary. Routing uses deterministic service lanes, not a globally optimal route search.

The active network_v2 pipeline enumerates all combinations of the requested simultaneous CDU outages, with closed isolation components, disabled equipment, per-pod surviving units and heat allocation. An unavailable independent pod retains its unserved heat and produces a blocking connectivity finding. N+R is a requested outage scenario, not certified cooling capacity or operating reliability.

For the CLI, run `python3 run.py --config presets/compact.json --out outputs/new-design`. The legacy `config.json` preserves an open facility-water boundary until a plant is selected. JSON imports migrate to schema2. Existing output files are staged before replacement; failed export cannot overwrite a previous successful package. `--allow-nonconforming` explicitly permits a draft despite geometry findings; the browser blocks normal import downloads for those designs but offers a labelled diagnostic concept ZIP so editing can continue.

## Connection points

Every cooling pod and the facility declare where they hand over, and
`metadata.connection_points` records it: the pod's point is the tee at which its
primary flow joins the facility trunk, the facility's point is the interface the
plant connects to, and `assignments` says which facility point each pod takes,
how far away it is and how much flow it brings. A pod takes the nearest declared
point that still has capacity for its whole flow and spills to the next nearest
only when the closest one is full, because a pod has one pair of connection ports
and cannot receive half its duty from somewhere else. One plant can be declared
today, so every pod is assigned to it.

The trunk leaves the hall at whichever end faces the plant rather than always at
the north end, so a pod beside the plant reaches it without first running the
length of the hall.

A pod's collector belongs to the pod and travels with it. Arranging a pod
reroutes one pair of links from the facility trunk to its connection point, at a
single elevation. It used to leave the collector behind and run a separate
elevated lane from every CDU, stacked 0.8 m apart to miss each other: on RD113
the eighth lane sat at 11.76 m, through a 6.5 m ceiling, so an eight-CDU pod
could not be arranged at all. The corridor the links use is one pipe wide, so
arranging a second pod at the same time, or arranging one past the TCS spine,
raises its links over the pod headers and needs the ceiling to allow it. A water-cooled plant keeps the north interface: its condenser
banks, towers and pumps occupy the south service corridor, and its own FWS ends
face west and north, so the run would have to cross that circuit.

## Pipe sizing

*Manual* keeps one bore per pipe family, exactly as entered. *Preliminary* sizes
each **run** for what that run carries. A run is a maximal stretch that has to
share a bore, broken only at a reducer or a tee, because those are the two
fittings that can hold two: a concentric or eccentric reducer between two runs,
and an ASME B16.9 reducing tee, designated run x run x branch. Everything else -
pipe, elbow, valve, strainer, quick disconnect, flexible connector - is one bore
end to end, so an elbow never reduces.

A section's duty is the carried flow with the redundancy uplift, because an
outage moves a neighbouring unit's duty onto the header it shares, capped at its
own circuit total. A section with no carried flow - a standby leg behind a shut
isolation valve - takes the circuit total, because it takes full duty the moment
that valve opens. Branch levels keep the duty envelopes they already had.

On RD113 that turns four bores into eight and puts the reduction where it
belongs:

| | before | after |
| --- | --- | --- |
| distinct bores applied | 4 | 8 |
| NPS 16 pipe | 180 edges | 132 edges |
| reducing tees | 0 | 20 |

`Bore changes stay inside a reducing fitting` is the check that keeps it honest:
two bores on one component are ordinary on a reducer or a tee and wrong on a
pipe, an elbow or a valve. The pairing check cannot see it, because it only
compares across a joint.

The run table is in `metadata.run_sizing`. No listed reducing tee is confirmed to
exist in the chosen run x run x branch combination; that is a procurement check.

## CDU placement

`cdu_placement` decides where a pod's CDUs stand. `central_gallery` stands each
pod's CDUs alongside the rows that pod feeds - its own rows, whichever way round
the pods were assigned to them - and `end_gallery` stands them all off the end of
the hall, which is a legitimate choice and the reason this reports rather than
blocks. Every design reports, per pod, how far its gallery stands clear of the
rows it serves, under *Cooling pod N CDUs stand with the rows they serve*.

The CDU collector runs on its own lane west of the row distribution spine. It
used to share that spine, which silently required the gallery to stand clear of
the rows in Y: centring it on them, which is what `central_gallery` is for, put
the collector tees on the row takeoffs and blocked the design.

On RD113 the two are worth 36.6 m of pipe and 5 m of mean rack-to-CDU reach:

| | rack to its CDU, mean | routed pipe |
| --- | --- | --- |
| `end_gallery` | 17.1 m / 20.6 m | 689.3 m |
| `central_gallery` | 12.4 m / 12.4 m | 652.7 m |

## Route optimisation

Routing normally uses deterministic service lanes. `route_optimizer` replaces the
fixed lanes on the plant transport connections - the facility-water tie-ins and the
condenser-water legs - with a search over a lane graph built from the obstacles
already in the model. Everything else is unchanged: the optimizer supplies
waypoints, `route_path` still builds every pipe, elbow, node, tag and edge, and
`geometry_checks.diagnose` remains the acceptance gate.

A link is only rerouted when the search beats the lane it would otherwise use,
measured with the same length-and-bend cost, so enabling it cannot lengthen a run.
A route that will not place legally is reported and the fixed lane is kept.
In-hall TCS distribution is not touched; it already routes at the rectilinear
bound. Compare the two with:

```bash
python3 tools/compare_routing.py --config presets/compact.json
```

`route_cost.py` prices a routed graph - pipe by nominal size, fittings, hangers
and the present value of pump energy - and reports routed length against the
rectilinear bound per run, so a result states its own optimality gap. **The rate
table is an assumption.** This repository holds no pipe, fitting or labour cost
data; the defaults are order-of-magnitude placeholders. Ratios are meaningful,
currency figures are not, until project rates replace them.

This is a route search, not a hydraulic solver, a clash-resolution tool or a
support design. It does not move equipment, change topology, resize pipe or
establish that a layout is constructible.

## Preliminary sizing

**Manual** mode retains entered commercial dimensions and evaluates declared flow, rough pressure loss, pump head/power and valve Kv/Cv at those actual bores. Equipment suggestions work in Manual mode; velocity exceedances remain visible as tentative candidate limitations and do not silently resize pipes. Both modes derive liquid flow using either L/min per liquid kW or heat balance with entered density, specific heat and temperature rise. **Preliminary** mode additionally rounds uniform pipe families upward through the selected catalogue using internal diameter and velocity limits, then checks geometry with those diameters.

The pressure screen uses routed lengths, Reynolds number, Darcy–Weisbach/Colebrook, declared fitting K and allocated equipment/valve pressure drops. It reports approximate pump head and electrical input using an explicit overall efficiency. It does not solve pressure balancing, pump-curve intersections, operating redundancy, NPSH, cavitation, controls or transients. Open tower lift/nozzle pressure and chiller COP are separate inputs. Valve Kv/Cv are required values at an allocated pressure drop, not catalogue selections. See `SIZING_BASIS.md` for primary sources, assumptions and formulas.

## Handoff

- `network.ifc`: IFC4 coordination geometry with physical ports and distinct FWS/CWS/TCS-Pxx systems. IFC alone is not native editable Revit MEP.
- `revit_handoff.json`, `revit/`: native Revit2027/.NET10 add-in source, configuration and installation instructions. Requires building and validating in the target Windows application.
- `network_*.pcf`: generic PCF with explicit equipment placeholders and omission reports. Resolve downstream library mappings.
- `flownex_mapping.json`: functions requiring mapping in Flownex SE2025 Release3's official Revit Network Builder. No native Flownex project is fabricated.
- `graph.json`, schedules, diagnostics, configuration hash and source register preserve the applied design.

The generator excludes server internals, refrigerant circuits and hydraulic/transient network solving. Vendor dimensions, bend ratings, capacity curves, fluid/material compatibility and jurisdictional requirements remain qualifications. ASHRAE/OCP guidance and reference examples are identified separately from project assumptions. No source books are bundled.

## Verification

Run `python3 -m unittest discover -s tests -v`. If IfcOpenShell and pytest are installed, the suite also checks IFC schema, EXPRESS rules, geometry and connected port identity. Browser checks cover real worker startup, edits, apply, cancellation, validation errors and download generation. See `VALIDATION.md` for executed and pending target checks.
