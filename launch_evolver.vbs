' Starts Evolver's tray app, hidden, and exits.
'
' Evolver already starts from a Startup-folder shortcut at sign-in, which is a
' shortcut the app writes for itself and points at whatever interpreter wrote
' it. This is the launcher for everything that is NOT the user clicking: the
' broker's tray, which starts Evolver again when it finds it gone. Such a caller
' has one path it can be given and no way to work out which interpreter to use,
' so the choosing lives here, once.
'
' Evolver's own single-instance mutex makes a launch over a live Evolver a
' no-op, so a caller may run this on a liveness reading it does not fully trust.

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

projectRoot = fso.GetParentFolderName(WScript.ScriptFullName)
entryPoint = projectRoot & "\tray_app.py"

' pythonw, not python: the tray is a GUI app and must not flash up a console.
pythonExe = projectRoot & "\.venv\Scripts\pythonw.exe"

' The copy a previous run left named for Evolver, when there is one. Windows
' identifies a process by the file it was started from, so a bare interpreter
' puts Evolver in the task list as one more anonymous "Python" -- which is
' exactly what you need it not to be when something has to be ended by hand.
' See app_support.process_identity, and tray_app.py's _name_this_process.
namedExe = projectRoot & "\.venv\Scripts\Evolver-Evolver.exe"
If fso.FileExists(namedExe) Then
    pythonExe = namedExe
End If
If Not fso.FileExists(pythonExe) Then
    pythonExe = "pythonw.exe"
End If

shell.CurrentDirectory = projectRoot
cmd = """" & pythonExe & """ """ & entryPoint & """"
shell.Run cmd, 0, False
