param(
    [string]$Design = (Join-Path (Split-Path -Parent $PSScriptRoot) 'app\tests\fixtures\bilingual-dialogue-v1.json'),
    [string]$OutputDirectory = (Join-Path (Split-Path -Parent $PSScriptRoot) 'local\private\dialogue')
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech

$fixture = Get-Content -Raw -Encoding UTF8 $Design | ConvertFrom-Json
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
    [int]$fixture.audio_format.sample_rate_hz,
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono)
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

$manifestTracks = [ordered]@{}
foreach ($trackName in @('ue1', 'ue2')) {
    $track = $fixture.tracks.$trackName
    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    try {
        $installed = @($synth.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name })
        if ($track.voice -notin $installed) {
            throw "Required TTS voice '$($track.voice)' is not installed. Installed: $($installed -join ', ')"
        }
        $synth.SelectVoice([string]$track.voice)
        $synth.Rate = [int]$track.rate
        $parts = [System.Collections.Generic.List[string]]::new()
        if ([int]$track.leading_silence_ms -gt 0) {
            $parts.Add("<break time=`"$([int]$track.leading_silence_ms)ms`"/>")
        }
        for ($index = 0; $index -lt $track.turns.Count; $index++) {
            $parts.Add([System.Security.SecurityElement]::Escape([string]$track.turns[$index]))
            if ($index -lt $track.turns.Count - 1) {
                $parts.Add("<break time=`"$([int]$track.between_turns_ms)ms`"/>")
            }
        }
        if ([int]$track.trailing_silence_ms -gt 0) {
            $parts.Add("<break time=`"$([int]$track.trailing_silence_ms)ms`"/>")
        }
        $ssml = "<speak version=`"1.0`" xmlns=`"http://www.w3.org/2001/10/synthesis`" xml:lang=`"$($track.language)`">$($parts -join ' ')</speak>"
        $path = Join-Path $OutputDirectory "$trackName-$($track.language).wav"
        $synth.SetOutputToWaveFile($path, $format)
        $synth.SpeakSsml($ssml)
        $synth.SetOutputToNull()
        $item = Get-Item $path
        $manifestTracks[$trackName] = [ordered]@{
            file = $item.Name
            voice = [string]$track.voice
            language = [string]$track.language
            bytes = $item.Length
            sha256 = (Get-FileHash -Algorithm SHA256 $path).Hash.ToLowerInvariant()
        }
    } finally {
        $synth.Dispose()
    }
}

$manifest = [ordered]@{
    fixture_id = $fixture.fixture_id
    generated_at_utc = [DateTime]::UtcNow.ToString('o')
    source_design = (Resolve-Path $Design).Path
    audio_format = $fixture.audio_format
    playback_seconds = $fixture.playback_seconds
    tracks = $manifestTracks
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $OutputDirectory 'manifest.json')
Write-Output "Generated bilingual dialogue fixture in $OutputDirectory"
