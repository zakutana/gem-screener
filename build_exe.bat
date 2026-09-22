@echo off
REM Builds dist\GemScreener.exe — double-click it and the screener opens in your
REM browser with a Refresh button that re-runs the collector.
REM
REM --collect-data certifi: requests needs the CA bundle for HTTPS, and without
REM   it every DeFiLlama call inside the frozen exe fails on certificate verify.
REM --noconsole: no terminal window. app.py redirects stdout to gem_screener.log
REM   before importing the collector, because --noconsole sets sys.stdout to None
REM   and every print() would otherwise vanish, errors included.
cd /d "%~dp0"

python -c "import PyInstaller" 2>nul
if errorlevel 1 (
  echo Instaluji PyInstaller...
  python -m pip install pyinstaller || exit /b 1
)

python -m PyInstaller --onefile --noconsole --clean --noconfirm ^
  --name GemScreener ^
  --add-data "template.html;." ^
  --collect-data certifi ^
  --exclude-module tkinter ^
  app.py || exit /b 1

echo.
echo Hotovo: dist\GemScreener.exe
echo Snapshot a log se ukladaji vedle .exe souboru.
