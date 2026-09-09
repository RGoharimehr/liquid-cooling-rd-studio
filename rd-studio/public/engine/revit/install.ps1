param([string]$RevitInstallDir = 'C:\Program Files\Autodesk\Revit 2027')
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Install this add-in on the Windows Revit 2027 workstation.' }
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) { throw 'Install the .NET 10 SDK (10.0.100 or a compatible servicing release), then retry. The runtime alone cannot build an add-in.' }
if (-not ((dotnet --list-sdks) -match '^10\.')) { throw 'The .NET 10 SDK is required for Revit 2027.' }
if (-not (Test-Path (Join-Path $RevitInstallDir 'RevitAPI.dll'))) { throw "Revit 2027 API assemblies were not found in $RevitInstallDir." }
if ((Get-Item (Join-Path $RevitInstallDir 'RevitAPI.dll')).VersionInfo.FileMajorPart -ne 27) { throw 'RevitInstallDir must contain Revit 2027 API assemblies (major version 27).' }
Push-Location $PSScriptRoot
try {
    dotnet build ReferenceDesignImport.csproj -c Release -p:RevitInstallDir="$RevitInstallDir"
    if ($LASTEXITCODE -ne 0) { throw 'Build failed; no add-in installed.' }
    $rdDestination = Join-Path $env:APPDATA 'Autodesk\Revit\Addins\2027\RDStudio'
    New-Item -ItemType Directory -Force $rdDestination | Out-Null
    Copy-Item 'bin\Release\net10.0-windows\*' $rdDestination -Recurse -Force
    $rdAssembly = [System.Security.SecurityElement]::Escape((Join-Path $rdDestination 'ReferenceDesignImport.dll'))
    $rdManifest = @"
<?xml version="1.0" encoding="utf-8"?>
<RevitAddIns><AddIn Type="Command">
<Name>Import RD Studio</Name><Assembly>$rdAssembly</Assembly>
<AddInId>826e31ab-92fb-4bb4-9ed2-d0eef9fa44f6</AddInId>
<FullClassName>LiquidCooling.Revit.ImportCommand</FullClassName>
<Text>Import RD Studio reference design</Text><VendorId>RDST</VendorId>
<VendorDescription>Reference geometry and connected native MEP handoff</VendorDescription>
</AddIn></RevitAddIns>
"@
    Set-Content (Join-Path (Split-Path $rdDestination) 'RDStudio.addin') $rdManifest -Encoding utf8
    Write-Host "Installed for this Windows user: $rdDestination"
    Write-Host 'Restart Revit 2027 and open Add-Ins > External Tools > Import RD Studio reference design.'
} finally { Pop-Location }
