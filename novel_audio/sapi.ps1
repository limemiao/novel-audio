param(
    [ValidateSet('list', 'speak')][string]$Mode = 'list',
    [string]$Voice = '',
    [int]$Rate = 0,
    [string]$TextFile = '',
    [string]$OutputFile = ''
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$speaker = New-Object -ComObject SAPI.SpVoice
if ($Mode -eq 'list') {
    $names = @($speaker.GetVoices() | ForEach-Object { $_.GetDescription() })
    ConvertTo-Json -InputObject $names -Compress
    exit 0
}
$matched = $false
foreach ($token in $speaker.GetVoices()) {
    if ($token.GetDescription() -eq $Voice) {
        $speaker.Voice = $token
        $matched = $true
        break
    }
}
if (-not $matched) { throw "Requested system voice is not installed: $Voice" }
$speaker.Rate = [Math]::Max(-10, [Math]::Min(10, $Rate))
$stream = New-Object -ComObject SAPI.SpFileStream
$stream.Format.Type = 22
try {
    $stream.Open($OutputFile, 3, $false)
    $speaker.AudioOutputStream = $stream
    $content = [System.IO.File]::ReadAllText($TextFile, [System.Text.Encoding]::UTF8)
    [void]$speaker.Speak($content, 16)
} finally {
    $stream.Close()
}
