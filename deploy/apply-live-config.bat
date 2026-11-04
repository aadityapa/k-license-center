@echo off
rem ============================================================
rem  D25: make every copy of every app on this PC use the LIVE licence server.
rem    1. stamp backend\apps-live.txt (issued by scripts.issue_app_config on the server)
rem       into source / installer / bin / publish / installed folders of all apps
rem    2. run the backend tests
rem    3. build all Setup.exe files for the live server
rem    4. commit + push the licence-server code
rem  Log: deploy\apply-live-config.log
rem ============================================================
setlocal
cd /d "%~dp0.."
set "VPY=%~dp0..\backend\.venv\Scripts\python.exe"
set "LOG=%~dp0apply-live-config.log"
echo ==== %date% %time% > "%LOG%"

echo [1/4] stamping the live licensing.dat into every copy ...
pushd backend
"%VPY%" -m scripts.install_app_config apps-live.txt >> "%LOG%" 2>&1 || (echo   FAILED - see %LOG% & popd & goto end)
"%VPY%" -m scripts.install_app_config --check >> "%LOG%" 2>&1 || (echo   some copies still wrong - see %LOG% & popd & goto end)
echo   ok
echo [2/4] backend unit tests (integration tests need a PostgreSQL user with CREATEDB - skipped here) ...
cmd /c "set DB_HOST=127.0.0.1&& set DB_PORT=1&& "%VPY%" -m pytest -q -p no:cacheprovider" >> "%LOG%" 2>&1 && (echo   ok) || (echo   UNIT TESTS FAILED - see %LOG% & popd & goto end)
popd

echo [3/4] building Setup.exe for all apps (a few minutes) ...
set "KLC_SERVER_URL=https://license.karnexgroup.com/api/v1"
set "KLC_SKIP_CONFIGURE=1"
pushd backend
"%VPY%" -m scripts.build_setup all >> "%LOG%" 2>&1 && (echo   ok) || (echo   BUILD FAILED - see build-setup.log)
popd

echo [4/4] git commit + push ...
git add -A >> "%LOG%" 2>&1
git -c core.autocrlf=true commit -m "D25: every app build uses the live server (apps.json serverUrl, install_app_config, configure_apps/build_setup live mode)" >> "%LOG%" 2>&1
git push origin main >> "%LOG%" 2>&1 && (echo   pushed) || (echo   PUSH FAILED - see %LOG%)

:end
echo.
echo Done. Details: %LOG%
pause
endlocal
