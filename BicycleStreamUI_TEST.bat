@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [FEHLER] .venv fehlt. Bitte zuerst setup_windows.bat ausfuehren.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" launcher.py --mode test
endlocal
