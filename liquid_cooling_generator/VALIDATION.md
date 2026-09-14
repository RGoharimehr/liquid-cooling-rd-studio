# Validation record — 13 September 2026

The current engine suite passed **106 Python tests and 12 subtests**, including the zone-editing, worker-session recovery and Manual-mode equipment-matching repairs. The command was `.venv-ifc/bin/python -m pytest -q` from the engine directory, with pytest and IfcOpenShell available.

Current zone-interaction, finder transport/cancellation, and 12 design-action JavaScript tests passed; TypeScript and the production build passed. All three shipped presets passed Pyodide generation and export checks with 1,586, 2,877 and 2,256 components. After the browser exposed a numeric JSON hash mismatch, the shared hash was normalized across Python/browser number representations. The final full suite passed 105 tests and 12 subtests; its one legacy test fixture still used the former hash algorithm. After updating that fixture, all 11 equipment-requirement tests passed. No engine assertion remains failing.

## Current repair regressions

- A no-op zone click preserves automatic placement arrays and the applied configuration hash.
- Consecutive zone moves regenerate and apply without a separate Apply call, and the resulting design remains exportable.
- Placement rejection, a generation exception, or blocking routed geometry restores the prior successful engine session and its exports.
- A cancelled worker can restore the applied configuration and its matching equipment report. A mismatched restoration hash is rejected before session mutation.
- Manual sizing calculates duties using retained commercial bores, without modifying the selected dimensions. Equipment requirements and candidate qualification retain manual velocity-limit warnings and reject inconsistent bore metadata.

The interface also keeps zone handles mounted during checks and provides Discard pending changes, Undo zone move and restoration of the last valid design. The in-app browser checks below exercise actual pointer events and the module worker.

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

On 13 September, local in-app browser cold startup, Manual-mode Apply and catalogue search completed (100 of 330 component duties had candidates, with unresolved qualification retained). A no-op handle click preserved the applied model. Two consecutive pointer drags moved pod 1 from x=0 to 0.5 m and 1.0 m without another Apply; the final hash prefix was `655852bfcf3e`. Handles and download controls remained usable. An overlapping move was rejected with named equipment/service-access conflicts and retained that design. The full-package action reached “Download prepared from the applied design.” Cancelling another package operation retained the model and download buttons. Browser retry after cancellation was interrupted by a page reload; restored-session export and repeated browser-number round trips passed the Python regressions. The current browser download was not independently inspected on disk.

On 9 September, actual in-app browser module-worker cold startup and Apply completed successfully. A 90-degree plant rotation was accepted by top-view placement preflight and Apply regenerated an exportable model with hash `d71dfbb7b4c4914439e1a44a2ce657bee0cd6b9427dddfd77a299cf65e7fdfcf`. The browser saved `graph-json-bundle.zip`; ZIP integrity passed and its graph carried that exact applied hash. The final frontend build and Pyodide preset checks passed. This record does not imply that every interactive scenario was repeated in both browsers.

Chrome computer-use access was unavailable. Current Chrome interactive startup, cancellation and download checks are **NOT TESTED**.

Earlier deployed version 3 acceptance remains historical: Site source commit `60b0b933512e8c4821835a79b4c6b55118060638` completed a live preliminary design, pod drag and Apply. Saved complete and IFC4 ZIPs carried the matching applied hash. The complete ZIP had 106 files and passed ZIP integrity; its IFC4 had 1,486 elements and 1,514 ports with no IfcOpenShell schema/EXPRESS findings or geometry failures. Those counts describe that older release, not the current air-unit model.

## Remaining application validation and scope

The native add-in now targets **Revit 2027 and .NET 10**. Its source, installation script, mapping metadata and import guide are included. Compilation against the actual Revit 2027 SDK, native MEP connectivity/editability and import into licensed Windows Revit remain **NOT TESTED**.

Official Flownex SE 2025 Release 3 documentation identifies Revit 2026 support. Revit 2027 compatibility of the installed Network Builder remains **UNCONFIRMED**, and an actual Flownex transfer and component-library mapping remain **NOT TESTED**. No native Flownex project is fabricated. IFC4 coordination geometry and connected-port metadata do not establish native editable Revit MEP behavior.

Design actions test three deterministic plant-routing preferences and accept a shorter candidate only after generator checks pass. This is bounded route improvement, not global layout optimization. Sizing remains a prescribed-flow screen rather than a balanced hydraulic or transient network solver.

Air coils share the declared FWS circuit in the current template. Their actual capacity at the entering water/air conditions is unresolved; warm CDU facility water can require a separate colder circuit. Manufacturer hose limits, performance curves, fluid/material compatibility and service requirements require the selected equipment's data. Source guidance does not establish equipment-specific compliance, and the supplied books are not distributed with the site.
