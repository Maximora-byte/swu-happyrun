@echo off
setlocal
cd /d "%~dp0"
py -3.13 --version >nul 2>&1
if errorlevel 1 (
  echo Python 3.13 is required. Install it from python.org, then open this launcher again.
  pause
  exit /b 2
)
py -3.13 verify_package.py
if errorlevel 1 goto failed
if exist ".runtime\Scripts\python.exe" goto install
py -3.13 -m venv .runtime
if errorlevel 1 goto failed
:install
".runtime\Scripts\python.exe" -m pip --disable-pip-version-check install --force-reinstall --no-index --find-links wheels --require-hashes -r requirements-runtime.txt
if errorlevel 1 goto failed
:start
".runtime\Scripts\python.exe" -m swu_happyrun desktop
if errorlevel 1 goto failed
exit /b 0
:failed
echo HappyRun could not start. Existing local state has been preserved.
pause
exit /b 1
