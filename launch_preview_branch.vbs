' Launch THIS WORKTREE's Evolver window as a branch preview, for judging a
' change before it lands. It opens the run-detail window on what the branch
' reports about the real library and nothing else: no tray, no scheduler, no
' pipeline (see preview_branch.py for why Evolver can never preview by running
' a second instance). The live app can stay running -- this contends with
' nothing it does.
'
' Three things a worktree needs done differently, same shape as origenerator's
' launcher of the same name:
'   - it borrows the primary checkout's .venv (a worktree has none of its own;
'     the primary is three levels up: <primary>\.claude\worktrees\<name>),
'     falling back to python on PATH exactly as launch_evolver.vbs does,
'   - it re-copies the primary's content.local.json every launch. Not once:
'     the overlay is where library_root and project_roots live, so a copy taken
'     weeks ago resolves a library that has moved, and the preview comes up on
'     the committed example overlay showing an empty run instead,
'   - the run record and the running times it measures stay in this worktree's
'     own runs\ and state\, so the live install's are untouched.
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

' The primary's venv when it has one, else whatever python the live launcher
' would have found. Running without a venv is a normal state of the primary, so
' refusing to launch there would strand every preview behind a MsgBox for an
' interpreter the app never needed.
Function FindPythonCommand()
  Dim venvPython, candidates, i

  venvPython = primaryRoot & "\.venv\Scripts\pythonw.exe"
  If fso.FileExists(venvPython) Then
    FindPythonCommand = Quote(venvPython)
    Exit Function
  End If

  candidates = Array("pythonw", "python", "py -3")
  For i = 0 To UBound(candidates)
    If shell.Run("cmd /c where " & Split(candidates(i), " ")(0) & " >nul 2>nul", 0, True) = 0 Then
      FindPythonCommand = candidates(i)
      Exit Function
    End If
  Next
  FindPythonCommand = ""
End Function

pythonCmd = FindPythonCommand()
If pythonCmd = "" Then
  MsgBox "Could not find python or the py launcher.", vbCritical, "Evolver (branch preview)"
  WScript.Quit 1
End If

' The workspace folder holding every sibling checkout, for the shared packages
' the window imports (shared_ui, app_support).
workspaceDir = fso.GetParentFolderName(primaryRoot)

cmd = "cmd /c cd /d " & Quote(projectRoot) & " && set PYTHONPATH=" & workspaceDir & "&&" _
      & pythonCmd & " preview_branch.py 1>>" & Quote(launcherLog) & " 2>&1"
shell.Run cmd, 0, False
