# Create valid private lab credentials once. Never overwrite existing keys.
$ErrorActionPreference = 'Stop'

$LabRoot = Split-Path -Parent $PSScriptRoot
$SecretPath = Join-Path $LabRoot 'local/secrets/ims.env'

if (-not (Test-Path -LiteralPath $SecretPath)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $SecretPath) | Out-Null
    $randomGenerator = [Security.Cryptography.RandomNumberGenerator]::Create()

    try {
        function New-LabHex {
            $bytes = New-Object byte[] 16
            $randomGenerator.GetBytes($bytes)
            return ([BitConverter]::ToString($bytes)).Replace('-', '')
        }

        $secretLines = @(
            "IMS_DIGEST_PASSWORD=$(New-LabHex)"
            "SUBSCRIBER_K=$(New-LabHex)"
            "SUBSCRIBER_OPC=$(New-LabHex)"
            'SUBSCRIBER_AMF=8000'
        )

        [IO.File]::WriteAllLines(
            $SecretPath,
            $secretLines,
            [Text.UTF8Encoding]::new($false)
        )
        Write-Host 'Created private laboratory credentials in local/secrets/ims.env'
    }
    finally {
        $randomGenerator.Dispose()
    }
}

# Проверка существующего файла обязательна: скрипт не заменяет ключи молча,
# потому что это нарушило бы регистрацию уже созданных абонентов.
$secretValues = @{}
Get-Content -LiteralPath $SecretPath | ForEach-Object {
    if ($_ -match '^([^#=]+)=(.*)$') {
        $secretValues[$matches[1]] = $matches[2]
    }
}

foreach ($secretName in @('SUBSCRIBER_K', 'SUBSCRIBER_OPC')) {
    if ($secretValues[$secretName] -notmatch '^[0-9a-fA-F]{32}$') {
        throw (
            "$secretName must contain exactly 32 hexadecimal characters " +
            'in local/secrets/ims.env'
        )
    }
}

$digestPassword = $secretValues['IMS_DIGEST_PASSWORD']
if (-not $digestPassword -or $digestPassword.StartsWith('replace-')) {
    throw 'Set IMS_DIGEST_PASSWORD in local/secrets/ims.env; existing credentials were preserved'
}

if ($secretValues['SUBSCRIBER_AMF'] -notmatch '^[0-9a-fA-F]{4}$') {
    throw 'SUBSCRIBER_AMF must contain four hexadecimal characters'
}

$recordingDirectory = Join-Path $LabRoot 'local/private/recordings'
New-Item -ItemType Directory -Force -Path $recordingDirectory | Out-Null
