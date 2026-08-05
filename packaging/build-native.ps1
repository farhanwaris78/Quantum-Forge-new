# Build a self-contained jpackage app image or installer on Windows.
[CmdletBinding()]
param([ValidateSet("app-image", "msi", "exe")][string]$Type = "app-image")
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
if (-not (Get-Command jpackage.exe -ErrorAction SilentlyContinue)) { throw "jpackage from JDK 17+ is required." }
[xml]$Pom = Get-Content "pom.xml"
$Version = $Pom.project.version
& mvn.cmd -B -ntp -DskipTests clean verify
if ($LASTEXITCODE -ne 0) { throw "Maven build failed with status $LASTEXITCODE" }
$InputDir = Join-Path $Root "target\jpackage-input"
$FxPath = Join-Path $Root "target\jpackage-javafx"
$Dest = Join-Path $Root "target\native"
Remove-Item $InputDir, $FxPath -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $InputDir, $FxPath, $Dest | Out-Null
Copy-Item "target\quantumforge.jar" $InputDir
Get-ChildItem "target\dependency\*.jar" | ForEach-Object {
    if ($_.Name -like "javafx-*") {
        if ($_.Name -like "*-win.jar") { Copy-Item $_.FullName $FxPath }
    } else { Copy-Item $_.FullName $InputDir }
}
if (-not (Get-ChildItem "$FxPath\javafx-graphics-*.jar" -ErrorAction SilentlyContinue)) {
    throw "Platform JavaFX modules are missing."
}
$Arguments = @(
    "--type", $Type,
    "--dest", $Dest,
    "--name", "QuantumForge",
    "--app-version", $Version,
    "--vendor", "QuantumForge Development Team",
    "--description", "Quantum ESPRESSO workflow editor and results viewer",
    "--copyright", "Copyright (C) 2025-2026 QuantumForge Development Team",
    "--license-file", (Join-Path $Root "LICENSE"),
    "--input", $InputDir,
    "--main-jar", "quantumforge.jar",
    "--main-class", "quantumforge.launcher.QuantumForgeLauncher",
    "--module-path", $FxPath,
    "--add-modules", "javafx.controls,javafx.fxml,javafx.web,javafx.swing,java.logging,jdk.crypto.ec",
    "--java-options", "-Dfile.encoding=UTF-8",
    "--icon", (Join-Path $Root "bin\quantumforge.ico")
)
if ($Type -ne "app-image") {
    $Arguments += @("--win-menu", "--win-shortcut", "--win-dir-chooser", "--win-per-user-install")
}
& jpackage.exe @Arguments
if ($LASTEXITCODE -ne 0) { throw "jpackage failed with status $LASTEXITCODE" }
Get-ChildItem -LiteralPath $Dest
