@echo off
rem ============================================================
rem  Build the Setup.exe of the apps for the LIVE licence server
rem  (https://license.karnexgroup.com, AWS).
rem
rem    deploy\build-setup-live.bat           menu
rem    deploy\build-setup-live.bat all       every app
rem    deploy\build-setup-live.bat KSTACK    one app
rem
rem  The live database is private, so this PC does not connect to it: each apps
rem  licensing.dat (server address + API client) is issued ON THE SERVER with
rem  scripts.issue_app_config and saved into the apps folder first. The apps must
rem  trust the servers signing key (scripts.set_app_public_key) - build-setup checks it.
rem ============================================================
setlocal
if "%KLC_LIVE_URL%"=="" set "KLC_LIVE_URL=https://license.karnexgroup.com/api/v1"
set "KLC_SERVER_URL=%KLC_LIVE_URL%"
set "KLC_SKIP_CONFIGURE=1"
call "%~dp0..\build-setup.bat" %*
endlocal
