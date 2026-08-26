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

# Кадрирование исходника 1920x1080. Границы измерены по перепаду яркости:
# окно чата начинается на x=540, заголовок окна кончается на y=24,
# панель задач начинается на y=1048. Резать «на глаз» нельзя — срезает
# аватарки бота и левый край шапки.
CROP_CHAT = "crop=572:1016:542:24"

# (файл реплики, что показываем, диапазон в записи, подпись на экране)
SEGMENTS = [
    ("01.wav", "card", ASSETS / "reels_hook.png", None),
    ("02.wav", "chat", (0.35, 2.15), "Клиент открывает бота"),
    ("03.wav", "chat", (2.15, 4.15), "7 шагов — и почти везде кнопки"),
    ("04.wav", "chat", (4.15, 7.45), "Нужные функции — галочками"),
    ("05.wav", "chat", (7.45, 9.65), "Бюджет и срок — диапазонами"),
    ("06.wav", "chat", (9.65, 10.60), "Печатать почти ничего не нужно"),
    ("09.wav", "card", ASSETS / "reels_cta.png", None),
]

FONT = str(ASSETS / "fonts" / "InterDisplay-SemiBold.ttf")
CAPTION_SIZE = 52
CAPTION_BOTTOM = 1640          # верх плашки: ниже кнопок, но выше поля ввода


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def caption_layer(text: str, target: Path) -> None:
    """Подпись на прозрачном слое: ffmpeg в этой сборке не умеет drawtext."""
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(FONT, CAPTION_SIZE)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    words, lines, current = text.split(" "), [], ""
    for word in words:
        probe = f"{current} {word}".strip()
        if draw.textlength(probe, font=font) <= W - 220 or not current:
            current = probe
        else:
            lines.append(current)
            current = word
    lines.append(current)

    line_height = CAPTION_SIZE + 16
    box_height = line_height * len(lines) + 44
    widest = max(draw.textlength(line, font=font) for line in lines)
    box_width = int(widest) + 76
    x0, y0 = (W - box_width) // 2, CAPTION_BOTTOM
    draw.rounded_rectangle([x0, y0, x0 + box_width, y0 + box_height],
                           radius=26, fill=(8, 12, 18, 205))

    y = y0 + 22
    for line in lines:
        width = draw.textlength(line, font=font)
        draw.text(((W - width) / 2, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_height

    layer.save(target)


def run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(result.stderr[-1500:])


def encode_still(image: Path, seconds: float, target: Path) -> None:
    run([ffmpeg(), "-y", "-loglevel", "error", "-loop", "1", "-i", str(image),
         "-t", f"{seconds:.3f}", "-vf", f"scale={W}:{H},fps={FPS},format=yuv420p",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", str(target)])


def encode_clip(source: Path, start: float, end: float, seconds: float,
                target: Path, crop: str, caption: Path | None) -> None:
    """Кусок записи, растянутый под длительность реплики, с подписью поверх."""
    factor = seconds / (end - start)
    if factor < 1.0:                      # ускорять не станем — просто возьмём короче
        end, factor = start + seconds, 1.0

    chain = f"{crop},scale={W}:{H}:flags=lanczos,setpts={factor:.4f}*PTS,fps={FPS}"
    command = [ffmpeg(), "-y", "-loglevel", "error",
               "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(source)]
    if caption:
        command += ["-i", str(caption), "-filter_complex",
                    f"[0:v]{chain}[v];[v][1:v]overlay=0:0,format=yuv420p"]
    else:
        command += ["-vf", f"{chain},format=yuv420p"]
    command += ["-an", "-c:v", "libx264", "-preset", "medium", "-crf", "20", str(target)]
    run(command)


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
    for index, (part, kind, payload, text) in enumerate(SEGMENTS):
        seconds = audio_tools.duration(PARTS / part) + TAIL
        piece = workdir / f"{index:02d}.mp4"

        if kind == "card":
            encode_still(payload, seconds, piece)
        else:
            caption = None
            if text:
                caption = workdir / f"{index:02d}_caption.png"
                caption_layer(text, caption)
            encode_clip(source, payload[0], payload[1], seconds, piece, CROP_CHAT, caption)

        print(f"  {part}  {seconds:4.1f} с  старт {cursor:5.1f} с  {text or 'титр'}")
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
