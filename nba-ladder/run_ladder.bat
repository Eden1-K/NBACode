@echo off
REM Updates the NBA ladder model and opens the dashboard.
REM Double-click to run. "run_ladder.bat quiet" updates without opening the page (used by the daily task).
cd /d "%~dp0"
where python >nul 2>nul && (set PY=python) || (set PY=py)
%PY% -m pip install -q -r requirements.txt
%PY% run.py
if /i not "%1"=="quiet" start "" "%~dp0docs\index.html"
