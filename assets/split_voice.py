"""Нарезка сплошной озвучки на отдельные реплики по паузам.

Синтезаторы отдают весь текст одним файлом, а сборщику нужны фразы по
отдельности. Скрипт находит паузы и режет запись ровно на нужное число
кусков, оставляя границами самые длинные паузы — то есть межфразовые,
а не запятые внутри предложения.

    python assets/split_voice.py запись.mp3
    python assets/split_voice.py запись.mp3 --count 9 --noise -32
"""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

ASSETS = Path(__file__).resolve().parent
PARTS = ASSETS / "voice_parts"


def ffmpeg() -> str:
    try:
        import imageio_ffmpeg
    except ImportError:
        raise SystemExit("Нужен ffmpeg: python -m pip install imageio-ffmpeg")
    return imageio_ffmpeg.get_ffmpeg_exe()


def duration(path: Path) -> float:
    probe = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(path)],
                           capture_output=True, text=True).stderr
    match = re.search(r"Duration: (\d+):(\d+):([\d.]+)", probe)
    if not match:
        raise SystemExit(f"Не удалось определить длительность: {path}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def find_pauses(path: Path, noise: float, minimum: float) -> list[tuple[float, float]]:
    report = subprocess.run(
        [ffmpeg(), "-hide_banner", "-nostats", "-i", str(path),
         "-af", f"silencedetect=noise={noise}dB:d={minimum}", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    starts = [float(v) for v in re.findall(r"silence_start: ([\d.]+)", report)]
    ends = [float(v) for v in re.findall(r"silence_end: ([\d.]+)", report)]
    return list(zip(starts, ends))


def main() -> None:
    parser = argparse.ArgumentParser(description="Режет сплошную озвучку на реплики")
    parser.add_argument("source", help="файл со всей озвучкой")
    parser.add_argument("--count", type=int, default=9, help="сколько реплик получить")
    parser.add_argument("--noise", type=float, default=-32, help="порог тишины, дБ")
    parser.add_argument("--min", dest="minimum", type=float, default=0.25,
                        help="минимальная длина паузы, с")
    parser.add_argument("--pad", type=float, default=0.06, help="запас по краям куска, с")
    args = parser.parse_args()

    source = Path(args.source)
    if not source.exists():
        raise SystemExit(f"Нет файла: {source}")

    total = duration(source)
    pauses = find_pauses(source, args.noise, args.minimum)
    if not pauses:
        raise SystemExit("Пауз не найдено — попробуйте порог помягче, например --noise -28")

    # Края записи границами не считаем
    inner = [(start, end) for start, end in pauses if start > 0.05 and end < total - 0.05]
    if len(inner) < args.count - 1:
        raise SystemExit(
            f"Нашлось всего {len(inner)} пауз внутри записи, а нужно {args.count - 1}. "
            "Смягчите порог: --noise -28 или --min 0.2"
        )

    # Границы — самые длинные паузы: они разделяют фразы, а короткие это запятые
    boundaries = sorted(sorted(inner, key=lambda p: p[1] - p[0], reverse=True)[:args.count - 1])
    head = pauses[0][1] if pauses and pauses[0][0] <= 0.05 else 0.0
    tail = pauses[-1][0] if pauses and pauses[-1][1] >= total - 0.05 else total

    segments = []
    cursor = head
    for start, end in boundaries:
        segments.append((cursor, start))
        cursor = end
    segments.append((cursor, tail))

    PARTS.mkdir(parents=True, exist_ok=True)
    for old in PARTS.iterdir():
        if old.is_file():
            old.unlink()

    print(f"Запись {total:.1f} с, пауз найдено {len(inner)}, режу на {len(segments)}:\n")
    for index, (start, end) in enumerate(segments, 1):
        begin = max(0.0, start - args.pad)
        finish = min(total, end + args.pad)
        target = PARTS / f"{index:02d}.wav"
        result = subprocess.run(
            [ffmpeg(), "-y", "-loglevel", "error", "-ss", f"{begin:.3f}", "-to", f"{finish:.3f}",
             "-i", str(source), "-ac", "1", "-ar", "44100", "-sample_fmt", "s16", str(target)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise SystemExit(result.stderr[-500:])
        print(f"  {target.name}  {finish - begin:4.1f} с   {begin:6.2f} - {finish:6.2f}")

    print("\nПроверьте на слух, что фразы разрезаны по границам предложений.")
    print("Дальше: python assets/make_reels.py, затем assemble_voice.py и mux_voice.py")


if __name__ == "__main__":
    main()
