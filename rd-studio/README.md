# RD Studio

A local, in-browser tuning and geometry workspace for liquid-cooled data-center
reference designs. The UI is React, Three.js and Pyodide. Every design parameter
carries a source or assumption note. Generation runs the same pure-Python engine
as the CLI in the adjacent `liquid_cooling_generator` directory — there is no
second implementation.

## Commands

| Command | What it does |
| --- | --- |
| `npm ci` then `npm run dev` | Install and start the local interface. |
| `npm run dev:restart` | Stop whatever is already running, then start again. |
| `npm run dev:stop` | Stop the server, or clear the stale lockfile a crashed one leaves behind. |
| `npm run sync` | Refresh the browser engine assets and initial model after engine changes. Runs automatically before `npm run build`. |
| `npm run doctor` | Report what is broken in this checkout, naming the fix for each finding. |
| `npm run doctor -- --url <origin>` | Ask the same questions of a deployment, to tell a stale deployment apart from a code fault. |
| `npm run verify` | Doctor, type check, and every test the CI studio job runs, including all three presets through the real browser Python runtime. |

`vinext dev` holds a lockfile and refuses to start while another server owns it.
A closed terminal or a crash leaves that lock behind with nothing listening, so
`dev:stop` clears it as well as stopping a live server.

## Troubleshooting

**"This deployment is serving an incomplete design engine."**
The browser assembles the engine from the file list in `/engine/manifest.json`
and nothing else, so a module is missing from the studio whenever it is missing
from that list *as served*. Run `npm run doctor` here, then
`npm run doctor -- --url <origin>` against the deployment. A local pass with a
`--url` failure means the code is fine and the deployment is stale, incomplete,
or was built on a platform whose path separators the list cannot carry.

**A stale browser engine copy.** `npm run sync` rewrites it. The committed copy
must match the engine sources, and CI fails if it does not.

**`npm ci` fails with `EPERM: operation not permitted, unlink ...node`
(Windows).** A running dev server holds native addons open, and `npm ci`
deletes `node_modules` before reinstalling, so the unlink fails partway through
and leaves the tree half-deleted. What follows names the wrong thing: `tsc`
reports itself uninstalled and `npm run sync` says the Pyodide runtime is
absent. Stop the server first, then reinstall:

```sh
npm run dev:stop
npm ci
npm run doctor
```

`npm run doctor` reports a half-deleted `node_modules` directly, so you do not
have to infer it from the next command's error.

## Using the studio

Select a reference, tune parameters, and arrange the plan before clicking
**Apply design**.

In **Plan**, enable **Arrange zones**, then select a cooling pod, network-rack
zone or plant and drag, rotate or flip it as many times as needed. These edits
update a lightweight draft only: equipment moves immediately while faint piping
remains the last applied route. **Undo arrangement change** reverses one draft
action, and **Discard pending changes** restores the applied inputs. Placement
conflicts appear while drafting; **Apply design** checks the complete
arrangement, reroutes piping, and enables normal exports only when the required
checks pass. Equipment-count and coordinate-frame changes must be applied before
the regenerated zones can be arranged.

The zone toolbar occupies its own area above the SVG, so the canvas cannot
intercept its controls.

## What the engine reports

**Pipe sizing.** *Piping → Preliminary* rounds pipe families through the
commercial-size catalogue. *Manual* retains the commercial dimensions you chose
while still calculating flow, rough pressure losses, pump duty and valve Kv/Cv
for equipment matching. Velocity exceedances stay warnings and candidate
limitations; the finder never resizes pipes. *Sizing estimates* holds the flow,
fluid and pressure-budget inputs.

**Connection points.** Each cooling pod and the facility declare where they hand
over. A pod's collector travels with the pod, so arranging one reroutes a single
pair of links to its connection point rather than one elevated lane per CDU. The plan marks every declared point and names, on hover, the flow it
carries, the facility point it is assigned to and the distance to it. A pod takes
the nearest facility point with capacity for its whole flow. One plant can be
declared today, so every pod is assigned to it.

**CDU placement.** *Central gallery* stands each pod's CDUs alongside the rows
that pod feeds; *End gallery* stands them off the end of the hall. Every design
reports how far each pod's gallery stands clear of its own rows, so the choice
has a number rather than a look at the plan. It reports and never blocks.

**CDU outage connectivity** uses the active pipeline. The redundancy input is
the number of simultaneous outages across all independent pods, and every
combination is checked. Offline CDUs and their isolation components are removed
from those cases, heat is allocated within each pod, and a pod left with no
surviving CDU reports unserved heat and blocks normal export. This is not
capacity, pressure or operational-redundancy verification.

**Air loads.** Air-unit envelopes and FWS piping carry the residual compute,
network and additional room heat into chiller sizing. Shared warm FWS does not
establish air-coil capacity; operating temperatures require qualification.

**Equipment.** The headless finder searches the current published catalogue
after RD computes duties, using rounded commercial sizes in Preliminary mode or
your retained commercial sizes in Manual mode. Its database updates
independently of this repository. See [HEADLESS_FINDER.md](HEADLESS_FINDER.md).

**Design actions → Try shorter plant routes** runs a bounded route search with
no language model and offers only checked improvements. Optional Ollama running
on your own computer can propose parameter changes; a separate generator check
validates each candidate before it can be staged. See
[LOCAL_AGENT.md](LOCAL_AGENT.md).

## Scope and limits

- Every export bundle contains the applied inputs and the diagnostics.
- Cancelling an operation keeps the applied model; the next operation restores
  its worker session automatically.
- The interface supports 128 compute racks per generation.
- No backend fluid-network solver, account integration or external API key is
  required.
- Imports without `schema_version` preserve an explicit `air_cooled` or
  `water_cooled` plant; a legacy file that omits `plant_type` keeps its
  boundary-only scope.
- RD113 R0 is a spatial interpretation of the attached reference, not an exact
  electrical or hydraulic replica. Read the source notes and the generated
  engineering review before any downstream import.
- Revit handoff source targets **Revit 2027 / .NET 10**. See
  [the Windows guide](public/engine/revit/README.md); native Windows validation
  is still pending.
- [VALIDATION.md](VALIDATION.md) records the completed checks and the
  target-application limits.
