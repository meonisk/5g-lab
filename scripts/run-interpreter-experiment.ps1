param(
    [string]$ExperimentName = 'full-interpreter-call'
)

$ErrorActionPreference = 'Stop'
$LabRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ConfigPath = Join-Path $LabRoot 'app/config/lab.env'
$SecretsPath = Join-Path $LabRoot 'local/secrets/ims.env'
$ComposePath = Join-Path $LabRoot 'docker-compose.yml'

$experimentId = "$(Get-Date -AsUTC -Format 'yyyyMMddTHHmmssZ')-$ExperimentName"
$experimentDirectory = Join-Path $LabRoot "local/experiments/$experimentId"
$inputDirectory = Join-Path $experimentDirectory 'input'
$outputDirectory = Join-Path $experimentDirectory 'output'
$logDirectory = Join-Path $experimentDirectory 'logs'
$metadataDirectory = Join-Path $experimentDirectory 'metadata'

foreach ($directory in @(
    $inputDirectory,
    $outputDirectory,
    $logDirectory,
    $metadataDirectory
)) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
}

$fixtureDirectory = Join-Path $LabRoot 'local/private/interpreter'
Copy-Item `
    -LiteralPath (Join-Path $fixtureDirectory 'ue1-ru-RU.wav') `
    -Destination (Join-Path $inputDirectory 'russian-user-speaks.wav')
Copy-Item `
    -LiteralPath (Join-Path $fixtureDirectory 'ue2-en-US.wav') `
    -Destination (Join-Path $inputDirectory 'english-user-speaks.wav')

$composeArguments = @(
    'compose',
    '--env-file', $ConfigPath,
    '--env-file', $SecretsPath,
    '-f', $ComposePath
)
$startedAt = [DateTime]::UtcNow.ToString('o')
$testExitCode = 1
$env:EXPERIMENT_DIRECTORY = $experimentDirectory.Replace('\', '/')

Write-Output "Experiment directory: $experimentDirectory"
Write-Output 'Running two complete phone-side interpreter streams...'

try {
    & python `
        (Join-Path $LabRoot 'app/tests/integration/check_bidirectional_interpreter.py') `
        2>&1 |
        Tee-Object -FilePath (Join-Path $metadataDirectory 'test-result.json')
    $testExitCode = $LASTEXITCODE
}
finally {
    $finishedAt = [DateTime]::UtcNow.ToString('o')

    # Capture every Compose container log before replacing the recorder clients.
    $containerRows = @(
        & docker @composeArguments ps -a --format json |
            ForEach-Object { $_ | ConvertFrom-Json }
    )
    foreach ($container in $containerRows) {
        $safeName = ($container.Name -replace '[^A-Za-z0-9_.-]', '_')
        $logPath = Join-Path $logDirectory "$safeName.log"
        $containerLog = @(
            & docker logs `
                --since $startedAt `
                --until $finishedAt `
                --timestamps `
                $container.Name `
                2>&1
        )
        [System.IO.File]::WriteAllLines(
            $logPath,
            [string[]]$containerLog,
            [System.Text.UTF8Encoding]::new($false)
        )
    }

    $containerNames = @($containerRows | ForEach-Object { $_.Name })
    & docker inspect $containerNames |
        Set-Content -Encoding UTF8 (Join-Path $metadataDirectory 'containers.inspect.json')
    & docker @composeArguments ps -a --format json |
        Set-Content -Encoding UTF8 (Join-Path $metadataDirectory 'containers.jsonl')

    # A graceful pjsua exit finalizes RIFF and data lengths in both WAV headers.
    foreach ($clientName in @('lab-sipue1', 'lab-sipue2')) {
        & docker exec `
            $clientName `
            sh `
            -lc `
            'printf "q\n" > /tmp/pjsua-control' `
            2>$null | Out-Null
    }
    Start-Sleep -Seconds 3

    # Replacing pjsua restores ordinary non-recording clients for later work.
    & docker @composeArguments up `
        -d `
        --no-deps `
        --force-recreate `
        sipue1 `
        sipue2 | Out-Null

    Remove-Item Env:EXPERIMENT_DIRECTORY -ErrorAction SilentlyContinue
}

& python `
    (Join-Path $LabRoot 'scripts/build-experiment-manifest.py') `
    $experimentDirectory `
    --repository $LabRoot `
    --started-at $startedAt `
    --finished-at $finishedAt `
    --test-exit-code $testExitCode

$readme = @"
# Full IMS interpreter experiment

This private directory contains one complete end-to-end run.

- `input/`: full WAV injected into each phone microphone side.
- `output/`: full WAV recorded on each phone received-audio side.
- `logs/`: timestamped Docker stdout/stderr for every lab container.
- `metadata/test-result.json`: validated turn, latency, RTP and language result.
- `metadata/containers.inspect.json`: exact container/image/runtime metadata.
- `manifest.json`: hashes, durations, roles, revision and final status.

The output WAV includes everything delivered to that subscriber call leg,
including the interpreter greeting and translated speech. This directory is
private because it contains complete speech audio.
"@
$readme | Set-Content -Encoding UTF8 (Join-Path $experimentDirectory 'README.md')

if ($testExitCode -ne 0) {
    throw "Experiment failed. Evidence was retained in $experimentDirectory"
}

Write-Output "Experiment completed: $experimentDirectory"
