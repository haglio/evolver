$ErrorActionPreference = "Stop"

$bash = "C:\Program Files\Git\bin\bash.exe"
$cmd  = "/c/path/to/suite-root/process_AI_videos.sh"

& $bash -lc $cmd
exit $LASTEXITCODE
