param([string]$Voice = "", [int]$Rate = 0)

# Озвучка ролика встроенным синтезатором Windows (System.Speech).
# Без запуска с -Voice просто показывает список установленных голосов.
#
#   .\assets\make_voice_windows.ps1
#   .\assets\make_voice_windows.ps1 -Voice "Microsoft Pavel"
#
# Затем: python assets/assemble_voice.py

Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer

if (-not $Voice) {
    Write-Host "Установленные голоса:`n"
    $synth.GetInstalledVoices() | ForEach-Object {
        $info = $_.VoiceInfo
        Write-Host ("  {0,-34} {1,-8} {2}" -f $info.Name, $info.Culture, $info.Gender)
    }
    Write-Host "`nНужен русский мужской. Запустите снова, например:"
    Write-Host "  .\assets\make_voice_windows.ps1 -Voice 'Microsoft Pavel'"
    Write-Host "`nЕсли русских голосов нет: Параметры - Время и язык - Речь - Добавить голоса - Русский."
    Write-Host "`nСистема может знать больше голосов, чем видит этот интерфейс. Проверить:"
    Write-Host "  Get-ChildItem 'HKLM:\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens' | ForEach-Object { (Get-ItemProperty `$_.PSPath).'(default)' }"
    exit
}

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

$installed = $synth.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }
if ($installed -notcontains $Voice) {
    Write-Host "Голос '$Voice' не установлен. Доступны:`n"
    $installed | ForEach-Object { Write-Host "  $_" }
    Write-Host "`nЗапись отменена — иначе фразы наговорит голос по умолчанию."
    exit 1
}

$synth.SelectVoice($Voice)
$synth.Rate = $Rate          # 0 — обычный темп, +1 быстрее, -1 медленнее

for ($i = 0; $i -lt $lines.Count; $i++) {
    $path = Join-Path $dir ("{0:d2}.wav" -f ($i + 1))
    $synth.SetOutputToWaveFile($path)
    $synth.Speak($lines[$i])
    Write-Host ("  {0}  {1}" -f (Split-Path $path -Leaf), $lines[$i])
}
$synth.SetOutputToNull()
$synth.Dispose()

Write-Host "`nФразы записаны в $dir"
Write-Host "Теперь соберите дорожку: python assets/assemble_voice.py"
