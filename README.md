# Liquid Cooling RD Studio

Parameter-driven reference design for chiller plant → facility water → CDU →
aggregate direct-to-chip racks, with CRAH/wall-unit air loads and piping.

One shared Python graph drives the browser plan and 3D model, preliminary
sizing, equipment requirements, IFC4, PCF and the native Revit handoff source.
The equipment finder stays headless and reads its independently maintained
catalogue only after RD has calculated the requirements.

## Start the studio

Use Node.js 22.13 or newer and Python 3.12 or newer. From this repository:

```sh
cd rd-studio
npm ci
npm run sync          # copy the engine into the browser bundle
npm run dev
```

On Windows, stop a running dev server before `npm ci`: it holds native addons
open, and the install deletes `node_modules` before reinstalling, so it fails
with `EPERM` on a locked `.node` file and leaves the tree half-deleted. `npm run
dev:stop` first, and `npm run doctor` will tell you if a previous install was
interrupted this way.

Open the address the development server prints. Choose a starting reference,
tune the inputs, then click **Apply design**. Pending changes never replace the
applied model or its download identity.

In **Plan → Arrange zones**, select a pod, network zone or plant and move,
rotate or flip it. Overlap checks run before staging; Apply reroutes and checks
the pipes. **Piping → Preliminary** calculates and rounds commercial sizes.
**Design actions → Try shorter plant routes** compares checked alternatives
without a language model.

### Restart, stop and diagnose

```sh
npm run dev:restart   # stop whatever is running, then start fresh
npm run dev:stop      # stop it, or clear a stale lock so dev can start again
npm run sync          # refresh the browser engine copy
npm run doctor        # what is wrong with this checkout
npm run verify        # doctor, types, and every test the CI studio job runs
```

`vinext dev` holds a lockfile and refuses to start while another server owns it.
A closed terminal or a crash leaves that lock behind with nothing listening, so
`dev:stop` clears it as well as stopping a live server.

`npm run doctor` covers the faults that break the studio silently: engine
modules absent from the browser manifest, manifest entries with no file behind
them, entries carrying Windows path separators, browser copies that drifted
from the engine sources, an incomplete Pyodide runtime, and a dev server or
stale lock holding the port. Each finding names the command that clears it.
`npm run sync` fixes most, and is wired as `prebuild` so a build cannot ship a
bundle that is behind the engine sources.

### When the studio says the engine is incomplete

> This deployment is serving an incomplete design engine
> (ModuleNotFoundError: No module named 'datacenter_equipment_finder')

The browser assembles the engine from the file list in `/engine/manifest.json`
and nothing else. A module is therefore missing from the studio whenever it is
missing from that list **as served**, which can be true while the repository is
complete. Ask the deployment directly:

```sh
npm run doctor -- --url https://your-studio-host
```

It compares the served manifest against this checkout and fetches files from the
host, so it separates the three faults that reach you as the same sentence:

| What the doctor finds | What it means |
| --- | --- |
| The served manifest is short | The deployment is stale or incomplete. Redeploy from a checkout where `npm run doctor` passes. |
| A file the manifest promised returns 404, or an HTML page | The host is not serving that path. |
| Manifest entries contain `\` | The bundle was built by a sync on Windows. Re-sync with the current `sync-engine.py` and redeploy. |

A local pass with a `--url` failure means the code is fine and the deployment
is not.

### The equipment finder

The selection core is vendored into
`liquid_cooling_generator/datacenter_equipment_finder/` from
[DATA-CENTER-EQUIPMENT-FINDER](https://github.com/RGoharimehr/DATA-CENTER-EQUIPMENT-FINDER)
at the revision recorded in
[UPSTREAM.md](liquid_cooling_generator/datacenter_equipment_finder/UPSTREAM.md),
so the studio does not need that repository at load time. It does need it at
search time: the catalogue is fetched from raw GitHub content on each search and
is never bundled, so an equipment search requires outbound access to it.

## Use the CLI

```sh
cd liquid_cooling_generator
python3 run.py --config presets/compact.json --out outputs/my-design
```

## Validate changes

Every command below runs on each push and pull request via
[`.github/workflows/checks.yml`](.github/workflows/checks.yml).

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
cd liquid_cooling_generator
python3 -m pytest tests -q
python3 validate_design.py --all-presets
python3 validate_design.py --design-space    # what can vary, by studio section
python3 validate_design.py --config presets/compact.json --matrix   # all 108 geometry variants
python3 benchmark.py --all                   # against published reference designs
cd ../rd-studio
npm run verify        # doctor, tsc, agent/finder/plan-editor tests, browser worker
npm run build
```

## Guides and scope

- [Review repairs and known limits](liquid_cooling_generator/CODE_REVIEW_2026-09-09.md)
- [Revit 2027 Windows setup and import](liquid_cooling_generator/revit/README.md)
- [Sizing basis and formulas](liquid_cooling_generator/SIZING_BASIS.md)
- [Headless finder architecture](rd-studio/HEADLESS_FINDER.md)
- [Validation record and the independent acceptance harness](liquid_cooling_generator/VALIDATION.md)
- [Adding a reference design](liquid_cooling_generator/references/PRESET_AUTHORING.md)

This is a concept-layout generator with prescribed-flow pressure estimates. It
does not solve hydraulic balance and it does not certify a design. Air coils
initially share FWS; warm CDU water may require a separate, colder air-cooling
loop. Vendor operating-point data remains subject to qualification.

Revit 2027 / .NET 10 add-in source is included; compilation and native import
still have to be tested on Windows. Flownex SE 2025 Release 3 documents Revit
2026 support, and Revit 2027 Network Builder compatibility is unconfirmed. IFC4
is coordination geometry, not proof of native Revit MEP editability. No
fabricated Flownex project is included.

The supplied source books and the full extracted reference documents are
excluded. Short indicative extracts and the source register preserve provenance
without claiming standards certification. The Sites hosting manifest keeps this
project's existing binding; credentials and runtime secrets are not included.
