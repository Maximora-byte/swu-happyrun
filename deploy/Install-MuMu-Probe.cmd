@echo off
setlocal
cd /d "%~dp0"
if exist ".runtime\Scripts\python.exe" goto runtime_verify
py -3.13 --version >nul 2>&1
if errorlevel 1 goto python_missing
py -3.13 verify_package.py
if errorlevel 1 goto verify_failed
goto runtime_required
:runtime_verify
".runtime\Scripts\python.exe" verify_package.py
if errorlevel 1 goto verify_failed
".runtime\Scripts\python.exe" install_mumu_probe.py --open-app
if errorlevel 1 goto install_failed
pause
exit /b 0
:runtime_required
echo First open Start-HappyRun.cmd once to prepare the offline runtime, then try again.
pause
exit /b 2
:python_missing
echo Python 3.13 or the prepared HappyRun runtime is required. Open Start-HappyRun.cmd first.
pause
exit /b 2
:verify_failed
echo Package verification failed. Keep and use the original complete delivery folder.
pause
exit /b 2
:install_failed
echo Probe installation stopped. No uninstall, data reset, or automatic retry was performed.
pause
exit /b 3
