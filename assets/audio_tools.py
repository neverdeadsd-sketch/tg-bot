"""Чтение записанных фраз: любой формат, обрезка тишины, выравнивание громкости.

Телефон и «Запись голоса» отдают m4a или mp3, поэтому файлы при необходимости
конвертируются через ffmpeg из пакета imageio-ffmpeg. Чистый WAV 16 бит
читается напрямую, без каких-либо зависимостей.
"""
from __future__ import annotations

import array
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wma", ".mp4"}

SILENCE_LEVEL = 0.015   # порог тишины относительно пика фразы
PAD_SECONDS = 0.08      # сколько тишины оставить по краям
TARGET_PEAK = 0.82      # к какому уровню подтягивать каждую фразу

_converted: dict[Path, Path] = {}
_tempdir: tempfile.TemporaryDirectory | None = None


def list_parts(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.suffix.lower() in AUDIO_SUFFIXES)


def _ffmpeg() -> str:
    try:
        import imageio_ffmpeg
    except ImportError:
        raise SystemExit(
            "Для этого формата нужен ffmpeg: python -m pip install imageio-ffmpeg\n"
            "Либо сохраните записи как WAV."
        )
    return imageio_ffmpeg.get_ffmpeg_exe()


def _to_wav(path: Path) -> Path:
    """Конвертирует что угодно в моно WAV 16 бит 44.1 кГц."""
    global _tempdir
    if path in _converted:
        return _converted[path]
    if _tempdir is None:
        _tempdir = tempfile.TemporaryDirectory(prefix="voice_parts_")
    target = Path(_tempdir.name) / f"{path.stem}.wav"
    result = subprocess.run(
        [_ffmpeg(), "-y", "-loglevel", "error", "-i", str(path),
         "-ac", "1", "-ar", "44100", "-sample_fmt", "s16", str(target)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"Не удалось прочитать {path.name}:\n{result.stderr[-500:]}")
    _converted[path] = target
    return target


def _read_wav(path: Path) -> tuple[array.array, int]:
    with wave.open(str(path), "rb") as handle:
        rate, width, channels = handle.getframerate(), handle.getsampwidth(), handle.getnchannels()
        raw = handle.readframes(handle.getnframes())
    if width != 2:
        raise ValueError("не 16 бит")
    samples = array.array("h")
    samples.frombytes(raw)
    if sys.byteorder == "big":
        samples.byteswap()
    if channels > 1:
        samples = array.array("h", [
            sum(samples[i:i + channels]) // channels
            for i in range(0, len(samples) - channels + 1, channels)
        ])
    return samples, rate


def _trim(samples: array.array, rate: int) -> array.array:
    """Убирает паузы по краям — иначе фразы поедут относительно сцен."""
    peak = max(abs(min(samples)), abs(max(samples))) if samples else 0
    if peak == 0:
        return samples
    threshold = peak * SILENCE_LEVEL
    first, last = 0, len(samples) - 1
    while first < last and abs(samples[first]) < threshold:
        first += 1
    while last > first and abs(samples[last]) < threshold:
        last -= 1
    pad = int(PAD_SECONDS * rate)
    return samples[max(0, first - pad):min(len(samples), last + pad)]


def _normalize(samples: array.array) -> array.array:
    peak = max(abs(min(samples)), abs(max(samples))) if samples else 0
    if peak == 0:
        return samples
    scale = (TARGET_PEAK * 32767) / peak
    if 0.9 < scale < 1.1:
        return samples
    return array.array("h", [max(-32768, min(32767, int(value * scale))) for value in samples])


def load_part(path: Path, *, trim: bool = True, normalize: bool = True) -> tuple[array.array, int]:
    """Читает фразу: конвертирует при необходимости, режет тишину, ровняет громкость."""
    try:
        samples, rate = _read_wav(path) if path.suffix.lower() == ".wav" else _read_wav(_to_wav(path))
    except (ValueError, wave.Error):
        samples, rate = _read_wav(_to_wav(path))
    if trim:
        samples = _trim(samples, rate)
    if normalize:
        samples = _normalize(samples)
    return samples, rate


def duration(path: Path) -> float:
    samples, rate = load_part(path)
    return len(samples) / rate
