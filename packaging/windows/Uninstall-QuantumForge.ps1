# Conservative uninstaller for the per-user Windows installation.
[CmdletBinding()]
param([switch]$Yes, [switch]$Purge)
$ErrorActionPreference = "Stop"
$AppHome = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$InstallRoot = (Resolve-Path (Join-Path $AppHome "..\..")).Path
$Receipt = Join-Path $AppHome "INSTALL_RECEIPT"
if (-not (Test-Path $Receipt) -or -not (Test-Path (Join-Path $InstallRoot "versions"))) {
    throw "This does not look like an installer-managed QuantumForge installation."
}
if ($InstallRoot -eq $env:USERPROFILE -or $InstallRoot -eq $env:LOCALAPPDATA) {
    throw "Unsafe installation root; refusing removal."
}
if ($Purge) {
    Write-Warning "-Purge permanently deletes $HOME\.quantumforge, including projects and settings."
}
if (-not $Yes -or $Purge) {
    $Answer = Read-Host "Uninstall QuantumForge from $InstallRoot? [y/N]"
    if ($Answer -notmatch '^[Yy]$') { Write-Host "Uninstall cancelled."; exit 0 }
}
$CommandDir = Join-Path $InstallRoot "bin"
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
$Parts = @($UserPath -split ';' | Where-Object { $_ -and $_ -ne $CommandDir })
[Environment]::SetEnvironmentVariable("Path", ($Parts -join ';'), "User")
if (Test-Path (Join-Path $CommandDir "quantumforge.cmd")) {
    Remove-Item -LiteralPath (Join-Path $CommandDir "quantumforge.cmd") -Force
}
Remove-Item -LiteralPath $InstallRoot -Recurse -Force
if ($Purge) {
    $Data = Join-Path $HOME ".quantumforge"
    if (Test-Path $Data) { Remove-Item -LiteralPath $Data -Recurse -Force }
    Write-Host "QuantumForge and its user data were removed."
} else {
    Write-Host "QuantumForge was removed. Research data remains in $HOME\.quantumforge"
}
