$ErrorActionPreference = "Stop"

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCmd) {
    & $pythonCmd.Source -m unittest discover -s tests -p "test_*.py" -v
    exit $LASTEXITCODE
}

$pyCmd = Get-Command py -ErrorAction SilentlyContinue
if ($pyCmd) {
    & $pyCmd.Source -3 -m unittest discover -s tests -p "test_*.py" -v
    exit $LASTEXITCODE
}

throw "Python launcher not found. Install Python and ensure 'python' or 'py' is in PATH."
