' Launch THIS WORKTREE's Evolver -- the whole app, in place of the usual one --
' so a branch can be judged before it lands. Same tray icon, same window, every
' command working, the schedule included, on the live library and the usual
' Evolver's own run history, queue manifests and settings: what the user judges
' a change by is the app itself, not a window of it filled from a report. The
' Evolver running when this starts steps aside for it, and comes back when the
' preview is quit or has run for an hour (see gui/branch_session.py). Running
' this again replaces a preview already up, so it always shows the branch as
' it stands.
'
' Four things a worktree needs done differently:
'   - it borrows the primary checkout's .venv (a worktree has none of its own;
'     the primary is three levels up: <primary>\.claude\worktrees\<name>),
'   - it marks the run a branch session (EVOLVER_BRANCH_SESSION=1), which is
'     what points those user files at the live checkout and has the Evolver
'     already running make way for it (see gui/branch_session.py),
'   - it re-copies the primary's content.local.json every launch. Not once: the
'     overlay is where library_root and project_roots live, so a copy taken
'     weeks ago resolves a library that has moved, and the preview comes up on
'     the committed example overlay with no library at all,
'   - its own log lands in this worktree's state\ folder.
' Named distinctly from launch_evolver.vbs on purpose: handed a launcher
' sharing the usual Evolver's name, you click the one you run daily and review
' the old code.

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

projectRoot = fso.GetParentFolderName(WScript.ScriptFullName)
stateDir = projectRoot & "\state"
If Not fso.FolderExists(stateDir) Then fso.CreateFolder(stateDir)
launcherLog = stateDir & "\preview_branch.log"

Function Quote(s)
  Quote = Chr(34) & s & Chr(34)
End Function

' <primary>\.claude\worktrees\<this worktree> -> up three levels to the primary.
primaryRoot = fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(projectRoot)))

overlay = primaryRoot & "\content.local.json"
If fso.FileExists(overlay) Then
  fso.CopyFile overlay, projectRoot & "\content.local.json", True
End If

' pythonw, not python: the tray is a GUI app and must not flash up a console.
' The primary's venv and nothing else -- it is where the siblings this app was
' built against are installed, so the preview runs the versions the usual one
' runs rather than whatever sits in the workspace folder.
pythonExe = primaryRoot & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pythonExe) Then
  MsgBox "The primary checkout's virtual environment is missing:" & vbCrLf & pythonExe, _
         vbCritical, "Evolver (branch preview)"
  WScript.Quit 1
End If

cmd = "cmd /c cd /d " & Quote(projectRoot) & " && set EVOLVER_BRANCH_SESSION=1&&" _
      & Quote(pythonExe) & " tray_app.py --show-window 1>>" & Quote(launcherLog) & " 2>&1"
shell.Run cmd, 0, False
