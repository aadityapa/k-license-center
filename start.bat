@echo off
rem ============================================================
rem  K License Center - start everything
rem
rem    start.bat
rem
rem    1. installs what is missing (first run only):
rem         backend\.venv   Python packages of the licence server (FastAPI)
rem         frontend        React + Tailwind portal packages (npm)
rem    2. creates / upgrades the database tables (PostgreSQL)
rem    3. connects every app listed in apps.json (product, API client,
rem       licensing.dat in the app's source and builds)
rem    4. starts the licence server (port 3001) and the portal (port 5173)
rem    5. opens the portal - login admin / Pass@100%%
rem
rem  Needs: Python 3.10+ (python.org, tick "Add to PATH"), Node.js 20+,
rem         PostgreSQL 14+ with the klicense role and database (database\postgres\README.md).
rem  Demo data: load database\postgres\demo\demo_data.sql into a test database.
rem  Setup.exe for an app:  build-setup.bat
rem ============================================================
setlocal
cd /d "%~dp0"

set "PYEXE="
where py >nul 2>nul && (py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PYEXE=py -3")
if not defined PYEXE (
  where python >nul 2>nul && (python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PYEXE=python")
)
if not defined PYEXE (echo Python 3.10 or newer not found. Install it from python.org ^(tick "Add python.exe to PATH"^) first. & pause & exit /b 1)
where node >nul 2>nul || (echo Node.js not found. Install Node 20 or newer from nodejs.org first. & pause & exit /b 1)

if not exist "backend\.env" copy "backend\.env.example" "backend\.env" >nul

set "VPY=%~dp0backend\.venv\Scripts\python.exe"
if not exist "%VPY%" (
  echo Creating the server's Python environment - first run only...
  %PYEXE% -m venv "backend\.venv" || (echo Could not create backend\.venv & pause & exit /b 1)
)
rem (Re)install the server packages when requirements.txt changed.
fc /b "backend\requirements.txt" "backend\.venv\requirements.installed" >nul 2>nul
if errorlevel 1 (
  echo Installing server components...
  "%VPY%" -m pip install --disable-pip-version-check -q --upgrade pip
  "%VPY%" -m pip install --disable-pip-version-check -q -r "backend\requirements.txt" || (echo Installing the server packages failed - see above. & pause & exit /b 1)
  copy /y "backend\requirements.txt" "backend\.venv\requirements.installed" >nul
)
if not exist "frontend\node_modules\tailwindcss" (
  echo Installing portal components - first run only...
  pushd frontend & call npm install & popd
)

echo Stopping anything already on ports 3001 / 5173...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":3001" ^| findstr "LISTENING"') do taskkill /f /pid %%p >nul 2>nul
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do taskkill /f /pid %%p >nul 2>nul

findstr /b /c:"DB_PASSWORD=change-me" "backend\.env" >nul && (
  echo.
  echo  backend\.env still has DB_PASSWORD=change-me.
  echo  Set it to the password of the "klicense" role you created in pgAdmin, save, and run start.bat again.
  notepad "backend\.env"
  pause
  exit /b 1
)
findstr /b /c:"DB_MOCK=true" "backend\.env" >nul && (
  echo.
  echo  backend\.env has DB_MOCK=true. The in-memory demo mode no longer exists:
  echo  remove that line - the server always uses PostgreSQL.
  notepad "backend\.env"
  pause
  exit /b 1
)

pushd backend
echo.
echo Database:
"%VPY%" -m scripts.db_migrate
if errorlevel 1 (
  popd
  echo.
  echo  Database setup failed - see the message above.
  echo  Is PostgreSQL running? Are the DB_ values in backend\.env right?
  pause
  exit /b 1
)
echo.
echo Applications (apps.json):
"%VPY%" -m scripts.configure_apps
popd

echo.
echo Starting the licence server and the portal...
start "K License server" cmd /k "cd /d "%~dp0backend" && "%VPY%" run.py --reload"
start "K License portal" cmd /k "cd /d "%~dp0frontend" && npm run dev"
timeout /t 8 /nobreak >nul
start "" http://localhost:5173

echo.
echo Running on PostgreSQL.
echo Portal: http://localhost:5173   login admin / Pass@100%%
echo Licence server: http://localhost:3001  (health: /health and /health/db)
echo Close the two server windows to stop.
echo.
echo First time only, so other PCs can reach the server, run in an Administrator command prompt:
echo   netsh advfirewall firewall add rule name="K License API" dir=in action=allow protocol=TCP localport=3001
endlocal
