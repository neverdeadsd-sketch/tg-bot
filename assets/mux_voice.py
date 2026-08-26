"""Сведение готовой озвучки с роликом.

    pip install imageio-ffmpeg
    python assets/mux_voice.py

Берёт assets/reels_brief.mp4 и assets/voice.wav, отдаёт reels_brief_voiced.mp4:
видео копируется без пережатия, звук кодируется в AAC. Если дорожка длиннее
видео, последний кадр удерживается до её конца — хвост реплики не обрежется.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import imageio_ffmpeg

ASSETS = Path(__file__).resolve().parent
VIDEO = ASSETS / "reels_brief.mp4"
VOICE = ASSETS / "voice.wav"
OUT = ASSETS / "reels_brief_voiced.mp4"

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def duration(path: Path) -> float:
    probe = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True
    ).stderr
    for line in probe.splitlines():
        if "Duration:" in line:
            clock = line.split("Duration:")[1].split(",")[0].strip()
            hours, minutes, seconds = clock.split(":")
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    raise SystemExit(f"Не удалось определить длительность: {path}")


def main() -> None:
    for path in (VIDEO, VOICE):
        if not path.exists():
            raise SystemExit(f"Нет файла: {path}")

    video_len, voice_len = duration(VIDEO), duration(VOICE)
    print(f"видео {video_len:.1f} с, озвучка {voice_len:.1f} с")

    command = [FFMPEG, "-y", "-i", str(VIDEO), "-i", str(VOICE)]
    if voice_len > video_len + 0.05:
        # держим последний кадр, пока говорит голос
        command += ["-filter_complex", f"[0:v]tpad=stop_mode=clone:stop_duration={voice_len - video_len:.2f}[v]",
                    "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "slow", "-crf", "20"]
    else:
        command += ["-map", "0:v", "-map", "1:a", "-c:v", "copy", "-shortest"]
    command += ["-c:a", "aac", "-b:a", "160k", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(OUT)]

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(result.stderr[-2000:])
    print(f"Готово: {OUT}  {OUT.stat().st_size / 1024 / 1024:.1f} МБ")


if __name__ == "__main__":
    main()
