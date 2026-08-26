param([string]$Voice = "", [double]$Rate = 1.0)

# Озвучка через современный движок Windows (WinRT SpeechSynthesis).
# В отличие от System.Speech он видит голоса OneCore, включая русский
# мужской Pavel. Права администратора и правка реестра не нужны.
#
#   .\assets\make_voice_winrt.ps1                      - список голосов
#   .\assets\make_voice_winrt.ps1 -Voice "Pavel"       - запись фраз
#   .\assets\make_voice_winrt.ps1 -Voice "Pavel" -Rate 1.1

$ErrorActionPreference = "Stop"

[Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType = WindowsRuntime] | Out-Null

# PowerShell 5.1 не умеет await для WinRT. Расширения из
# System.Runtime.WindowsRuntime есть не в каждой сборке, поэтому просто
# опрашиваем статус операции: 0 - выполняется, 1 - готово, дальше ошибка.
function Wait-Async($operation) {
    $deadline = (Get-Date).AddSeconds(60)
    while ($operation.Status -eq 0) {
        if ((Get-Date) -gt $deadline) { throw "Синтезатор не ответил за 60 секунд" }
        Start-Sleep -Milliseconds 20
    }
    if ($operation.Status -ne 1) {
        throw "Синтез вернул статус $($operation.Status) (2 - отменён, 3 - ошибка)"
    }
    $operation.GetResults()
}

$voices = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices

if (-not $Voice) {
    Write-Host "Голоса, доступные современному движку:`n"
    $voices | ForEach-Object {
        Write-Host ("  {0,-32} {1,-8} {2}" -f $_.DisplayName, $_.Language, $_.Gender)
    }
    Write-Host "`nЗапись: .\assets\make_voice_winrt.ps1 -Voice 'Pavel'"
    exit
}

$selected = $voices | Where-Object { $_.DisplayName -like "*$Voice*" } | Select-Object -First 1
if (-not $selected) {
    Write-Host "Голос '$Voice' не найден. Доступны:`n"
    $voices | ForEach-Object { Write-Host ("  {0}  ({1})" -f $_.DisplayName, $_.Language) }
    exit 1
}
Write-Host ("Голос: {0}  {1}  {2}`n" -f $selected.DisplayName, $selected.Language, $selected.Gender)

$lines = @(
    "Заявки от клиентов теряются в переписке.",
    "Смотрите, как это работает с ботом.",
    "Клиент проходит семь коротких шагов: тип бота, сфера.",
    "Нужные функции отмечает галочками.",
    "Бюджет и срок — диапазонами.",
    "Печатать ничего не надо: почти везде кнопки, и на каждом шаге есть «назад».",
    "Перед отправкой он видит сводку и может поправить любой пункт.",
    "Клиенту уходит номер заявки, а вам приходит готовая карточка с контактом, бюджетом и сроком.",
    "Сделаю такой же под ваш бизнес. Пишите."
)

$dir = Join-Path $PSScriptRoot "voice_parts"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
Get-ChildItem $dir -Filter *.wav | Remove-Item -Force   # чтобы не смешать со старой записью

$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$synth.Voice = $selected
$synth.Options.SpeakingRate = $Rate

for ($i = 0; $i -lt $lines.Count; $i++) {
    $path = Join-Path $dir ("{0:d2}.wav" -f ($i + 1))

    $stream = Wait-Async $synth.SynthesizeTextToStreamAsync($lines[$i])
    $size = [uint32]$stream.Size
    $reader = New-Object Windows.Storage.Streams.DataReader($stream.GetInputStreamAt(0))
    Wait-Async $reader.LoadAsync($size) | Out-Null
    $bytes = New-Object byte[] $size
    $reader.ReadBytes($bytes)
    $reader.Dispose()
    [System.IO.File]::WriteAllBytes($path, $bytes)

    Write-Host ("  {0}  {1:n1} КБ  {2}" -f (Split-Path $path -Leaf), ($size / 1KB), $lines[$i])
}
$synth.Dispose()

Write-Host "`nФразы записаны в $dir"
Write-Host "Дальше по порядку:"
Write-Host "  python assets/make_reels.py"
Write-Host "  python assets/assemble_voice.py"
Write-Host "  python assets/mux_voice.py"
