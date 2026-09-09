# Prefer a locally installed Python; use the bundled desktop runtime when absent.
$hubPython = Get-Command python,python3 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($hubPython) {
    & $hubPython.Source -B "$PSScriptRoot/hub.py" @args
} else {
    $hubBundledPython = 'C:\Users\SLDD\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (-not (Test-Path -LiteralPath $hubBundledPython)) {
        throw 'Python 3.11+ is required. Run hub.py with your Python interpreter.'
    }
    & $hubBundledPython -B "$PSScriptRoot/hub.py" @args
}
exit $LASTEXITCODE
