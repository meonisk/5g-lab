param(
    [string]$Design = 'app/tests/fixtures/bilingual-dialogue-v1.json',
    [string]$OutputDirectory = 'local/private/dialogue'
)

$ErrorActionPreference = 'Stop'
$LabRoot = Split-Path -Parent $PSScriptRoot

Push-Location $LabRoot
try {
    python scripts/generate_dialogue.py --design $Design --output $OutputDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Piper dialogue generation failed' }
}
finally {
    Pop-Location
}
