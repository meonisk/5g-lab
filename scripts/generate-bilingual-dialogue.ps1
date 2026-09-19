param(
    [string]$Design = (Join-Path `
        (Split-Path -Parent $PSScriptRoot) `
        'app\tests\fixtures\bilingual-dialogue-v1.json'),
    [string]$OutputDirectory = (Join-Path `
        (Split-Path -Parent $PSScriptRoot) `
        'local\private\dialogue')
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech

$LabRoot = Split-Path -Parent $PSScriptRoot
$PublicEnvironment = @{}
Get-Content -LiteralPath (Join-Path $LabRoot 'app/config/lab.env') | ForEach-Object {
    if ($_ -match '^([^#=]+)=(.*)$') {
        $PublicEnvironment[$matches[1]] = $matches[2]
    }
}

$VoiceByLanguage = @{
    'ru-RU' = $PublicEnvironment.DIALOGUE_RU_WINDOWS_VOICE
    'en-US' = $PublicEnvironment.DIALOGUE_EN_WINDOWS_VOICE
}

$dialogueDesign = Get-Content -Raw -Encoding UTF8 $Design | ConvertFrom-Json
$audioFormat = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
    [int]$dialogueDesign.audio_format.sample_rate_hz,
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono
)

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

$manifestTracks = [ordered]@{}
foreach ($trackName in @('ue1', 'ue2')) {
    $trackDesign = $dialogueDesign.tracks.$trackName
    $voiceName = $VoiceByLanguage[[string]$trackDesign.language]
    if (-not $voiceName) {
        throw "No Windows dialogue voice configured for $($trackDesign.language)"
    }
    $speechSynthesizer = New-Object System.Speech.Synthesis.SpeechSynthesizer

    try {
        $installedVoices = @(
            $speechSynthesizer.GetInstalledVoices() |
                ForEach-Object { $_.VoiceInfo.Name }
        )
        if ($voiceName -notin $installedVoices) {
            throw (
                "Required TTS voice '$voiceName' is not installed. " +
                'Change DIALOGUE_*_WINDOWS_VOICE in app/config/lab.env. ' +
                "Installed: $($installedVoices -join ', ')"
            )
        }

        $speechSynthesizer.SelectVoice([string]$voiceName)
        $speechSynthesizer.Rate = [int]$trackDesign.rate

        # SSML-паузы задают очередность собеседников. Они являются частью
        # воспроизводимого тестового входа, а не задержкой самого стенда.
        $ssmlParts = [System.Collections.Generic.List[string]]::new()
        if ([int]$trackDesign.leading_silence_ms -gt 0) {
            $ssmlParts.Add(
                "<break time=`"$([int]$trackDesign.leading_silence_ms)ms`"/>"
            )
        }

        for ($turnIndex = 0; $turnIndex -lt $trackDesign.turns.Count; $turnIndex++) {
            $escapedText = [System.Security.SecurityElement]::Escape(
                [string]$trackDesign.turns[$turnIndex]
            )
            $ssmlParts.Add($escapedText)

            $hasNextTurn = $turnIndex -lt $trackDesign.turns.Count - 1
            if ($hasNextTurn) {
                $ssmlParts.Add(
                    "<break time=`"$([int]$trackDesign.between_turns_ms)ms`"/>"
                )
            }
        }

        if ([int]$trackDesign.trailing_silence_ms -gt 0) {
            $ssmlParts.Add(
                "<break time=`"$([int]$trackDesign.trailing_silence_ms)ms`"/>"
            )
        }

        $speechMarkup = (
            '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" ' +
            "xml:lang=`"$($trackDesign.language)`">" +
            ($ssmlParts -join ' ') +
            '</speak>'
        )
        $audioPath = Join-Path `
            $OutputDirectory `
            "$trackName-$($trackDesign.language).wav"

        $speechSynthesizer.SetOutputToWaveFile($audioPath, $audioFormat)
        $speechSynthesizer.SpeakSsml($speechMarkup)
        $speechSynthesizer.SetOutputToNull()

        $audioFile = Get-Item $audioPath
        $manifestTracks[$trackName] = [ordered]@{
            file = $audioFile.Name
            voice = [string]$voiceName
            language = [string]$trackDesign.language
            bytes = $audioFile.Length
            sha256 = (Get-FileHash -Algorithm SHA256 $audioPath).Hash.ToLowerInvariant()
        }
    }
    finally {
        $speechSynthesizer.Dispose()
    }
}

$manifest = [ordered]@{
    fixture_id = $dialogueDesign.fixture_id
    generated_at_utc = [DateTime]::UtcNow.ToString('o')
    source_design = (Resolve-Path $Design).Path
    audio_format = $dialogueDesign.audio_format
    playback_seconds = $dialogueDesign.playback_seconds
    tracks = $manifestTracks
}

$manifestPath = Join-Path $OutputDirectory 'manifest.json'
$manifest | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $manifestPath

Write-Output "Generated bilingual dialogue fixture in $OutputDirectory"
