' =========================================================
' Fin+ Nifty 500 Screener One-Click Desktop Launcher
' Runs the Streamlit server minimized on a dedicated port (8506)
' to prevent collisions with Fin+ Trading Journal (on 8505).
' =========================================================

Dim WshShell
Set WshShell = CreateObject("WScript.Shell")

' Set the working directory to your Finance project folder
WshShell.CurrentDirectory = "c:\Users\AbhilashBabu\Finance"

' Launch Streamlit using its absolute executable path on dedicated port 8506
' (7 = Minimized command window, False = Do not wait for completion)
WshShell.Run "cmd.exe /c ""C:\Users\AbhilashBabu\AppData\Local\Programs\Python\Python311\Scripts\streamlit.exe"" run nifty_scanner\scanner_app.py --server.port 8506", 7, False

Set WshShell = Nothing
