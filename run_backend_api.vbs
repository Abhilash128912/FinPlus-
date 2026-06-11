' =========================================================
' Trading Workstation API Backend One-Click Launcher
' Runs the FastAPI backend server on port 8000 in the background.
' =========================================================

Dim WshShell
Set WshShell = CreateObject("WScript.Shell")

' Set the working directory to your Finance project folder
WshShell.CurrentDirectory = "c:\Users\AbhilashBabu\Finance"

' Launch FastAPI server using virtual environment python on port 8000
' (7 = Minimized command window, False = Do not wait for completion)
WshShell.Run "cmd.exe /c ""C:\Users\AbhilashBabu\venv311\Scripts\python.exe"" backend_ws_api.py", 7, False

Set WshShell = Nothing
