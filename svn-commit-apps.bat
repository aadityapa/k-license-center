@echo off
rem Commit the Vehicle SIM / KSTACK licensing changes to SVN.  Usage: svn-commit-apps.bat [VEHSIM|KSTACK|DIAGSTUDIO]
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0svn-commit-apps.ps1" %1
pause
