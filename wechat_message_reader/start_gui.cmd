@echo off
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo Missing .venv\Scripts\python.exe. Create the project environment first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m wechat_message_reader.gui
if errorlevel 1 pause
