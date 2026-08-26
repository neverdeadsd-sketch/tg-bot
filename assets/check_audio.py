"""Проверка цепочки озвучки: где именно пропал звук.

    python assets/check_audio.py

Смотрит наговорённые фразы, собранную дорожку и итоговые видео, показывает
громкость и наличие звуковой дорожки. Нужен только стандартный Python.
"""
from __future__ import annotations

import array
import subprocess
import sys
import wave
from pathlib import Path

ASSETS = Path(__file__).resolve().parent
PARTS = ASSETS / "voice_parts"
VOICE = ASSETS / "voice.wav"
SILENT = ASSETS / "reels_brief.mp4"
VOICED = ASSETS / "reels_brief_voiced.mp4"


def describe(path: Path) -> str:
    """Длительность, частота и пиковая громкость WAV-файла."""
    with wave.open(str(path), "rb") as handle:
        rate, width, channels = handle.getframerate(), handle.getsampwidth(), handle.getnchannels()
        frames = handle.getnframes()
        raw = handle.readframes(frames)
    if width != 2:
        return f"{frames / rate:5.1f} с  {rate} Гц  {width * 8} бит — не 16 бит, читать не умею"
    samples = array.array("h")
    samples.frombytes(raw)
    if sys.byteorder == "big":
        samples.byteswap()
    peak = max(abs(min(samples)), abs(max(samples))) if samples else 0
    level = peak / 32767
    if level < 0.01:
        verdict = "ТИШИНА"
    elif level < 0.10:
        verdict = f"очень тихо, пик {level * 100:.0f}%"
    else:
        verdict = f"пик {level * 100:.0f}%"
    return f"{frames / rate / channels:5.1f} с  {rate} Гц  {verdict}"


def has_audio_stream(path: Path) -> str:
    try:
        import imageio_ffmpeg
    except ImportError:
        return "не проверить: нет imageio-ffmpeg (pip install imageio-ffmpeg)"
    probe = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
        capture_output=True, text=True,
    ).stderr
    streams = [line.strip() for line in probe.splitlines() if "Stream #" in line]
    audio = [line for line in streams if "Audio:" in line]
    if not audio:
        return "звуковой дорожки НЕТ"
    return "звук есть: " + audio[0].split("Audio:")[1].strip()[:48]


def main() -> None:
    print("1. Наговорённые фразы")
    parts = sorted(PARTS.glob("*.wav")) if PARTS.is_dir() else []
    if not parts:
        print(f"   нет файлов в {PARTS} — сначала make_voice_windows.ps1")
    for path in parts:
        print(f"   {path.name}  {describe(path)}")

    print("\n2. Собранная дорожка")
    print(f"   {VOICE.name}: {describe(VOICE) if VOICE.exists() else 'нет файла — запустите assemble_voice.py'}")

    print("\n3. Видео")
    for path in (SILENT, VOICED):
        if path.exists():
            size = path.stat().st_size / 1024 / 1024
            print(f"   {path.name}  {size:.1f} МБ  {has_audio_stream(path)}")
        else:
            print(f"   {path.name}: нет файла")

    print("\nИтог:")
    if not parts:
        print("   Начните с записи фраз: .\\assets\\make_voice_windows.ps1 -Voice 'Microsoft Pavel'")
    elif not VOICE.exists():
        print("   Соберите дорожку: python assets/make_reels.py, затем assemble_voice.py")
    elif not VOICED.exists():
        print("   Сведите звук с видео: python assets/mux_voice.py")
    else:
        print(f"   Заливать нужно {VOICED.name} — именно в нём звук.")
        print(f"   {SILENT.name} немой по определению, это исходник без дорожки.")


if __name__ == "__main__":
    main()
