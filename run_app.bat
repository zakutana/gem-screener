@echo off
REM Run Gem Screener without building the exe.
REM Opens http://127.0.0.1:8765/ in your browser; the Refresh button in the
REM page header re-runs the collector.
cd /d "%~dp0"
python app.py
if errorlevel 1 (
  echo.
  echo Neco se pokazilo - podrobnosti v gem_screener.log
  pause
)
