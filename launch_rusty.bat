@echo off
cd /d "%~dp0"
start "" "C:\Users\Perfect\AppData\Local\Programs\Python\Python312\pythonw.exe" -m vyra.gui_server
timeout /t 2 /nobreak >nul
if exist "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" (
    start "" "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" --app=http://127.0.0.1:8765 --window-size=420,680
) else (
    start "" "http://127.0.0.1:8765"
)
exit
