param([switch]$SkipVerify)
$ErrorActionPreference = 'Stop'
$LabRoot = Split-Path -Parent $PSScriptRoot
$Bash = 'C:\Program Files\Git\bin\bash.exe'
$PublicEnv = @{}
Get-Content (Join-Path $LabRoot 'lab.env') | ForEach-Object {
    if ($_ -match '^([^#=]+)=(.*)$') { $PublicEnv[$matches[1]] = $matches[2] }
}

Push-Location $LabRoot
try {
    & "$PSScriptRoot\prepare-host.ps1"
    if ($LASTEXITCODE -ne 0) { throw 'SCTP preparation failed' }

    & "$PSScriptRoot\compose.ps1" up -d --build
    if ($LASTEXITCODE -ne 0) { throw 'docker compose up failed' }

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

    docker restart lab-ue1 lab-ue2 | Out-Null
    Start-Sleep -Seconds 15
    docker restart lab-sipue1 lab-sipue2 | Out-Null
    Start-Sleep -Seconds 12

    if (-not $SkipVerify) {
        foreach ($gate in @('verify.sh', 'verify-ims.sh', 'verify-ims-registration.sh', 'verify-ims-call.sh', 'verify-voice-agent.sh')) {
            & $Bash "scripts/$gate"
            if ($LASTEXITCODE -ne 0) { throw "$gate failed" }
        }
    }
} finally {
    Pop-Location
}
