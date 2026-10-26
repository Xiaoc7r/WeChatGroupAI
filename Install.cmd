@echo off
setlocal
cd /d "%~dp0"
py -3.12 -c "import struct, tkinter; assert struct.calcsize('P') == 8"
if errorlevel 1 goto python_missing
if not exist ".venv\Scripts\python.exe" (
    py -3.12 -m venv .venv
    if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -c "import tkinter, win32crypt, win32ui, requests, wechatauto"
if errorlevel 1 goto failed
echo SUCCESS: Run Start.cmd. Configure your own API key and WeChat group.
pause
exit /b 0
:python_missing
echo Install Python 3.12 x64 with Python Launcher and Tkinter first.
pause
exit /b 1
:failed
echo STOPPED: See the error above. For win32ui DLL errors, install Microsoft Visual C++ x64 runtime.
pause
exit /b 1
