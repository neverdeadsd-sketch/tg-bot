"""Сборка озвучки из отдельных фраз в одну дорожку по таймингам ролика.

Берёт assets/voice_parts/01.wav … и раскладывает их по секундам сцен.
Нужен только стандартный Python — ни torch, ни numpy, ни ffmpeg.

    python assets/assemble_voice.py
"""
from __future__ import annotations

import array
import json
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio_tools  # noqa: E402

ASSETS = Path(__file__).resolve().parent
PARTS = ASSETS / "voice_parts"
OUT = ASSETS / "voice.wav"
PLAN = ASSETS / "voice_plan.json"

GAP = 0.15               # пауза, если фраза не влезла в свой слот

# Запасные тайминги, если ролик ещё не пересобран под записанные фразы.
FALLBACK_STARTS = [0.0, 2.4, 5.0, 9.5, 13.9, 17.7, 21.8, 25.0, 30.5]
FALLBACK_TOTAL = 34.5


def load_plan() -> tuple[list[float], float]:
    """make_reels.py кладёт сюда старты сцен после подгонки под фразы."""
    if PLAN.exists():
        data = json.loads(PLAN.read_text(encoding="utf-8"))
        return data["phrases"], float(data["total"])
    print("! voice_plan.json не найден — беру базовые тайминги.")
    print("  Сначала запустите make_reels.py, он подгонит сцены под ваши фразы.")
    return FALLBACK_STARTS, FALLBACK_TOTAL


def main() -> None:
    files = audio_tools.list_parts(PARTS)
    if not files:
        raise SystemExit(f"Нет аудиофайлов в {PARTS}.\n"
                         f"Положите туда записи фраз: 01, 02, … 09 (wav, mp3 или m4a).")
    starts, total_seconds = load_plan()
    if len(files) != len(starts):
        print(f"! файлов {len(files)}, а таймингов {len(starts)} — раскладываю по порядку")

    parts, rate = [], None
    for path in files:
        samples, part_rate = audio_tools.load_part(path)
        if rate is None:
            rate = part_rate
        elif part_rate != rate:
            raise SystemExit(f"{path.name}: частота {part_rate} вместо {rate}")
        parts.append((path.name, samples))

    placed, cursor = [], 0.0
    for index, (name, samples) in enumerate(parts):
        planned = starts[index] if index < len(starts) else cursor
        start = max(planned, cursor)
        length = len(samples) / rate
        if start > planned + 0.01:
            print(f"  ! {name} сдвинут на {start - planned:.2f} с — предыдущая фраза длиннее слота")
        print(f"  {start:5.1f} с  {length:4.1f} с  {name}")
        placed.append((start, samples))
        cursor = start + length + GAP

    total = max(total_seconds, cursor)
    track = array.array("i", bytes(4 * int(total * rate)))   # 32 бита — запас на сложение
    for start, samples in placed:
        offset = int(start * rate)
        for index, value in enumerate(samples):
            track[offset + index] += value

    peak = max(abs(min(track)), abs(max(track))) or 1
    scale = 29000 / peak
    output = array.array("h", [int(value * scale) for value in track])
    if sys.byteorder == "big":
        output.byteswap()
    with wave.open(str(OUT), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(output.tobytes())

    print(f"\nГотово: {OUT}  {total:.1f} с, {rate} Гц")
    print("Дальше: python assets/mux_voice.py — или запушьте voice.wav, сведу я.")


if __name__ == "__main__":
    main()
