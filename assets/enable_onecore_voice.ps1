param([string]$Match = "Pavel", [switch]$Undo)

# Показывает голоса OneCore классическому движку System.Speech.
# Windows держит современные голоса (в том числе русский мужской Pavel) в ветке
# Speech_OneCore, куда System.Speech не смотрит. Скрипт копирует ветку голоса
# в SAPI5 — сам файл голоса не трогается, копируется только описание.
#
#   Запускать в PowerShell ОТ ИМЕНИ АДМИНИСТРАТОРА:
#     .\assets\enable_onecore_voice.ps1
#     .\assets\enable_onecore_voice.ps1 -Match "Pavel"
#     .\assets\enable_onecore_voice.ps1 -Undo        # убрать добавленное

$ErrorActionPreference = "Stop"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Нужны права администратора."
    Write-Host "Закройте это окно и откройте PowerShell через правый клик - Запуск от имени администратора."
    exit 1
}

$oneCore = "HKLM\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens"
$sapi    = "HKLM\SOFTWARE\Microsoft\Speech\Voices\Tokens"

$tokens = Get-ChildItem "HKLM:\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens" |
    Where-Object { (Get-ItemProperty $_.PSPath).'(default)' -like "*$Match*" }

if (-not $tokens) {
    Write-Host "В OneCore нет голоса с '$Match' в названии. Доступные:`n"
    Get-ChildItem "HKLM:\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens" | ForEach-Object {
        Write-Host ("  {0}" -f (Get-ItemProperty $_.PSPath).'(default)')
    }
    exit 1
}

foreach ($token in $tokens) {
    $name = Split-Path $token.Name -Leaf
    $title = (Get-ItemProperty $token.PSPath).'(default)'
    $target = "HKLM:\SOFTWARE\Microsoft\Speech\Voices\Tokens\$name"

    if ($Undo) {
        if (Test-Path $target) {
            Remove-Item $target -Recurse -Force
            Write-Host "Убран: $title"
        } else {
            Write-Host "Не был добавлен: $title"
        }
        continue
    }

    if (Test-Path $target) {
        Write-Host "Уже доступен: $title"
        continue
    }
    & reg copy "$oneCore\$name" "$sapi\$name" /s /f | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Добавлен: $title"
    } else {
        Write-Host "Не удалось скопировать $title (код $LASTEXITCODE)"
    }
}

Write-Host "`nТеперь System.Speech видит:`n"
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.GetInstalledVoices() | ForEach-Object {
    $info = $_.VoiceInfo
    Write-Host ("  {0,-34} {1,-8} {2}" -f $info.Name, $info.Culture, $info.Gender)
}
$synth.Dispose()

if (-not $Undo) {
    Write-Host "`nЗапись голосом Pavel:"
    Write-Host "  .\assets\make_voice_windows.ps1 -Voice 'Microsoft Pavel'"
    Write-Host "Если имя в списке отличается — подставьте его точно как показано выше."
}
