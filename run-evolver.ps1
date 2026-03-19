$ErrorActionPreference = "Stop"

$python = (Get-Command python -ErrorAction SilentlyContinue)?.Source
if ($python) {
    & $python .\evolver.py
    exit $LASTEXITCODE
}

$py = (Get-Command py -ErrorAction SilentlyContinue)?.Source
if ($py) {
    & $py -3 .\evolver.py
    exit $LASTEXITCODE
}

throw "Python launcher not found. Install Python and ensure 'python' or 'py' is in PATH."
