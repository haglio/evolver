$ErrorActionPreference = "Stop"

$bash = "C:\Program Files\Git\bin\bash.exe"
$cmd  = "/c/path/to/suite-root/projects/evolver/evolver.sh"

& $bash -lc $cmd
exit $LASTEXITCODE
