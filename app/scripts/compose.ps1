$ErrorActionPreference = 'Stop'
$LabRoot = Split-Path -Parent $PSScriptRoot
$ComposeArgs = @('--env-file', (Join-Path $LabRoot 'lab.env'), '--env-file', (Join-Path $LabRoot 'secrets/ims.env'))
Push-Location $LabRoot
try {
    & docker compose @ComposeArgs @args
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}
