param([switch]$SkipVerify)

$ErrorActionPreference = 'Stop'

$LabRoot = Split-Path -Parent $PSScriptRoot
$GitBash = 'C:\Program Files\Git\bin\bash.exe'


function Assert-CommandSucceeded {
    param(
        [int]$ExitCode,
        [string]$FailureMessage
    )

    if ($ExitCode -ne 0) {
        throw $FailureMessage
    }
}


function Assert-HostRequirements {
    $requiredCommands = @(
        'docker',
        'python',
        'powershell.exe',
        'wsl'
    )

    foreach ($commandName in $requiredCommands) {
        if (-not (Get-Command $commandName -ErrorAction SilentlyContinue)) {
            throw "Required command is missing: $commandName"
        }
    }

    if (-not (Test-Path -LiteralPath $GitBash)) {
        throw 'Install Git for Windows with Bash'
    }

    docker info --format '{{.OSType}}' | Out-Null
    Assert-CommandSucceeded `
        -ExitCode $LASTEXITCODE `
        -FailureMessage 'Start Docker Desktop with Linux containers first'
}


function Read-PublicEnvironment {
    $environment = @{}
    $environmentPath = Join-Path $LabRoot 'app/config/lab.env'

    Get-Content -LiteralPath $environmentPath | ForEach-Object {
        if ($_ -match '^([^#=]+)=(.*)$') {
            $environment[$matches[1]] = $matches[2]
        }
    }

    return $environment
}


function New-DialogueFixtures {
    & powershell.exe `
        -NoProfile `
        -File "$PSScriptRoot\generate-bilingual-dialogue.ps1"
    Assert-CommandSucceeded `
        -ExitCode $LASTEXITCODE `
        -FailureMessage 'Dialogue fixture generation failed; check Windows voices'

    $interpreterDesign = Join-Path `
        $LabRoot `
        'app/tests/fixtures/interpreter-dialogue-v2.json'
    $interpreterOutput = Join-Path $LabRoot 'local/private/interpreter'

    & powershell.exe `
        -NoProfile `
        -File "$PSScriptRoot\generate-bilingual-dialogue.ps1" `
        -Design $interpreterDesign `
        -OutputDirectory $interpreterOutput
    Assert-CommandSucceeded `
        -ExitCode $LASTEXITCODE `
        -FailureMessage 'Interpreter fixture generation failed'
}


function Wait-PyHssApi {
    param([hashtable]$PublicEnvironment)

    $apiAddress = $PublicEnvironment.PYHSS_API_BIND
    $apiPort = $PublicEnvironment.PYHSS_API_PORT
    $subscriberListUrl = "http://${apiAddress}:${apiPort}/ims_subscriber/list?page=0&page_size=1"

    for ($attemptNumber = 1; $attemptNumber -le 36; $attemptNumber++) {
        try {
            $response = Invoke-WebRequest `
                -UseBasicParsing `
                -TimeoutSec 2 `
                -Uri $subscriberListUrl

            if ($response.StatusCode -eq 200) {
                return
            }
        }
        catch {
            # PyHSS starts three local processes sequentially; readiness is
            # expected to lag behind the Docker container state.
            Start-Sleep -Seconds 5
        }
    }

    throw 'PyHSS REST API did not become ready'
}


function Initialize-Subscribers {
    docker cp `
        "$LabRoot\scripts\subscribers.js" `
        'lab-mongo:/tmp/subscribers.js'
    Assert-CommandSucceeded `
        -ExitCode $LASTEXITCODE `
        -FailureMessage 'Open5GS subscriber copy failed'

    docker exec lab-mongo mongosh --quiet /tmp/subscribers.js
    Assert-CommandSucceeded `
        -ExitCode $LASTEXITCODE `
        -FailureMessage 'Open5GS subscriber provisioning failed'

    & $GitBash scripts/provision-ims-subscribers.sh --apply
    Assert-CommandSucceeded `
        -ExitCode $LASTEXITCODE `
        -FailureMessage 'IMS subscriber provisioning failed'
}


function Restart-RegistrationChain {
    # Recreated databases leave long-lived Open5GS connections and the gNB SCTP
    # association pointing at stale state. Restart dependencies before UEs.
    docker restart lab-udr lab-udm lab-ausf lab-pcf lab-amf | Out-Null
    Start-Sleep -Seconds 5

    docker restart lab-gnb | Out-Null
    Start-Sleep -Seconds 5

    docker restart lab-ue1 lab-ue2 | Out-Null
    Start-Sleep -Seconds 15

    docker restart lab-sipue1 lab-sipue2 | Out-Null
    Start-Sleep -Seconds 12
}


function Invoke-LiveGates {
    $gateFiles = @(
        'verify.sh',
        'verify-ims.sh',
        'verify-ims-registration.sh',
        'verify-ims-call.sh',
        'verify-voice-agent.sh',
        'verify-real-ai-stream.sh',
        'verify-transcription-recording.sh',
        'verify-bilingual-dialogue.sh',
        'verify-security.sh'
    )

    # Все gates используют один стенд, поэтому намеренно выполняются по очереди.
    foreach ($gateFile in $gateFiles) {
        & $GitBash "app/tests/integration/$gateFile"
        Assert-CommandSucceeded `
            -ExitCode $LASTEXITCODE `
            -FailureMessage "$gateFile failed"
    }
}


Assert-HostRequirements
& "$PSScriptRoot\initialize-local.ps1"
$PublicEnvironment = Read-PublicEnvironment

Push-Location $LabRoot
try {
    New-DialogueFixtures

    & "$PSScriptRoot\prepare-host.ps1"
    Assert-CommandSucceeded `
        -ExitCode $LASTEXITCODE `
        -FailureMessage 'SCTP preparation failed'

    & "$PSScriptRoot\compose.ps1" up -d --build
    Assert-CommandSucceeded `
        -ExitCode $LASTEXITCODE `
        -FailureMessage 'docker compose up failed'

    # Инициализатор проверяет digest модели и завершается; рабочий Ollama
    # запускается отдельно и использует тот же приватный volume.
    docker wait lab-llm-model-init | Out-Null
    Assert-CommandSucceeded `
        -ExitCode $LASTEXITCODE `
        -FailureMessage 'Could not wait for pinned LLM initialization'

    $modelInitializationExitCode = docker inspect `
        --format '{{.State.ExitCode}}' `
        lab-llm-model-init
    if ($modelInitializationExitCode -ne '0') {
        throw 'Pinned LLM initialization failed'
    }

    Wait-PyHssApi -PublicEnvironment $PublicEnvironment
    Initialize-Subscribers
    Restart-RegistrationChain

    if (-not $SkipVerify) {
        Invoke-LiveGates
    }
}
finally {
    Pop-Location
}
