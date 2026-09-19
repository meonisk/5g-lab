# Operator entry point. Runtime paths are rooted in app/.
& "$PSScriptRoot\..\app\scripts\compose.ps1" @args
exit $LASTEXITCODE
