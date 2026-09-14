# Liquid Cooling RD Studio

Parameter-driven reference design for chiller plant → facility water → CDU → aggregate direct-to-chip racks, with CRAH/wall-unit air loads and piping.

The shared Python graph drives the browser plan/3D model, preliminary sizing, equipment requirements, IFC4, PCF and native Revit handoff source. The equipment finder remains headless and reads its independently maintained catalogue only after RD calculates requirements.

## Start the studio

Use Node.js 22.13 or newer and Python 3.12 or newer. From this repository:

```sh
cd rd-studio
npm ci
python3 scripts/sync-engine.py
npm run dev
```

Open the local address printed by the development server. Choose a starting reference, tune inputs, then click **Apply design**. Pending changes do not replace the applied model or its download identity.

In **Plan → Arrange zones**, select a pod, network zone or plant and move, rotate or flip it. Overlap checks run before staging; Apply reroutes and checks the pipes. **Piping → Preliminary** calculates and rounds commercial sizes. **Design actions → Try shorter plant routes** compares checked alternatives without a language model.

## Use the CLI

```sh
cd liquid_cooling_generator
python3 run.py --config presets/compact.json --out outputs/my-design
```

## Validate changes

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
node scripts/test-agent.mjs
node scripts/test-finder.mjs
node scripts/test-engine.mjs
npm exec tsc -- --noEmit
npm run build
```

## Guides and scope

- [Review repairs and known limits](liquid_cooling_generator/CODE_REVIEW_2026-09-09.md)
- [Revit 2027 Windows setup and import](liquid_cooling_generator/revit/README.md)
- [Sizing basis and formulas](liquid_cooling_generator/SIZING_BASIS.md)
- [Headless finder architecture](rd-studio/HEADLESS_FINDER.md)
- [Validation record and the independent acceptance harness](liquid_cooling_generator/VALIDATION.md)
- [Adding a reference design](liquid_cooling_generator/references/PRESET_AUTHORING.md)

This is a concept-layout generator with prescribed-flow pressure estimates. It does not solve hydraulic balance or certify a design. Air coils initially share FWS; warm CDU water may require a separate colder air-cooling loop. Vendor operating-point data remains subject to qualification.

Revit 2027/.NET 10 add-in source is included. Compilation and native import must be tested on Windows. Flownex SE 2025 Release 3 documents Revit 2026 support; Revit 2027 Network Builder compatibility is unconfirmed. IFC4 is coordination geometry, not proof of native Revit MEP editability. No fabricated Flownex project is included.

The supplied source books and full extracted reference documents are excluded. Short indicative source extracts and the source register preserve provenance without claiming standards certification. The Sites hosting manifest retains this project's existing binding; credentials and runtime secrets are not included.
