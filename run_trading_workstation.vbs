' =========================================================
' Fin+ Trading Workstation One-Click Desktop Launcher
' Runs the updated Trading_WS.py minimized on its dedicated port (8501)
' to prevent collisions with other active journals or screeners.
' =========================================================

Dim WshShell
Set WshShell = CreateObject("WScript.Shell")

' Set the working directory to your Finance project folder
WshShell.CurrentDirectory = "c:\Users\AbhilashBabu\Finance"

' Launch Streamlit using its absolute executable path on dedicated port 8501
' (7 = Minimized command window, False = Do not wait for completion)
WshShell.Run "cmd.exe /c ""C:\Users\AbhilashBabu\AppData\Local\Programs\Python\Python311\Scripts\streamlit.exe"" run Trading_WS.py --server.port 8501", 7, False

Set WshShell = Nothing
