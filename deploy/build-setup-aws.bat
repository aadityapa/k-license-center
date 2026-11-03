@echo off
rem ============================================================
rem  Build the Setup.exe of an app for the licence server on AWS.
rem
rem    deploy\build-setup-aws.bat               menu
rem    deploy\build-setup-aws.bat KSTACK        one app / all
rem
rem  Settings: deploy\build-aws.cfg (copy build-aws.cfg.example).
rem  Opens an SSH tunnel to the server's database (never exposed to the internet),
rem  connects the app (API client + licensing.dat with the https address), checks
rem  the app trusts the server's signing key, then builds Setup.exe as usual.
rem ============================================================
setlocal
cd /d "%~dp0.."
if not exist "deploy\build-aws.cfg" (echo Copy deploy\build-aws.cfg.example to deploy\build-aws.cfg and fill it in. & pause & exit /b 1)
for /f "usebackq eol=# tokens=1,* delims==" %%a in ("deploy\build-aws.cfg") do set "%%a=%%b"
if "%DOMAIN%"=="" (echo DOMAIN missing in build-aws.cfg & pause & exit /b 1)
where ssh >nul 2>nul || (echo OpenSSH client not found: Settings - Apps - Optional features - OpenSSH Client. & pause & exit /b 1)

echo Opening SSH tunnel to %SSH_USER%@%SSH_HOST% ...
start "klicense-db-tunnel" /min ssh -i "%SSH_KEY%" -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=accept-new -N -L 15432:127.0.0.1:5432 %SSH_USER%@%SSH_HOST%
timeout /t 5 /nobreak >nul

set "DB_HOST=127.0.0.1"
set "DB_PORT=15432"
set "DB_NAME=klicense"
set "DB_USER=klicense"
set "DATABASE_URL="
set "KLC_SERVER_URL=https://%DOMAIN%/api/v1"
call build-setup.bat %*

taskkill /fi "WINDOWTITLE eq klicense-db-tunnel*" >nul 2>nul
endlocal
