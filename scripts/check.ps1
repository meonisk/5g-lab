$ErrorActionPreference = 'Stop'
Push-Location "$PSScriptRoot\..\app"
try {
    python tools/quality/check.py
    if ($LASTEXITCODE -ne 0) { throw 'Offline checks failed' }
} finally { Pop-Location }
