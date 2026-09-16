' Launch THIS WORKTREE's Evolver -- the whole app, beside the live one -- so a
' branch can be judged before it lands. Same tray icon, same window, every
' command working, on the live library and the live app's own run history,
' queue manifests and settings: what the user judges a change by is the app
' itself, not a window of it filled from a report.
'
' Four things a worktree needs done differently:
'   - it borrows the primary checkout's .venv (a worktree has none of its own;
'     the primary is three levels up: <primary>\.claude\worktrees\<name>),
'   - it marks the run a branch session (EVOLVER_BRANCH_SESSION=1), which is
'     what points those user files at the live checkout and keeps the schedule,
'     the presence poll and the broker watch with the live app -- two of either
'     would fight (see gui/branch_session.py),
'   - it re-copies the primary's content.local.json every launch. Not once: the
'     overlay is where library_root and project_roots live, so a copy taken
'     weeks ago resolves a library that has moved, and the preview comes up on
'     the committed example overlay with no library at all,
'   - its own log lands in this worktree's state\ folder.
' Named distinctly from launch_evolver.vbs on purpose: handed a launcher
' sharing the live app's name, you click the one you run daily and review the
' old code.

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
' built against are installed, so the preview runs the versions the live app
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
