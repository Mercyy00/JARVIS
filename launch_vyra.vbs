Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "D:\engineers\JAY\JARVIS"
WshShell.Run """C:\Users\Perfect\AppData\Local\Programs\Python\Python312\pythonw.exe"" -m vyra.gui_server", 0, False
