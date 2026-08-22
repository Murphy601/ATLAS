#Requires -Version 5.1
param(
    [Parameter(Mandatory = $true)]
    [string]$Path
)

$ErrorActionPreference = "Stop"
$Path = (Resolve-Path -LiteralPath $Path).Path

Add-Type -AssemblyName System.Runtime.WindowsRuntime | Out-Null
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]

function Wait-WinRtOperation {
    param(
        $Operation,
        [type]$ResultType
    )
    $asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq "AsTask" -and
            $_.IsGenericMethodDefinition -and
            $_.GetGenericArguments().Count -eq 1 -and
            $_.GetParameters().Count -eq 1
        } |
        Select-Object -First 1
    if (-not $asTask) {
        throw "WindowsRuntime AsTask(IAsyncOperation) was not found"
    }
    $generic = $asTask.MakeGenericMethod($ResultType)
    $task = $generic.Invoke($null, @($Operation))
    [void]$task.Wait(-1)
    return $task.Result
}

$engine = $null
try {
    $en = New-Object Windows.Globalization.Language "en-US"
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($en)
} catch {
    $engine = $null
}
if (-not $engine) {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
}
if (-not $engine) {
    Write-Output "[]"
    exit 0
}

$file = Wait-WinRtOperation ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
$stream = Wait-WinRtOperation ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Wait-WinRtOperation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Wait-WinRtOperation ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$result = Wait-WinRtOperation ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])

$words = New-Object System.Collections.Generic.List[object]
foreach ($line in $result.Lines) {
    foreach ($word in $line.Words) {
        $box = $word.BoundingRect
        $words.Add([ordered]@{
            text = [string]$word.Text
            x    = [int]$box.X
            y    = [int]$box.Y
            w    = [int]$box.Width
            h    = [int]$box.Height
        }) | Out-Null
    }
}

if ($words.Count -eq 0) {
    Write-Output "[]"
} else {
    $words | ConvertTo-Json -Compress
}
