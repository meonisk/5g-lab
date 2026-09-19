$ErrorActionPreference = 'Stop'
Push-Location "$PSScriptRoot\.."
try {
    python scripts/quality/check.py
    if ($LASTEXITCODE -ne 0) { throw 'Offline checks failed' }
} finally { Pop-Location }
