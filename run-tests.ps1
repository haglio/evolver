$ErrorActionPreference = "Stop"

$python = (Get-Command python -ErrorAction SilentlyContinue)?.Source
if ($python) {
    & $python -m unittest discover -s tests -p "test_*.py" -v
    exit $LASTEXITCODE
}

$py = (Get-Command py -ErrorAction SilentlyContinue)?.Source
if ($py) {
    & $py -3 -m unittest discover -s tests -p "test_*.py" -v
    exit $LASTEXITCODE
}

throw "Python launcher not found. Install Python and ensure 'python' or 'py' is in PATH."
