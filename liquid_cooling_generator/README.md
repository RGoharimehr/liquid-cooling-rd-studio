# Liquid-cooling reference-design generator

A parameter-driven reference layout for chiller plant → facility water → four-port CDU → aggregate direct-to-chip rack connections. Compute and air-cooled network racks are separate. Independent cooling pods, equipment zones and routing geometry share one versioned graph across the browser, CLI and exports.

## Use

The web studio uses **Apply design**. Pending edits do not change the applied model or its downloads. Generation runs in a module worker with bundled Pyodide; cancellation stops the worker. Every download is a ZIP containing the requested format, applied configuration, BOM, connection schedule, source register and diagnostics.

In **Plan**, enable **Arrange zones**. Drag a cooling pod, network-rack zone or plant; arrow keys move a focused zone in 0.25 m steps. Apply regenerates the connections and checks geometry. Use Rotate 90°, Flip X and Flip Y for the selected zone. Equipment and service-space overlaps are checked before a zone change is staged. Zone origins and orthogonal rotations are also available in the parameter groups. Footprint width/depth constrain world-coordinate physical extents; zero disables the boundary. Routing uses deterministic service lanes, not a globally optimal route search. Some moves require more overhead clearance or a different placement and are rejected with diagnostics.

For the CLI, run `python3 run.py --config presets/compact.json --out outputs/new-design`. The legacy `config.json` preserves an open facility-water boundary until a plant is selected. JSON imports migrate to schema2. Existing output files are staged before replacement; failed export cannot overwrite a previous successful package. `--allow-nonconforming` explicitly permits a draft despite geometry findings; the browser blocks normal import downloads for those designs but offers a labelled diagnostic concept ZIP so editing can continue.

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

Manual mode retains entered catalogue dimensions. **Preliminary** mode assigns liquid heat flow using either L/min per liquid kW or heat balance with entered density, specific heat and temperature rise. It rounds uniform pipe families upward through the selected catalogue using actual internal diameter and velocity limits. Geometry is then checked with those diameters.

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
