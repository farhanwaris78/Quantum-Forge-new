@echo off
setlocal EnableExtensions
set "APP_HOME=%~dp0.."
for %%I in ("%APP_HOME%") do set "APP_HOME=%%~fI"

if /I "%~1"=="--update" (
  shift
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%APP_HOME%\management\Update-QuantumForge.ps1" %*
  exit /b %ERRORLEVEL%
)
if /I "%~1"=="--uninstall" (
  shift
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%APP_HOME%\management\Uninstall-QuantumForge.ps1" %*
  exit /b %ERRORLEVEL%
)

if defined QUANTUMFORGE_JAVA_HOME (
  set "JAVA=%QUANTUMFORGE_JAVA_HOME%\bin\java.exe"
) else if defined JAVA_HOME (
  set "JAVA=%JAVA_HOME%\bin\java.exe"
) else (
  set "JAVA=java.exe"
)

if not exist "%APP_HOME%\app\quantumforge.jar" (
  echo QuantumForge installation is incomplete: app\quantumforge.jar is missing. 1>&2
  exit /b 3
)

pushd "%APP_HOME%"
"%JAVA%" -Dfile.encoding=UTF-8 %QUANTUMFORGE_JAVA_OPTS% --module-path "%APP_HOME%\lib\javafx" --add-modules javafx.controls,javafx.fxml,javafx.web,javafx.swing -cp "%APP_HOME%\app\quantumforge.jar;%APP_HOME%\lib\*" quantumforge.launcher.QuantumForgeLauncher %*
set "RESULT=%ERRORLEVEL%"
popd
if "%RESULT%"=="9009" echo Java was not found. Install 64-bit Java 17+ and run quantumforge --doctor. 1>&2
exit /b %RESULT%
