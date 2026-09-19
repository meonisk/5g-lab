param([switch]$SkipVerify)
& "$PSScriptRoot\start.ps1" -SkipVerify:$SkipVerify
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
