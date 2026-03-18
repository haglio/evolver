$ErrorActionPreference = "Stop"

$bash = "C:\Program Files\Git\bin\bash.exe"
$cmd  = "/c/path/to/suite-root/projects/evolver/evolver.sh"
$workingDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path

$process = Start-Process -FilePath $bash `
	-ArgumentList '-lc', $cmd `
	-WorkingDirectory $workingDirectory `
	-WindowStyle Hidden `
	-PassThru `
	-Wait

exit $process.ExitCode
