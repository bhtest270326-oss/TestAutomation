@echo off
title Rim Repair Dashboard
cd /d "%~dp0"

python src\dashboard.py 2>nul
if errorlevel 1 (
    py src\dashboard.py 2>nul
    if errorlevel 1 (
        echo.
        echo  Could not start the dashboard.
        echo  Make sure Python is installed and dependencies are ready:
        echo     pip install -r requirements.txt
        echo.
        pause
    )
)
