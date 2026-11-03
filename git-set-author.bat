@echo off
rem ============================================================
rem  Show every commit as the aadityapa GitHub account.
rem    git-set-author.bat  your-email@example.com
rem  Use the e-mail that is on the aadityapa account (GitHub -> Settings -> Emails), or its
rem  private address  NNNNNNNN+aadityapa@users.noreply.github.com .
rem  Re-signs all existing commits with that name/e-mail, sets it for future commits,
rem  and replaces the history on GitHub (force push).
rem ============================================================
setlocal
cd /d "%~dp0"
if "%~1"=="" (echo Usage: git-set-author.bat aadityapa-email@example.com & pause & exit /b 1)
set "NAME=aadityapa"
set "EMAIL=%~1"

git config user.name "%NAME%"
git config user.email "%EMAIL%"
git add -A
git diff --cached --quiet || git commit -m "Update"

rem Rewrite author and committer of every commit on main (no files change).
set FILTER_BRANCH_SQUELCH_WARNING=1
git filter-branch -f --env-filter "GIT_AUTHOR_NAME='%NAME%'; GIT_AUTHOR_EMAIL='%EMAIL%'; GIT_COMMITTER_NAME='%NAME%'; GIT_COMMITTER_EMAIL='%EMAIL%'; export GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL" -- --branches || (echo Rewrite failed. & pause & exit /b 1)

git remote remove origin >nul 2>nul
git remote add origin https://aadityapa@github.com/aadityapa/k-license-center.git
git config credential.https://github.com.useHttpPath true
git push --force -u origin main
echo.
echo Done: GitHub now shows the commits by %NAME% (%EMAIL%).
pause
endlocal
