@echo off
setlocal
cd /d "%~dp0"
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set PYGAME_HIDE_SUPPORT_PROMPT=1
set PYTHON_EXE=C:\Users\Perfect\AppData\Local\Programs\Python\Python312\python.exe
if not exist "%PYTHON_EXE%" (
    set PYTHON_EXE=python
)
"%PYTHON_EXE%" voice_chat.py %*
endlocal
