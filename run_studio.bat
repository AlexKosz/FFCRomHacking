@echo off
title FFC Hack Studio
cd /d "%~dp0"
echo Checking dependencies (first run only takes a moment)...
python -m pip install -q -r requirements.txt
echo.
echo Starting FFC Hack Studio -- your browser will open automatically.
echo Keep this window open while you work. Close it to quit.
echo.
python -m ffc_hack_tool gui --projects projects
pause
