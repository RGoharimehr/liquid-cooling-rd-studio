RD owns the design and its calculations. The equipment finder is a headless tool
invoked after RD has calculated duties for the applied design. Preliminary mode
rounds each pipe family up through its standard dimension catalogue. Manual mode
retains the selected commercial sizes and calculates duties at their actual bores.
The finder never recalculates required flow,
pipe size, pump duty, working-pressure requirements or valve Kv/Cv.

The published finder database is read at each equipment search from:
https://raw.githubusercontent.com/RGoharimehr/DATA-CENTER-EQUIPMENT-FINDER/main/src/datacenter_equipment_finder/data/equipment_catalog.csv

The finder maintainer can publish new or corrected rows there independently.
RD needs no rebuild, import or catalogue-management action for compatible data
updates. Apply in either Manual or Preliminary mode searches automatically when
the applied requirements are ready; Refresh equipment
matches repeats the tool call for the same applied design. This reads the finder's
published CSV, not an unpublished local SQLite change. Publish the CSV through the
finder's own data workflow when that database changes.

Only tool code is bundled, pinned at finder commit
c2180b8a37b1ce711c963e5422b59ac8e4f7d219. The CSV, SQLite database and vendor PDFs
are not bundled. No credentials or local finder server are needed. The module
worker fetches the current CSV with no-store and a bounded size/time allowance,
validates its schema, and calls the Python selector. No design data is sent to
GitHub, and RD has no catalogue-write capability. A future incompatible schema or
new controlled category needs a deliberate tool-code contract update.

The RD contract records component and port IDs, independent fluid circuits,
standard nominal NPS separately from actual pipe bore, flow/thermal duties,
throttling coefficients, temperatures and pressure requirements. Per-circuit
minimum equipment pressure-rating inputs default to zero (unassigned). Enter a
project pressure envelope including fill/static/shutoff/transient conditions;
routed pressure loss is not a working-pressure rating. The finder compares this
RD-supplied requirement with published values where applicable.

The adapter filters functional role, nominal connection size, specified material
and fluid before limiting candidates. It retains incomplete evidence as tentative
and excludes disputed entries. Balancing duties do not match shutoff-only records.
Multi-circuit CDU/chiller records remain capacity shortlists until vendor profiles
establish performance and separate port/circuit conditions. It records no automatic
part decision and never changes geometry to make a catalogue entry fit.

Manual sizing does not suppress equipment suggestions. RD supplies calculated
heat and flow duties, rough routed pressure losses, pump duty and required valve
Kv/Cv using the retained commercial bores. If a retained bore exceeds the declared
velocity limit, the affected requirement and candidates carry that limitation;
finding a candidate does not clear the sizing warning. Missing vendor evidence
remains unresolved in both modes.

Equipment lookup is separate from generation and export. Network errors,
cancellation and malformed catalogue data retain the applied design and make the
current equipment search unavailable. Exports remain available subject to RD's
existing geometry gates. A running catalogue search does not lock zone editing or
downloads; a new design operation can interrupt the search. If the worker was
cancelled, the next operation restores the applied configuration and matching
cached equipment report before continuing. Every bundle includes equipment_requirements.json and
equipment_candidates.json, tied to the applied config and catalogue SHA-256.
The local assistant receives these results as read-only context. The page's
rd_get_equipment_matches tool exposes the same applied requirements and candidates.

Tests cover independent database updates, NPS/DN handling, filtering before top-N,
missing numeric evidence, incompatible roles/fluids, invalid data, hash binding,
failed-search export availability, restoration after worker cancellation, retained
manual bores and tentative candidate status for manual velocity exceedances.
