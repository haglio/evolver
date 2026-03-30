$ErrorActionPreference = "Stop"

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCmd) {
    & $pythonCmd.Source .\evolver.py
    exit $LASTEXITCODE
}

$pyCmd = Get-Command py -ErrorAction SilentlyContinue
if ($pyCmd) {
    & $pyCmd.Source -3 .\evolver.py
    exit $LASTEXITCODE
}

throw "Python launcher not found. Install Python and ensure 'python' or 'py' is in PATH."
