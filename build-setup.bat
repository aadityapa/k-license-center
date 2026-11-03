@echo off
rem ============================================================
rem  Build the Setup.exe of an application listed in apps.json
rem
rem    build-setup.bat               choose from a menu
rem    build-setup.bat VEHICLESIM    one app (its productCode)
rem    build-setup.bat all           every app
rem
rem  Output: in the app's own folder (apps.json "setupOutput", e.g. VehSim installer\dist,
rem          KStack Installer\Output)   Log: build-setup.log
rem  Needs: start.bat run once (Python environment + database), .NET 8 SDK,
rem  Inno Setup (offered automatically if missing).
rem ============================================================
setlocal
cd /d "%~dp0"
set "VPY=%~dp0backend\.venv\Scripts\python.exe"
if not exist "%VPY%" (echo The server's Python environment is missing. Run start.bat once first. & pause & exit /b 1)
pushd backend
"%VPY%" -m scripts.build_setup %*
popd
echo.
pause
endlocal
