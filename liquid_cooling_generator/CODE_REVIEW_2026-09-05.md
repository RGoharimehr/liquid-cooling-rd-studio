# Code review — current revision, 2026-09-05

Reviewed the current working files after the IFC4, standards, installation and traceability additions. This review does not apply the earlier snapshot's claim that IFC export is missing. Application source was not modified during this review.

## Validation performed

- Existing suite: 10 tests pass, 2 fail. The failures expect three pumps rather than the newly modelled six, and expect 250 kW/rack sizing to raise a catalogue error. These expectations need reconciling with the changed design.
- Fresh CLI run using `.venv-ifc/bin/python`: 660 hydraulic components plus 597 installation attachments; 1,257 IFC elements, 49 type objects and 697 port links. Reopening finds connected hydraulic component groups of 609 and 51 elements.
- All 1,257 IFC geometries tessellate. Basic schema validation passes. Direct IFC4 EXPRESS-rule evaluation nevertheless finds 49 type-property relationship violations.
- Default conformance result: 3 blocking failures and 3 further failed model checks. Process exit status is still zero.
- Additional tests exercised standards overrides, non-N+1 redundancy, failed IFC export into an existing output folder, and corpus identifier generation.
- No Revit or Flownex import round trip was available; opening/tessellating IFC is not proof of native Revit MEP interoperability.

## Findings

### 1. [P1] Several advertised tuning controls do not change the generated model

[standards.py:231](/Users/rgoharim/Documents/New%20project/liquid_cooling_generator/standards.py:231), [topology.py:113](/Users/rgoharim/Documents/New%20project/liquid_cooling_generator/topology.py:113), [placement.py:216](/Users/rgoharim/Documents/New%20project/liquid_cooling_generator/placement.py:216)

The standards profile records overrides, but geometry reads separate `Config` fields and installation code ignores several switches. Independently changing `header_supply_elevation_m` to 3.9, `tcs_main.min_bend_radius_d` to 8, `vent_at_high_point` to false, `support_at_fitting` to false or `tcs_filtration_um` to 10 produces identical node coordinates and component-kind counts. The filter remains hardcoded at 35 micrometres. Resolve a single effective parameter set, use it in construction, and test each advertised control for a corresponding model change or an explicit rejection.

### 2. [P1] IFC type property sets violate an IFC4 EXPRESS rule

[ifc4.py:223](/Users/rgoharim/Documents/New%20project/liquid_cooling_generator/ifc4.py:223)

The shared `pset` helper assigns properties to type objects using `IfcRelDefinesByProperties`. All 49 type definitions violate `IfcRelDefinesByProperties.NoRelatedTypeObject`; their `HasPropertySets` attributes are empty. Assign type properties through `IfcTypeObject.HasPropertySets`, retaining occurrence relationships for occurrence properties. Tessellation and basic attribute validation do not catch this relationship error.

### 3. [P1] Exported fitting solids do not preserve the graph's fitting geometry

[ifc4.py:263](/Users/rgoharim/Documents/New%20project/liquid_cooling_generator/ifc4.py:263), [mesh.py:108](/Users/rgoharim/Documents/New%20project/liquid_cooling_generator/mesh.py:108)

The IFC exporter creates a constant-diameter cylinder between the first two ports for tees, elbows and reducers. `TCS-T-0001` has a branch port outside its body bounds; `TCS-R-0001` has an 8-to-6-inch transition represented as a constant 6-inch tube. OBJ bends are chords, and its tee branch starts at the first endpoint instead of the fitting centre. These are material errors for a rendering/layout tool even when topology metadata remains present. Implement geometry by component kind using centre points and per-port bores.

### 4. [P1] A failed IFC export can receive a connectivity PASS using an old file

[emitters.py:548](/Users/rgoharim/Documents/New%20project/liquid_cooling_generator/emitters.py:548), [run.py:78](/Users/rgoharim/Documents/New%20project/liquid_cooling_generator/run.py:78)

Reproduced by generating the default design, then forcing `emit_ifc` to raise while regenerating a smaller design in the same directory. The manifest says `ifc_file: null`, but `_ifc_networks` reads the previous `network.ifc` and `ifc_network_connectivity` reports PASS with the old [609, 51] component counts. Stage outputs should be transactional or versioned; validate only the file successfully emitted by the current run. Do not claim a current export when the exporter failed.

### 5. [P1] Redundancy values other than one are accepted but not represented by scenarios

[topology.py:263](/Users/rgoharim/Documents/New%20project/liquid_cooling_generator/topology.py:263)

