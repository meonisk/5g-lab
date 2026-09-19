param(
    [Parameter(Position=0)]
    [ValidateSet('prepare','collect','validate','verify')]
    [string]$Command = 'verify',
    [string]$RunId,
    [string]$Design = 'app/research/designs/local-language-services-smoke-v2.json'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Tool = Join-Path $Root 'app/research/tools/research_run.py'
$Arguments = @($Tool, $Command, '--root', $Root)
if ($Design) { $Arguments += @('--design', (Join-Path $Root $Design)) }
if ($RunId) { $Arguments += @('--run-id', $RunId) }
& python @Arguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
