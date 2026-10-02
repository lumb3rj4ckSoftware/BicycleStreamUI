@echo off
setlocal
cd /d "%~dp0"
py -3.10 -m venv .venv 2>nul || python -m venv .venv
if errorlevel 1 goto :error
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 goto :error
echo.
echo Setup fertig. Starte BicycleStreamUI.bat oder BicycleStreamUI_TEST.bat.
pause
exit /b 0
:error
echo.
echo Setup fehlgeschlagen.
pause
exit /b 1
