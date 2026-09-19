param([switch]$SkipVerify)
$arguments = @('scripts/start_lab.py')
if ($SkipVerify) { $arguments += '--skip-verify' }
& python @arguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
