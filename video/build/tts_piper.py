# -*- coding: utf-8 -*-
"""Нейросетевой русский синтез через Piper (модель ru-irinia-medium, ONNX, офлайн)."""
import os
import re
import wave

import numpy as np

VOICE_DIR = os.environ.get("PIPER_VOICE_DIR", "/tmp/piper")
MODEL = os.path.join(VOICE_DIR, "ru-irinia-medium.onnx")
CONFIG = MODEL + ".json"

# Латиницу и аббревиатуры фонемизатор читает как попало — проговариваем их кириллицей.
# В субтитрах при этом остаётся исходное написание.
SAY_AS = [
    (r"\bPhotoshop\b", "Фотошоп"),
    (r"\bPSD\b", "пи-эс-ди"),
    (r"\bTIFF\b", "тиф"),
    (r"\bJPEG\b", "джейпег"),
    (r"\bPNG\b", "пи-эн-джи"),
    (r"\bRGB\b", "эр-джи-би"),
    (r"\bCMYK\b", "си-эм-уай-кей"),
]


def for_tts(text):
    for pat, rep in SAY_AS:
        text = re.sub(pat, rep, text)
    return text


class Piper:
    def __init__(self, length_scale=1.0, noise_scale=0.667, noise_w_scale=0.8):
        from piper import PiperVoice, SynthesisConfig
        if not os.path.exists(MODEL):
            raise SystemExit("нет модели голоса: %s — запустите fetch_voice.sh" % MODEL)
        self.voice = PiperVoice.load(MODEL, config_path=CONFIG)
        self.cfg = SynthesisConfig(length_scale=length_scale,
                                   noise_scale=noise_scale,
                                   noise_w_scale=noise_w_scale)
        self.rate_hz = self.voice.config.sample_rate

    def say(self, text, path, max_gap=None, head_tail=0.06):
        with wave.open(path, "wb") as w:
            self.voice.synthesize_wav(for_tts(text), w, syn_config=self.cfg)
        if max_gap is not None:
            squeeze_pauses(path, max_gap=max_gap, head_tail=head_tail)
        with wave.open(path) as w:
            return w.getnframes() / w.getframerate()


def squeeze_pauses(path, max_gap=0.22, head_tail=0.06, thresh=0.012):
    """Укорачивает паузы длиннее max_gap, не трогая сам темп речи."""
    with wave.open(path) as w:
        sr, n = w.getframerate(), w.getnframes()
        a = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    win = max(1, int(sr * 0.01))
    pad = (-len(a)) % win
    env = np.abs(np.pad(a, (0, pad))).reshape(-1, win).max(axis=1)
    loud = env > thresh
    if not loud.any():
        return
    keep = np.ones(len(env), dtype=bool)
    i, gap_win, ht_win = 0, max(1, int(max_gap / 0.01)), max(1, int(head_tail / 0.01))
    while i < len(env):
        if loud[i]:
            i += 1
            continue
        j = i
        while j < len(env) and not loud[j]:
            j += 1
        run = j - i
        limit = ht_win if (i == 0 or j >= len(env)) else gap_win
        if run > limit:
            keep[i + limit:j] = False
        i = j
    mask = np.repeat(keep, win)[:len(a)]
    out = (a[mask] * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(out.tobytes())


if __name__ == "__main__":
    p = Piper()
    print("sample rate:", p.rate_hz)
    print("%.2f с" % p.say("Экспорт — подача. PSD и TIFF — твоя кухня. "
                           "JPEG или PNG — одна тарелка, которую выносишь гостям.",
                           "/tmp/piper_check.wav"))
