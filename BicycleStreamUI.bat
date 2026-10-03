@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [FEHLER] .venv fehlt. Bitte zuerst setup_windows.bat ausfuehren.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" launcher.py --mode ant
set "BICYCLE_EXIT_CODE=%ERRORLEVEL%"
if not "%BICYCLE_EXIT_CODE%"=="0" (
  echo [FEHLER] Launcher beendet mit Exit-Code %BICYCLE_EXIT_CODE%. Siehe data\launcher.log.
  pause
)
endlocal & exit /b %BICYCLE_EXIT_CODE%
