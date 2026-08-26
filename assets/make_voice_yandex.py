"""Озвучка через Yandex SpeechKit: девять фраз ролика одним запуском.

Нужен только стандартный Python — ни pip-пакетов, ни ffmpeg: ответ приходит
сырым PCM, скрипт сам оборачивает его в WAV.

    python assets/make_voice_yandex.py --key AQVN... --voice ermil

Ключ можно положить в переменную окружения YANDEX_API_KEY.

Где взять ключ: консоль Yandex Cloud - сервисный аккаунт с ролью
ai.speechkit-tts.user - создать API-ключ. Нужен именно синтез речи
(SpeechKit), а не «голосовой агент» — тот для живых диалогов.

Мужские русские голоса: ermil (спокойный), filipp, zahar, madirus.
У ermil и zahar есть амплуа: --role neutral или good.
"""
from __future__ import annotations

import argparse
import os
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path

ASSETS = Path(__file__).resolve().parent
PARTS = ASSETS / "voice_parts"
URL = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"
SAMPLE_RATE = 48000

LINES = [
    "Заявки от клиентов теряются в переписке.",
    "Смотрите, как это работает с ботом.",
    "Клиент проходит семь коротких шагов: тип бота, сфера.",
    "Нужные функции отмечает галочками.",
    "Бюджет и срок — диапазонами.",
    "Печатать ничего не надо: почти везде кнопки, и на каждом шаге есть «назад».",
    "Перед отправкой он видит сводку и может поправить любой пункт.",
    "Клиенту уходит номер заявки, а вам приходит готовая карточка "
    "с контактом, бюджетом и сроком.",
    "Сделаю такой же под ваш бизнес. Пишите.",
]


def synthesize(text: str, key: str, voice: str, role: str | None,
               speed: float, folder: str | None) -> bytes:
    fields = {
        "text": text, "lang": "ru-RU", "voice": voice, "speed": str(speed),
        "format": "lpcm", "sampleRateHertz": str(SAMPLE_RATE),
    }
    if role:
        fields["emotion"] = role
    if folder:
        fields["folderId"] = folder

    request = urllib.request.Request(
        URL, data=urllib.parse.urlencode(fields).encode("utf-8"),
        headers={"Authorization": f"Api-Key {key}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:400]
        raise SystemExit(f"SpeechKit ответил {error.code}: {detail}") from None
    except urllib.error.URLError as error:
        raise SystemExit(f"Не достучаться до SpeechKit: {error.reason}") from None


def write_wav(path: Path, pcm: bytes) -> float:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm)
    return len(pcm) / 2 / SAMPLE_RATE


def main() -> None:
    parser = argparse.ArgumentParser(description="Озвучка ролика через Yandex SpeechKit")
    parser.add_argument("--key", default=os.getenv("YANDEX_API_KEY"), help="API-ключ сервисного аккаунта")
    parser.add_argument("--voice", default="ermil", help="ermil, filipp, zahar, madirus")
    parser.add_argument("--role", default=None, help="амплуа: neutral или good")
    parser.add_argument("--speed", type=float, default=1.0, help="0.8 медленнее, 1.2 быстрее")
    parser.add_argument("--folder", default=os.getenv("YANDEX_FOLDER_ID"), help="folderId, если ключ его требует")
    args = parser.parse_args()

    if not args.key:
        raise SystemExit("Нужен ключ: --key AQVN... или переменная YANDEX_API_KEY")

    PARTS.mkdir(parents=True, exist_ok=True)
    for old in PARTS.iterdir():                     # чтобы не смешать с прошлой записью
        if old.is_file():
            old.unlink()

    print(f"Голос: {args.voice}{' / ' + args.role if args.role else ''}, темп {args.speed}\n")
    total = 0.0
    for index, text in enumerate(LINES, 1):
        pcm = synthesize(text, args.key, args.voice, args.role, args.speed, args.folder)
        path = PARTS / f"{index:02d}.wav"
        seconds = write_wav(path, pcm)
        total += seconds
        print(f"  {path.name}  {seconds:4.1f} с  {text[:52]}…")

    print(f"\nЗаписано девять фраз, всего {total:.1f} с речи.")
    print("Дальше:")
    print("  python assets/make_reels.py")
    print("  python assets/assemble_voice.py")
    print("  python assets/mux_voice.py")


if __name__ == "__main__":
    main()
