# Create valid private lab credentials once. Never overwrite existing keys.
$ErrorActionPreference = 'Stop'
$LabRoot = Split-Path -Parent $PSScriptRoot
$SecretPath = Join-Path $LabRoot 'secrets/ims.env'
if (-not (Test-Path -LiteralPath $SecretPath)) {
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        function New-LabHex {
            $bytes = New-Object byte[] 16
            $rng.GetBytes($bytes)
            return ([BitConverter]::ToString($bytes)).Replace('-', '')
        }
        $content = @(
            "IMS_DIGEST_PASSWORD=$(New-LabHex)"
            "SUBSCRIBER_K=$(New-LabHex)"
            "SUBSCRIBER_OPC=$(New-LabHex)"
            'SUBSCRIBER_AMF=8000'
        )
        [IO.File]::WriteAllLines($SecretPath, $content, [Text.UTF8Encoding]::new($false))
        Write-Host 'Created private laboratory credentials in secrets/ims.env'
    } finally { $rng.Dispose() }
}
$values = @{}
Get-Content -LiteralPath $SecretPath | ForEach-Object {
    if ($_ -match '^([^#=]+)=(.*)$') { $values[$matches[1]] = $matches[2] }
}
foreach ($key in @('SUBSCRIBER_K', 'SUBSCRIBER_OPC')) {
    if ($values[$key] -notmatch '^[0-9a-fA-F]{32}$') {
        throw "$key must contain exactly 32 hexadecimal characters in secrets/ims.env"
    }
}
if (-not $values['IMS_DIGEST_PASSWORD'] -or $values['IMS_DIGEST_PASSWORD'].StartsWith('replace-')) {
    throw 'Set IMS_DIGEST_PASSWORD in secrets/ims.env; existing credentials were preserved'
}
if ($values['SUBSCRIBER_AMF'] -notmatch '^[0-9a-fA-F]{4}$') {
    throw 'SUBSCRIBER_AMF must contain four hexadecimal characters'
}
New-Item -ItemType Directory -Force -Path (Join-Path $LabRoot 'private/recordings') | Out-Null
