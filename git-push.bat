@echo off
rem ============================================================
rem  Push the K License Center to GitHub (first time and later).
rem    git-push.bat https://github.com/<you>/k-license-center.git
rem  First time: connects this folder to the GitHub repo and pushes.
rem  Later: just run git-push.bat (commits all changes, then pushes).
rem  Git for Windows asks you to sign in to GitHub in the browser once.
rem ============================================================
setlocal
cd /d "%~dp0"
where git >nul 2>nul || (echo Git not found. Install "Git for Windows" from https://git-scm.com/download/win & pause & exit /b 1)

if not "%~1"=="" (
  git remote remove origin >nul 2>nul
  git remote add origin %1
)
git remote get-url origin >nul 2>nul || (echo No GitHub address yet. Run:  git-push.bat https://github.com/^<you^>/k-license-center.git & pause & exit /b 1)

git add -A
git diff --cached --quiet || (
  set /p MSG=Describe the change ^(Enter = "Update"^):
  if "%MSG%"=="" set "MSG=Update"
  git commit -m "%MSG%"
)
git push -u origin main
echo.
pause
endlocal
