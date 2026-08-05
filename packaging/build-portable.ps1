# Build a Windows portable archive using Maven-resolved JavaFX native libraries.
[CmdletBinding()]
param(
    [ValidateSet("x64", "arm64")][string]$Machine = "x64"
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
[xml]$Pom = Get-Content (Join-Path $Root "pom.xml")
$Version = $Pom.project.version
& mvn.cmd -B -ntp -DskipTests clean verify
if ($LASTEXITCODE -ne 0) { throw "Maven build failed with status $LASTEXITCODE" }
$Name = "QuantumForge-$Version-windows-$Machine"
$Bundle = Join-Path $Root "target\portable\$Name"
if (Test-Path $Bundle) { Remove-Item -LiteralPath $Bundle -Recurse -Force }
@("app", "lib\javafx", "bin", "management", "resources", "docs") | ForEach-Object {
    New-Item -ItemType Directory -Force -Path (Join-Path $Bundle $_) | Out-Null
}
Copy-Item "target\quantumforge.jar" "$Bundle\app\"
$FxJars = @(Get-ChildItem "target\dependency\javafx-*-win.jar")
if (-not $FxJars) { throw "No JavaFX Windows native libraries were resolved." }
$FxJars | Copy-Item -Destination "$Bundle\lib\javafx\"
Get-ChildItem "target\dependency\*.jar" | Where-Object { $_.Name -notlike "javafx-*" } |
    Copy-Item -Destination "$Bundle\lib\"
Copy-Item "packaging\unix\quantumforge" "$Bundle\bin\quantumforge"
Copy-Item "packaging\windows\quantumforge.cmd" "$Bundle\bin\quantumforge.cmd"
Copy-Item "packaging\unix\install.sh" "$Bundle\management\install.sh"
Copy-Item "packaging\unix\update.sh" "$Bundle\management\update.sh"
Copy-Item "packaging\unix\uninstall.sh" "$Bundle\management\uninstall.sh"
Copy-Item "packaging\windows\Install-QuantumForge.ps1" "$Bundle\management\Install-QuantumForge.ps1"
Copy-Item "packaging\windows\Update-QuantumForge.ps1" "$Bundle\management\Update-QuantumForge.ps1"
Copy-Item "packaging\windows\Uninstall-QuantumForge.ps1" "$Bundle\management\Uninstall-QuantumForge.ps1"
Copy-Item "packaging\windows\Install-QuantumForge.ps1" "$Bundle\Install-QuantumForge.ps1"
Copy-Item "packaging\windows\Update-QuantumForge.ps1" "$Bundle\Update-QuantumForge.ps1"
Copy-Item "packaging\windows\Uninstall-QuantumForge.ps1" "$Bundle\Uninstall-QuantumForge.ps1"
Copy-Item "LICENSE", "README.md" "$Bundle\"
@("docs\INSTALLATION.md", "docs\RELEASE_AND_SECURITY.md", "docs\SCIENTIFIC_SOFTWARE_GUIDE.md",
  "docs\CODE_AUDIT.md", "docs\ROADMAP.md",
  "docs\TUTORIAL_INSTALL.md") |
    ForEach-Object {
        if (Test-Path $_) { Copy-Item $_ "$Bundle\docs\" }
    }
Copy-Item "src\quantumforge\app\resource\image\icon_256.png" "$Bundle\resources\quantumforge.png"
Set-Content -LiteralPath "$Bundle\VERSION" -Value $Version -Encoding ASCII
Set-Content -LiteralPath "$Bundle\LAUNCH_COMMAND.txt" -Value "command=quantumforge" -Encoding ASCII
Copy-Item "target\quantumforge-sbom.json" "$Bundle\quantumforge-sbom.cdx.json"
New-Item -ItemType Directory -Force -Path "target\release" | Out-Null
$Archive = Join-Path $Root "target\release\$Name.zip"
if (Test-Path $Archive) { Remove-Item -LiteralPath $Archive -Force }
Compress-Archive -Path $Bundle -DestinationPath $Archive -CompressionLevel Optimal
Write-Output $Archive
