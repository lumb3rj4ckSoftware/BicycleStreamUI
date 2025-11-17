@echo off
REM ============================================================
REM BicycleStreamUI Startscript
REM ============================================================

REM Verzeichnis dieses Skripts als Basis verwenden
cd /d "%~dp0"

echo [INFO] ExecutionPolicy temporär auf Bypass gesetzt ...
powershell -Command "Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force"

echo [INFO] Aktiviere virtuelle Umgebung ...
call .venv\Scripts\activate

echo [INFO] Starte BicycleStreamUI ...
python bridge.py --mode ant --output gc_live.json --interval 0.5

echo.
echo ============================================================
echo [ENDE] BicycleStreamUI wurde beendet.
echo Drücke eine beliebige Taste zum Schließen ...
pause >nul
