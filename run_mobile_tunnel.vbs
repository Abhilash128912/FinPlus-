' =========================================================
' Fin+ Mobile App Tunnel Launcher
' Starts the Localtunnel client in the background minimized
' exposing port 8000 on a static subdomain.
' =========================================================

Dim WshShell
Set WshShell = CreateObject("WScript.Shell")

' Set the working directory to your Finance project folder
WshShell.CurrentDirectory = "c:\Users\AbhilashBabu\Finance"

' Launch localtunnel with static subdomain 'abhilash-finplus'
' (7 = Minimized command window, False = Do not wait for completion)
WshShell.Run "cmd.exe /c npx localtunnel --port 8000 --subdomain abhilash-finplus", 7, False

Set WshShell = Nothing
