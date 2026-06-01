' =========================================================
' Fin+ MCX Energy Swing Workstation desktop launcher
' Runs the clean mcx_workstation.py minimized on port 8502
' to operate alongside the main NSE workstation.
' =========================================================

Dim WshShell
Set WshShell = CreateObject("WScript.Shell")

' Set the working directory to your Finance folder
WshShell.CurrentDirectory = "c:\Users\AbhilashBabu\Finance"

' Launch Streamlit on dedicated port 8502
' (7 = Minimized command window, False = Do not wait for completion)
WshShell.Run "cmd.exe /c ""C:\Users\AbhilashBabu\AppData\Local\Programs\Python\Python311\Scripts\streamlit.exe"" run mcx_workstation.py --server.port 8507", 7, False

Set WshShell = Nothing
