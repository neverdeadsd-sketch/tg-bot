@echo off
rem Double-click this to open the app. Closing the window stops the server.
setlocal
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" run.py ui
echo.
echo The server has stopped.
pause
endlocal
