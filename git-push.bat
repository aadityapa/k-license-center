@echo off
rem ============================================================
rem  Push the K License Center to GitHub as the aadityapa account.
rem    git-push.bat          commit all changes and push
rem  The GitHub user is fixed in the address (aadityapa@github.com), so Windows uses the
rem  aadityapa login - not another GitHub account saved on this PC (e.g. karanskb).
rem  The first time, a GitHub sign-in window opens: sign in as aadityapa.
rem ============================================================
setlocal
cd /d "%~dp0"
set "GH_USER=aadityapa"
set "REPO=https://%GH_USER%@github.com/aadityapa/k-license-center.git"
where git >nul 2>nul || (echo Git not found. Install "Git for Windows" from https://git-scm.com/download/win & pause & exit /b 1)

git remote remove origin >nul 2>nul
git remote add origin %REPO%
git config credential.https://github.com.useHttpPath true

git add -A
git diff --cached --quiet && goto push
set "MSG=Update"
set /p MSG=Describe the change (Enter = "Update"): 
git commit -m "%MSG%"
:push
echo Pushing to %REPO% ...
git push -u origin main
echo.
pause
endlocal
