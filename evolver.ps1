$ErrorActionPreference = "Stop"

$python = "C:\Python314\python.exe"
$script = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "evolver.py"
$workingDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path

$process = Start-Process -FilePath $python `
	-ArgumentList $script `
	-WorkingDirectory $workingDirectory `
	-WindowStyle Hidden `
	-PassThru `
	-Wait

exit $process.ExitCode
