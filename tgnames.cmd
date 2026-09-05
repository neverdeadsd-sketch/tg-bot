@echo off
rem Run any tgnames command without having to remember where Python lives.
rem   tgnames ui
rem   tgnames analyze money
rem Prefers the project's virtualenv, falls back to Python on PATH.
setlocal
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" run.py %*
if errorlevel 1 (
  echo.
  pause
)
endlocal
