"""Монтаж ролика из живой записи экрана.

Берёт запись Telegram Desktop, кадрирует её в вертикаль 1080x1920, режет на
куски по сценам и растягивает каждый под свою реплику озвучки. Запись сделана
на 120 кадрах в секунду, поэтому даже пятикратное замедление остаётся плавным.

    python assets/make_reels_real.py запись.mp4

Что где показывается — таблица SEGMENTS ниже.
"""
from __future__ import annotations

import argparse
import array
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio_tools  # noqa: E402

ASSETS = Path(__file__).resolve().parent
PARTS = ASSETS / "voice_parts"
OUT = ASSETS / "reels_real.mp4"

W, H, FPS = 1080, 1920, 30
TAIL = 0.30            # тишина после реплики, чтобы кадр не обрывался на слове

# Кадрирование исходника 1920x1080: колонка чата без списка диалогов и панели задач
CROP_CHAT = "crop=568:1010:566:12"
CROP_CARD = "crop=452:803:570:40"      # укрупнение на карточке заявки

# (файл реплики, что показываем, диапазон в записи)
SEGMENTS = [
    ("01.wav", "card", ASSETS / "reels_hook.png"),
    ("02.wav", "chat", (0.35, 2.15)),      # приветствие и меню
    ("03.wav", "chat", (2.15, 4.15)),      # шаги 1 и 2
    ("04.wav", "chat", (4.15, 7.45)),      # функции с галочками
    ("05.wav", "chat", (7.45, 9.65)),      # бюджет и срок
    ("06.wav", "chat", (9.65, 10.60)),     # описание, кнопки «пропустить» и «назад»
    ("08.wav", "card", None),              # карточка заявки крупно — подставится ниже
    ("09.wav", "card", ASSETS / "reels_cta.png"),
]
CARD_MOMENT = 1.00                        # кадр, с которого берём укрупнение карточки


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(result.stderr[-1500:])


def encode_still(image: Path, seconds: float, target: Path) -> None:
    run([ffmpeg(), "-y", "-loglevel", "error", "-loop", "1", "-i", str(image),
         "-t", f"{seconds:.3f}", "-vf", f"scale={W}:{H},fps={FPS},format=yuv420p",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", str(target)])


def encode_clip(source: Path, start: float, end: float, seconds: float,
                target: Path, crop: str) -> None:
    """Кусок записи, растянутый под длительность реплики."""
    factor = seconds / (end - start)
    if factor < 1.0:                      # ускорять не станем — просто возьмём короче
        end, factor = start + seconds, 1.0

    chain = [crop, f"scale={W}:{H}:flags=lanczos",
             f"setpts={factor:.4f}*PTS", f"fps={FPS}", "format=yuv420p"]
    run([ffmpeg(), "-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
         "-i", str(source), "-an", "-vf", ",".join(chain),
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", str(target)])


def encode_zoom(source: Path, moment: float, seconds: float, target: Path,
                crop: str, workdir: Path) -> None:
    """Медленный наезд на один кадр: живее статики и считается быстро."""
    still = workdir / f"{target.stem}_still.png"
    run([ffmpeg(), "-y", "-loglevel", "error", "-ss", f"{moment:.3f}", "-i", str(source),
         "-frames:v", "1", "-vf", f"{crop},scale={W}:{H}:flags=lanczos", str(still)])

    frames = max(2, int(seconds * FPS))
    run([ffmpeg(), "-y", "-loglevel", "error", "-loop", "1", "-i", str(still),
         "-t", f"{seconds:.3f}",
         "-vf", f"zoompan=z=\'min(1+0.00045*on,1.10)\':d={frames}:x=\'iw/2-(iw/zoom/2)\':"
                f"y=\'ih/2-(ih/zoom/2)\':s={W}x{H}:fps={FPS},format=yuv420p",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", str(target)])


def build_track(starts: list[float], names: list[str], total: float, path: Path) -> None:
    """Дорожка озвучки: каждая реплика на своей секунде."""
    rate = None
    placed = []
    for start, name in zip(starts, names):
        samples, part_rate = audio_tools.load_part(PARTS / name)
        rate = rate or part_rate
        if part_rate != rate:
            raise SystemExit(f"{name}: частота {part_rate} вместо {rate}")
        placed.append((start, samples))

    track = array.array("i", bytes(4 * int(total * rate)))
    for start, samples in placed:
        offset = int(start * rate)
        for index, value in enumerate(samples):
            if offset + index < len(track):
                track[offset + index] += value

    peak = max(abs(min(track)), abs(max(track))) or 1
    scale = 29000 / peak
    output = array.array("h", [int(value * scale) for value in track])
    if sys.byteorder == "big":
        output.byteswap()
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(output.tobytes())


def main() -> None:
    parser = argparse.ArgumentParser(description="Монтаж ролика из записи экрана")
    parser.add_argument("source", help="запись экрана 1920x1080")
    args = parser.parse_args()
    source = Path(args.source)

    work = tempfile.TemporaryDirectory(prefix="reels_real_")
    workdir = Path(work.name)

    starts, names, pieces, cursor = [], [], [], 0.0
    for index, (part, kind, payload) in enumerate(SEGMENTS):
        seconds = audio_tools.duration(PARTS / part) + TAIL
        piece = workdir / f"{index:02d}.mp4"

        if kind == "card" and payload is not None:
            encode_still(payload, seconds, piece)
        elif kind == "card":
            encode_zoom(source, CARD_MOMENT, seconds, piece, CROP_CARD, workdir)
        else:
            encode_clip(source, payload[0], payload[1], seconds, piece, CROP_CHAT)

        print(f"  {part}  {seconds:4.1f} с  старт {cursor:5.1f} с  {kind}")
        starts.append(cursor)
        names.append(part)
        pieces.append(piece)
        cursor += seconds

    listing = workdir / "list.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in pieces), encoding="utf-8")
    silent = workdir / "silent.mp4"
    run([ffmpeg(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(listing), "-c", "copy", str(silent)])

    voice = workdir / "voice.wav"
    build_track(starts, names, cursor, voice)

    run([ffmpeg(), "-y", "-loglevel", "error", "-i", str(silent), "-i", str(voice),
         "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
         "-movflags", "+faststart", str(OUT)])
    print(f"\nГотово: {OUT}  {cursor:.1f} с  {OUT.stat().st_size / 1024 / 1024:.1f} МБ")


if __name__ == "__main__":
    main()
