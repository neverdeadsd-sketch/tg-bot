"""Озвучка ролика: Silero TTS, русский мужской голос, раскладка по таймингам.

Каждая фраза синтезируется отдельно и ставится ровно на свою секунду —
дорожка сразу совпадает с видео, подгонять в монтаже ничего не нужно.

    pip install torch soundfile numpy
    python assets/make_voice.py

Первый запуск скачает модель (~100 МБ). Голоса: aidar (спокойный мужской),
eugene (мягче), также есть baya, kseniya, xenia — женские.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf
import torch

ASSETS = Path(__file__).resolve().parent
OUT = ASSETS / "voice.wav"

SPEAKER = "aidar"        # спокойный мужской
SAMPLE_RATE = 48000
GAP = 0.15               # минимальная пауза между фразами, если предыдущая затянулась
TOTAL_SECONDS = 34.5     # длительность ролика

# (секунда начала, текст) — тайминги совпадают со сценами в make_reels.py
LINES: list[tuple[float, str]] = [
    (0.0, "Заявки от клиентов теряются в переписке."),
    (2.4, "Смотрите, как это работает с ботом."),
    (5.0, "Клиент проходит семь коротких шагов: тип бота, сфера."),
    (9.5, "Нужные функции отмечает галочками."),
    (13.9, "Бюджет и срок — диапазонами."),
    (17.7, "Печатать ничего не надо: почти везде кнопки, и на каждом шаге есть «назад»."),
    (21.8, "Перед отправкой он видит сводку и может поправить любой пункт."),
    (25.0, "Клиенту уходит номер заявки, а вам приходит готовая карточка "
           "с контактом, бюджетом и сроком."),
    (30.5, "Сделаю такой же под ваш бизнес. Пишите."),
]


def main() -> None:
    torch.set_num_threads(4)
    print("Загружаю модель Silero…")
    model, _ = torch.hub.load(
        repo_or_dir="snakers4/silero-models", model="silero_tts",
        language="ru", speaker="v4_ru", trust_repo=True,
    )
    model.to(torch.device("cpu"))

    pieces: list[tuple[float, np.ndarray]] = []
    cursor = 0.0
    for planned, text in LINES:
        audio = model.apply_tts(text=text, speaker=SPEAKER, sample_rate=SAMPLE_RATE,
                                put_accent=True, put_yo=True).numpy()
        start = max(planned, cursor)
        length = len(audio) / SAMPLE_RATE
        if start > planned + 0.01:
            print(f"  ! фраза сдвинута на {start - planned:.2f} с — предыдущая длиннее слота")
        print(f"  {start:5.1f} с  {length:4.1f} с  {text[:46]}…")
        pieces.append((start, audio))
        cursor = start + length + GAP

    total = max(TOTAL_SECONDS, cursor)
    track = np.zeros(int(total * SAMPLE_RATE), dtype=np.float32)
    for start, audio in pieces:
        offset = int(start * SAMPLE_RATE)
        track[offset:offset + len(audio)] += audio.astype(np.float32)

    peak = float(np.max(np.abs(track))) or 1.0
    track = (track / peak) * 0.89          # нормализация с запасом от клиппинга
    sf.write(OUT, track, SAMPLE_RATE)
    print(f"\nГотово: {OUT}  {total:.1f} с")
    print("Положите файл в репозиторий и запушьте — сведу дорожку с видео.")


if __name__ == "__main__":
    main()
