# RD Studio

A local-in-browser tuning and geometry workspace for liquid-cooled data-center reference designs. The UI uses React, Three.js and Pyodide. Every design parameter has a source/assumption note. Generation uses the same pure-Python engine as the CLI in the adjacent `liquid_cooling_generator` directory.

- `npm ci` and `npm run dev` start the local interface.
- `python3 scripts/sync-engine.py` refreshes the shared engine assets and initial model after engine changes.
- `node scripts/test-engine.mjs` verifies all three presets and their IFC4/PCF/BOM/ZIP outputs inside the browser Python runtime.
- `npm exec tsc -- --noEmit` and `npm run build` validate the web application.

Select a reference, tune parameters, click Apply design, inspect 3D/plan geometry and service zones, then download. In Plan, enable Arrange zones to move, rotate or flip complete cooling pods, the network-rack zone or the plant. Zone moves check physical and service-space overlap before staging. Piping → Preliminary applies catalogue sizing; Sizing estimates contains flow, fluid and pressure-budget inputs. Every export bundle contains applied inputs and diagnostics. See VALIDATION.md for completed checks and target-application limits. The interface supports 128 compute racks per generation. No backend fluid-network solver, customer account integration or external API key is required.

RD113 R0 is explicitly a spatial interpretation of the user's attached reference, not an exact electrical/hydraulic replica. See the source notes and generated engineering review before downstream import.

**Design actions → Try shorter plant routes** runs a bounded route search without a language model and offers only checked improvements. Optional Ollama on your computer can propose parameter changes. A separate generator check validates each candidate before it can be staged. See [LOCAL_AGENT.md](LOCAL_AGENT.md) for setup and the proposal workflow.

Air-unit envelopes and FWS piping carry the residual compute, network and additional room heat into chiller sizing. Shared warm FWS does not establish air-coil capacity; operating temperatures require qualification. Revit handoff source targets **Revit 2027 / .NET 10**. See [the Windows guide](public/engine/revit/README.md); native Windows validation remains pending.

The headless finder searches the current published catalogue after RD computes duties and rounds commercial sizes. Its database can update independently. See [HEADLESS_FINDER.md](HEADLESS_FINDER.md).
