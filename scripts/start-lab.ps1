param([switch]$SkipVerify)
$ErrorActionPreference = 'Stop'
$LabRoot = Split-Path -Parent $PSScriptRoot
$Bash = 'C:\Program Files\Git\bin\bash.exe'
foreach ($command in @('docker', 'python', 'powershell.exe', 'wsl')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required command is missing: $command"
    }
}
if (-not (Test-Path $Bash)) { throw 'Install Git for Windows with Bash' }
docker info --format '{{.OSType}}' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop with Linux containers first' }
& "$PSScriptRoot\initialize-local.ps1"
$PublicEnv = @{}
Get-Content (Join-Path $LabRoot 'app/config/lab.env') | ForEach-Object {
    if ($_ -match '^([^#=]+)=(.*)$') { $PublicEnv[$matches[1]] = $matches[2] }
}

Push-Location $LabRoot
try {
    & powershell.exe -NoProfile -File "$PSScriptRoot\generate-bilingual-dialogue.ps1"
    if ($LASTEXITCODE -ne 0) { throw 'Dialogue fixture generation failed; check Windows voices' }
    & powershell.exe -NoProfile -File "$PSScriptRoot\generate-bilingual-dialogue.ps1" -Design "$LabRoot\app\tests\fixtures\interpreter-dialogue-v1.json" -OutputDirectory "$LabRoot\local\private\interpreter"
    if ($LASTEXITCODE -ne 0) { throw 'Interpreter fixture generation failed' }

    & "$PSScriptRoot\prepare-host.ps1"
    if ($LASTEXITCODE -ne 0) { throw 'SCTP preparation failed' }

    & "$PSScriptRoot\compose.ps1" up -d --build
    if ($LASTEXITCODE -ne 0) { throw 'docker compose up failed' }

    docker wait lab-llm-model-init | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'could not wait for pinned LLM initialization' }
    $LlmInitExit = docker inspect --format '{{.State.ExitCode}}' lab-llm-model-init
    if ($LASTEXITCODE -ne 0 -or $LlmInitExit -ne '0') { throw 'pinned LLM initialization failed' }

    docker cp "$LabRoot\scripts\subscribers.js" lab-mongo:/tmp/subscribers.js
    if ($LASTEXITCODE -ne 0) { throw 'Open5GS subscriber copy failed' }
    docker exec lab-mongo mongosh --quiet /tmp/subscribers.js
    if ($LASTEXITCODE -ne 0) { throw 'Open5GS subscriber provisioning failed' }

    $ready = $false
    for ($attempt = 0; $attempt -lt 36; $attempt++) {
        try {
            $api = "http://$($PublicEnv.PYHSS_API_BIND):$($PublicEnv.PYHSS_API_PORT)/ims_subscriber/list?page=0&page_size=1"
            $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 $api
            if ($response.StatusCode -eq 200) { $ready = $true; break }
        } catch { Start-Sleep -Seconds 5 }
    }
    if (-not $ready) { throw 'PyHSS REST API did not become ready' }

    & $Bash scripts/provision-ims-subscribers.sh --apply
    if ($LASTEXITCODE -ne 0) { throw 'IMS subscriber provisioning failed' }

    # A recreated Mongo container can leave long-lived Open5GS clients and the
    # gNB SCTP association pointing at stale state. Restart the dependency
    # chain before the UEs so a config-only/secret-scope update is reproducible.
    docker restart lab-udr lab-udm lab-ausf lab-pcf lab-amf | Out-Null
    Start-Sleep -Seconds 5
    docker restart lab-gnb | Out-Null
    Start-Sleep -Seconds 5
    docker restart lab-ue1 lab-ue2 | Out-Null
    Start-Sleep -Seconds 15
    docker restart lab-sipue1 lab-sipue2 | Out-Null
    Start-Sleep -Seconds 12

    if (-not $SkipVerify) {
        foreach ($gate in @('verify.sh', 'verify-ims.sh', 'verify-ims-registration.sh', 'verify-ims-call.sh', 'verify-voice-agent.sh', 'verify-real-ai-stream.sh', 'verify-transcription-recording.sh', 'verify-bilingual-dialogue.sh', 'verify-security.sh')) {
            & $Bash "app/tests/integration/$gate"
            if ($LASTEXITCODE -ne 0) { throw "$gate failed" }
        }
    }
} finally {
    Pop-Location
}
