# SHA-256-verified updater for installer-managed Windows bundles.
[CmdletBinding()]
param([switch]$Yes)
$ErrorActionPreference = "Stop"
$AppHome = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$InstallRoot = (Resolve-Path (Join-Path $AppHome "..\..")).Path
$CurrentVersion = (Get-Content (Join-Path $AppHome "VERSION") -Raw).Trim()
$Repository = if ($env:QUANTUMFORGE_UPDATE_REPOSITORY) {
    $env:QUANTUMFORGE_UPDATE_REPOSITORY
} else { "farhanwaris78/Quantum-Forge" }
$Arch = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
switch ($Arch) {
    "X64" { $Machine = "x64" }
    "Arm64" { $Machine = "arm64" }
    default { throw "Unsupported Windows architecture: $Arch" }
}
$Headers = @{ "User-Agent" = "QuantumForge-Updater/$CurrentVersion" }
$Release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repository/releases/latest" -Headers $Headers
if ($Release.draft -or $Release.prerelease) { throw "Latest GitHub release is not stable." }
$Pattern = "^QuantumForge-([0-9][0-9A-Za-z.\-]*)-windows-$Machine\.zip$"
$ArchiveAsset = $Release.assets | Where-Object { $_.name -match $Pattern } | Select-Object -First 1
$ChecksumAsset = $Release.assets | Where-Object { $_.name -eq "SHA256SUMS" } | Select-Object -First 1
if (-not $ArchiveAsset -or -not $ChecksumAsset) {
    throw "Release has no verified archive for windows-$Machine."
}
$LatestVersion = [regex]::Match($ArchiveAsset.name, $Pattern).Groups[1].Value
if ($LatestVersion -eq $CurrentVersion) {
    Write-Host "QuantumForge $CurrentVersion is already current."
    exit 0
}
if (-not $Yes) {
    $Answer = Read-Host "Update QuantumForge $CurrentVersion -> $LatestVersion? [y/N]"
    if ($Answer -notmatch '^[Yy]$') { Write-Host "Update cancelled."; exit 0 }
}

$Temp = Join-Path ([IO.Path]::GetTempPath()) ("quantumforge-update-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $Temp | Out-Null
try {
    $Archive = Join-Path $Temp $ArchiveAsset.name
    $Checksums = Join-Path $Temp "SHA256SUMS"
    Invoke-WebRequest -Uri $ArchiveAsset.browser_download_url -Headers $Headers -OutFile $Archive
    Invoke-WebRequest -Uri $ChecksumAsset.browser_download_url -Headers $Headers -OutFile $Checksums
    $Line = Get-Content $Checksums | Where-Object { $_ -match ("\s\*?" + [regex]::Escape($ArchiveAsset.name) + "$") } | Select-Object -First 1
    if (-not $Line -or $Line -notmatch '^([0-9a-fA-F]{64})\s') { throw "Release checksum is missing or malformed." }
    $Expected = $Matches[1].ToLowerInvariant()
    $Actual = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Actual -ne $Expected) { throw "SHA-256 verification FAILED; nothing was installed." }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Extract = Join-Path $Temp "extracted"
    New-Item -ItemType Directory -Path $Extract | Out-Null
    $ExtractRoot = [IO.Path]::GetFullPath($Extract + [IO.Path]::DirectorySeparatorChar)
    $Zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        foreach ($Entry in $Zip.Entries) {
            $Destination = [IO.Path]::GetFullPath((Join-Path $Extract $Entry.FullName))
            if (-not $Destination.StartsWith($ExtractRoot, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Unsafe path in release archive: $($Entry.FullName)"
            }
        }
    } finally { $Zip.Dispose() }
    [IO.Compression.ZipFile]::ExtractToDirectory($Archive, $Extract)
    $Installer = Get-ChildItem -LiteralPath $Extract -Recurse -Filter "Install-QuantumForge.ps1" |
        Where-Object { $_.FullName -match '[\\/]management[\\/]Install-QuantumForge\.ps1$' } |
        Select-Object -First 1
    if (-not $Installer) { throw "Release archive has no installer." }
    & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $Installer.FullName -Prefix $InstallRoot -Yes
    if ($LASTEXITCODE -ne 0) { throw "New release installer failed with status $LASTEXITCODE." }
    Write-Host "Update complete. Existing $HOME\.quantumforge research data was preserved."
}
finally {
    if (Test-Path $Temp) { Remove-Item -LiteralPath $Temp -Recurse -Force }
}
