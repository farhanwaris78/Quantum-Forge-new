# Atomic per-user installer for a downloaded QuantumForge Windows bundle.
[CmdletBinding()]
param(
    [string]$Prefix = (Join-Path $env:LOCALAPPDATA "QuantumForge"),
    [switch]$Yes
)
$ErrorActionPreference = "Stop"
if (Test-Path (Join-Path $PSScriptRoot "VERSION")) {
    $SourceRoot = (Resolve-Path $PSScriptRoot).Path # top-level convenience copy
} else {
    $SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
$Version = (Get-Content (Join-Path $SourceRoot "VERSION") -Raw).Trim()
if ($Version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+([.\-][0-9A-Za-z.\-]+)?$') {
    throw "Invalid bundle version: $Version"
}
if (-not (Test-Path (Join-Path $SourceRoot "app\quantumforge.jar"))) {
    throw "Bundle is incomplete; app\quantumforge.jar is missing."
}
$Links = Get-ChildItem -LiteralPath $SourceRoot -Recurse -Force | Where-Object {
    $_.Attributes -band [IO.FileAttributes]::ReparsePoint
}
if ($Links) { throw "Bundle contains an unexpected reparse point; refusing to install." }

$Versions = Join-Path $Prefix "versions"
$Target = Join-Path $Versions $Version
$Stage = Join-Path $Versions (".$Version.staging." + $PID)
$Backup = Join-Path $Versions (".$Version.backup." + $PID)
$CommandDir = Join-Path $Prefix "bin"
New-Item -ItemType Directory -Force -Path $Versions, $CommandDir | Out-Null
try {
    New-Item -ItemType Directory -Path $Stage | Out-Null
    Get-ChildItem -LiteralPath $SourceRoot -Force | Copy-Item -Destination $Stage -Recurse -Force
    @("version=$Version", "installed_at=$([DateTime]::UtcNow.ToString('o'))", "bin_dir=$CommandDir") |
        Set-Content -LiteralPath (Join-Path $Stage "INSTALL_RECEIPT") -Encoding UTF8
    if (Test-Path $Target) { Move-Item -LiteralPath $Target -Destination $Backup }
    Move-Item -LiteralPath $Stage -Destination $Target
    if (Test-Path $Backup) { Remove-Item -LiteralPath $Backup -Recurse -Force }

    $CurrentTemp = Join-Path $Prefix ("current.txt." + $PID)
    Set-Content -LiteralPath $CurrentTemp -Value $Version -NoNewline -Encoding ASCII
    Move-Item -LiteralPath $CurrentTemp -Destination (Join-Path $Prefix "current.txt") -Force

    $WrapperTemp = Join-Path $CommandDir ("quantumforge.cmd." + $PID)
    @"
@echo off
setlocal
set /p QF_VERSION=<"$Prefix\current.txt"
call "$Prefix\versions\%QF_VERSION%\bin\quantumforge.cmd" %*
exit /b %ERRORLEVEL%
"@ | Set-Content -LiteralPath $WrapperTemp -Encoding ASCII
    Move-Item -LiteralPath $WrapperTemp -Destination (Join-Path $CommandDir "quantumforge.cmd") -Force

    # Add only our dedicated command directory to the per-user PATH, once.
    $UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $Parts = @($UserPath -split ';' | Where-Object { $_ })
    if ($Parts -notcontains $CommandDir) {
        [Environment]::SetEnvironmentVariable("Path", (($Parts + $CommandDir) -join ';'), "User")
    }
    Write-Host "QuantumForge $Version installed safely."
    Write-Host "Open a new Command Prompt or PowerShell, then run: quantumforge --doctor"
    Write-Host "Review integration maturity with: quantumforge --capabilities"
    Write-Host "Existing $HOME\.quantumforge research data was not modified."
}
catch {
    if (Test-Path $Stage) { Remove-Item -LiteralPath $Stage -Recurse -Force }
    if ((Test-Path $Backup) -and -not (Test-Path $Target)) {
        Move-Item -LiteralPath $Backup -Destination $Target
    }
    throw
}
