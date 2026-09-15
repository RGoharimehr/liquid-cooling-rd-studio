# RD Studio

A local-in-browser tuning and geometry workspace for liquid-cooled data-center reference designs. The UI uses React, Three.js and Pyodide. Every design parameter has a source/assumption note. Generation uses the same pure-Python engine as the CLI in the adjacent `liquid_cooling_generator` directory.

- `npm ci` then `npm run dev` start the local interface.
- `npm run dev:restart` stops whatever is already running and starts again; `npm run dev:stop` also clears the stale lockfile a crashed server leaves behind.
- `npm run sync` refreshes the shared engine assets and initial model after engine changes. It runs automatically before `npm run build`.
- `npm run doctor` reports what is broken in this checkout and names the fix. `npm run doctor -- --url <origin>` does the same for a deployment, which is how you tell a stale deployment apart from a code fault.
- `npm run verify` runs the doctor, the type check and every test the CI studio job runs, including all three presets through the real browser Python runtime.

Select a reference, tune parameters, and arrange the plan before clicking **Apply design**. In Plan, enable Arrange zones; select a cooling pod, network-rack zone or plant, then drag, rotate or flip it as many times as needed. These edits update a lightweight draft only. Equipment moves immediately; faint piping remains the last applied route. **Undo arrangement change** reverses one draft action. Placement conflicts are shown while drafting; Apply checks the complete equipment arrangement, reroutes piping and enables normal exports only when required checks pass. Other equipment/count/coordinate-frame changes must be applied before arranging the regenerated zones. Discard pending changes restores applied inputs.

The zone toolbar occupies its own area above the SVG, so the canvas cannot intercept its controls. Imports without schema_version preserve an explicit air_cooled or water_cooled plant; a legacy file that omits plant_type retains its boundary-only scope.

CDU outage connectivity uses the active pipeline. The redundancy input is the number of simultaneous outages across all independent pods; all combinations are checked. Offline CDUs and their isolation components are removed from those cases, heat is allocated within each pod, and a pod with no surviving CDU reports unserved heat and blocks normal export. This is not capacity, pressure or operational-redundancy verification.

Piping → Preliminary rounds pipe families through the commercial-size catalogue. Manual retains the selected commercial dimensions while still calculating flow, rough pressure losses, pump duty and valve Kv/Cv for equipment matching. Velocity exceedances remain warnings and candidate limitations; the finder does not resize pipes. Sizing estimates contains flow, fluid and pressure-budget inputs. Every export bundle contains applied inputs and diagnostics. Cancelling an operation retains the applied model; the next operation restores its worker session automatically. See VALIDATION.md for completed checks and target-application limits. The interface supports 128 compute racks per generation. No backend fluid-network solver, customer account integration or external API key is required.

RD113 R0 is explicitly a spatial interpretation of the user's attached reference, not an exact electrical/hydraulic replica. See the source notes and generated engineering review before downstream import.

**Design actions → Try shorter plant routes** runs a bounded route search without a language model and offers only checked improvements. Optional Ollama on your computer can propose parameter changes. A separate generator check validates each candidate before it can be staged. See [LOCAL_AGENT.md](LOCAL_AGENT.md) for setup and the proposal workflow.

Air-unit envelopes and FWS piping carry the residual compute, network and additional room heat into chiller sizing. Shared warm FWS does not establish air-coil capacity; operating temperatures require qualification. Revit handoff source targets **Revit 2027 / .NET 10**. See [the Windows guide](public/engine/revit/README.md); native Windows validation remains pending.

The headless finder searches the current published catalogue after RD computes duties, using rounded commercial sizes in Preliminary mode or retained commercial sizes in Manual mode. Its database can update independently. See [HEADLESS_FINDER.md](HEADLESS_FINDER.md).
