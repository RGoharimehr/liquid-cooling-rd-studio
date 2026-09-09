# Import an RD design into Revit 2027

The add-in source targets **Revit 2027 and .NET 10**. Build and import still need to be tested on your Windows Revit workstation; this Mac cannot validate native Revit or Flownex behavior. The add-in creates reference MEP families and pipes, not vendor-qualified equipment.

## 1. Export from RD Studio

1. Apply your parameters. Resolve the listed geometry and commercial-size findings.
2. Choose **Download package** or **Revit** and extract the entire ZIP on Windows, for example into `C:\RD\MyDesign`.
3. Keep `revit_handoff.json`, `revit_pipe_catalogue.csv` and the `revit` folder together. A diagnostic concept ZIP is for troubleshooting and cannot be imported as a checked network.

For a quick coordination view only, use the IFC4 download and Revit's **Open → IFC** or **Link IFC** workflow. That is separate from the native MEP import below.

## 2. Install the add-in once

On the Windows machine with full Revit 2027 installed:

1. Install the **.NET 10 SDK** from [Microsoft](https://dotnet.microsoft.com/download/dotnet/10.0). The runtime alone cannot compile the add-in.
2. Close Revit. Open PowerShell in the extracted `revit` folder.
3. Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

If Revit is installed elsewhere, pass `-RevitInstallDir "D:\Autodesk\Revit 2027"`.
The script builds against your installed Revit API and installs for your Windows user under `%APPDATA%\Autodesk\Revit\Addins\2027`. It stops if the SDK/API is missing or the build fails. No Autodesk DLLs are distributed with RD.

## 3. Prepare a Revit project

1. Start Revit 2027 and create a fresh project from a mechanical/plumbing template.
2. Ensure the project has a level named **Level 1**, or put your level's exact name in `revit/import-settings.json` under `LevelName`.
3. In **Manage → MEP Settings → Mechanical Settings → Pipe Settings → Segments and Sizes**, prepare pipe segments with the nominal sizes and exact inside/outside diameters in `revit_pipe_catalogue.csv`. Duplicate a native pipe type for each material and assign the correct segment in its routing preferences.
4. Edit `PipeTypesByMaterial` in `revit/import-settings.json` to the exact pipe-type names in this project. Example:

```json
"PipeTypesByMaterial": {
  "stainless_sch10": "RD Stainless 10S",
  "carbon_steel_sch40": "RD Steel Sch40",
  "copper_type_l": "RD Copper Type L"
}
```

5. Set `MechanicalEquipmentTemplate` to an installed **unhosted Metric Mechanical Equipment.rft** template. Localized installations use different paths. Install Revit family-template content if it is missing.

A matching nominal label alone is insufficient: the add-in checks actual pipe bore and outside diameter against RD.

## 4. Import and check the result

1. Choose **Add-Ins → External Tools → Import RD Studio reference design**.
2. Select `revit_handoff.json` from the extracted package.
3. Read the completion dialog and `revit_import_result.json` beside that file. It records native element IDs, checked joints, configuration hash and errors.
4. Open a 3D view. Inspect a CDU's four connectors, the independent TCS pods, air coils, plant pumps and (for a water-cooled plant) the condenser loop. Open a generated family to inspect/edit its reference geometry and connectors.
5. Save the RVT under a new name. Importing again creates another network; use Undo or a fresh project to replace a trial.

On a connection, size, orientation or family failure the import transaction rolls back. Fix the first named issue and retry; do not loosen tolerances to conceal a wrong pipe segment or fitting.

| Message | What to do |
|---|---|
| Required native PipeType not found | Set the exact project pipe-type name in `PipeTypesByMaterial`. |
| Template not found | Set the actual installed unhosted `.rft` path. |
| Inside/outside diameter mismatch | Update the pipe segment from `revit_pipe_catalogue.csv`. |
| Unsupported kind or connector mismatch | Keep the report and component ID; that mapping requires correction before import. |
| Geometry blocking findings | Return to RD, resolve the listed conflicts and export a new applied package. |

## 5. Transfer to Flownex only after version compatibility is confirmed

The official [Flownex SE 2025 Release 3 announcement](https://flownex.com/news/flownex-se-2025-release-3/) documents **Revit 2026** support. It does not establish Revit 2027 support. Confirm that your installed Network Builder explicitly supports Revit 2027, or obtain a supported release from Flownex. This add-in does not perform that transfer.

Use `flownex_mapping.json` as a mapping checklist, not an executable Network Builder settings file. Map pumps, aggregate rack/air-coil loads, chillers and each CDU fluid side to actual installed Flownex library components. Preserve FWS, CWS and TCS-Pxx separation. Compare counts, coordinates, bores and the connection schedule, then save the native project through Flownex. No renamed JSON `.fnm` is supplied.

Record Revit/Flownex builds, applied hash, import report, mapping exceptions and operator/date for both air-cooled and water-cooled representative designs before claiming end-to-end transfer validation.

Revit runtime basis: [Autodesk Revit 2027 .NET 10 migration](https://help.autodesk.com/cloudhelp/2027/ENU/Revit-WhatsNew/files/GUID-8D7A4715-EAF8-4BD1-BE78-061F900D0BCE.htm).
