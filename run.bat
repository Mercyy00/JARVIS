@echo off
setlocal
cd /d "%~dp0"
set PYTHON_EXE=C:\Users\Perfect\AppData\Local\Programs\Python\Python312\python.exe
if not exist "%PYTHON_EXE%" (
    set PYTHON_EXE=python
)
"%PYTHON_EXE%" main.py %*
endlocal
