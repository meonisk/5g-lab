$ErrorActionPreference = 'Stop'
& python "$PSScriptRoot\initialize_local.py"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