The scenario generator always removes exactly one CDU. With four units and redundancy two, every scenario retains three active units although the duty count is two. The branch result is therefore 1,662.9 L/min while the rated two-duty basis is 2,494.3 L/min. With redundancy zero, single-outage cases are still generated. Enumerate the required outage combinations, or explicitly reject unsupported redundancy values. Keep scenario heat, design flow, equipment rating and loss basis consistent.

### 6. [P1] Blocking conformance failures still return process success

[run.py:96](/Users/rgoharim/Documents/New%20project/liquid_cooling_generator/run.py:96), [run.py:117](/Users/rgoharim/Documents/New%20project/liquid_cooling_generator/run.py:117)

The default run reports three blocking failures—CDU heat capacity and primary/secondary flow—but exits with status 0. Automated generation or downstream import scripts cannot distinguish accepted designs from failed checks. Return a nonzero validation status or provide an explicit draft-export mode that records failures without representing the run as conforming. Review artifacts can still be retained.

### 7. [P2] IFC port directions and named systems do not match the graph

[ifc4.py:313](/Users/rgoharim/Documents/New%20project/liquid_cooling_generator/ifc4.py:313), [ifc4.py:369](/Users/rgoharim/Documents/New%20project/liquid_cooling_generator/ifc4.py:369)

Port direction is assigned by list position rather than incident directed edges. Collecting tees consequently have reversed ports: the default export has 140 tee-port direction disagreements, including 38 SINK–SINK and 38 SOURCE–SOURCE connections. Both named distribution systems have zero component memberships because `IfcRelAssignsToGroup` relationships are missing. Derive directions from graph edges and explicitly assign each service's elements to its system.

### 8. [P2] Regeneration changes every IFC identity

[ifc4.py:77](/Users/rgoharim/Documents/New%20project/liquid_cooling_generator/ifc4.py:77)

Random GUIDs are generated for every export, including unchanged components and ports. Re-exporting an unchanged graph changes every component GUID, undermining correspondence across tuning and downstream reloads. Derive persistent IFC identifiers from stable graph identifiers and an explicit project namespace.

### 9. [P2] Some compliance checks establish less than their names claim

[decisions.py:218](/Users/rgoharim/Documents/New%20project/liquid_cooling_generator/decisions.py:218)

`leak_detection_present` passes because 82 drip trays exist, even though no leak-detector component exists. A tray does not establish detection. `vents_at_all_high_points` only checks that at least one vent exists, not coverage of every required high point. Define the required objects/coverage and compare actual graph placements against them; use NOT_EVALUABLE where detection or coverage has not been modelled.

### 10. [P2] The source-corpus builder does not produce the IDs the verifier looks up

[tools/build_corpus.py:22](/Users/rgoharim/Documents/New%20project/liquid_cooling_generator/tools/build_corpus.py:22), [decisions.py:33](/Users/rgoharim/Documents/New%20project/liquid_cooling_generator/decisions.py:33)

The Deschutes PDF name becomes `OCP_Specification_Deschutes_v1_0`, while the register requests `OCP-Specification-Deschutes_v1_0`. The CloudScale filename similarly expands to a different key than the abbreviated register ID. Existing hand-seeded snippets remain on disk, so rebuilding from full PDFs can leave verification reading the old partial snippets. Introduce explicit document IDs and a file-to-ID mapping. Current evidence is correctly labelled indicative, but the documented upgrade path does not resolve these keys.

### 11. [P2] The authoritative graph is saved before final metadata exists

[run.py:72](/Users/rgoharim/Documents/New%20project/liquid_cooling_generator/run.py:72)

`graph.json` is written before `metadata.emission` and `metadata.verification` are assigned, and is never rewritten. Reopening it loses the very information used to produce the final traceability matrix. Finalise and persist the authoritative graph after attaching the final results, or explicitly separate immutable design data from a linked run-result artifact.

## Remaining limitations from the previous review

- Pressure analysis still runs unconditionally, and temperature/property restrictions still gate geometry generation. A layout-only path remains absent.
- PCF still omits unsupported equipment and is not an end-to-end Flownex import demonstration.
- Previously generated output files are not cleaned transactionally; the stale-IFC reproduction above demonstrates the broader stale-output problem.
- A configurable return-topology choice is still absent. CDU count is now variable, so the old claim that it is fixed at three no longer applies.

## Recommended correction order

First make parameter overrides affect the model and make current-run export validation reliable. Then correct IFC type relationships, fitting geometry, port directions/system assignments and stable IDs. Reconcile redundancy scenarios, implement geometry-only operation and replace superficial conformance counts with checks of the actual model. Update tests to cover the added features and the changed pump/material defaults.
