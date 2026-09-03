# -*- coding: utf-8 -*-
"""Тихая фоновая подложка: тёплый пад из синусов, аккорд меняется раз в 30 секунд."""
import numpy as np
import wave

SR, DUR, AMP = 44100, 240.0, 0.030
# восемь аккордов по 30 с: Am - F - C - G, дважды
CHORDS = [(220.00, 261.63, 329.63), (174.61, 220.00, 261.63),
          (196.00, 261.63, 329.63), (196.00, 246.94, 293.66)] * 2
SEGL = DUR / len(CHORDS)


def main(out="/tmp/pad.wav"):
    n = int(SR * DUR)
    t = np.arange(n) / SR
    mixdown = np.zeros(n, dtype=np.float64)
    for i, chord in enumerate(CHORDS):
        a, b = i * SEGL, (i + 1) * SEGL
        m = (t >= a - 2.0) & (t < b + 2.0)
        seg_t = t[m]
        env = np.clip((seg_t - (a - 2.0)) / 2.5, 0, 1) * np.clip(((b + 2.0) - seg_t) / 2.5, 0, 1)
        s = np.zeros_like(seg_t)
        for k, f in enumerate(chord):
            for det in (-0.6, 0.0, 0.6):          # лёгкая расстройка даёт «живой» тембр
                s += np.sin(2 * np.pi * (f + det) * seg_t) / (3.0 + k)
            s += 0.14 * np.sin(2 * np.pi * f * 2 * seg_t) / (3.0 + k)
        mixdown[m] += s * env
    # медленное «дыхание» громкости
    mixdown *= 0.85 + 0.15 * np.sin(2 * np.pi * t / 17.0)
    # мягкий срез верха
    k = 220
    ker = np.hanning(k) / np.hanning(k).sum()
    mixdown = np.convolve(mixdown, ker, mode="same")
    mixdown /= np.max(np.abs(mixdown)) + 1e-9
    # плавные вход и выход всего трека
    fade = int(SR * 3)
    mixdown[:fade] *= np.linspace(0, 1, fade)
    mixdown[-fade:] *= np.linspace(1, 0, fade)
    pcm = (mixdown * AMP * 32767).astype(np.int16)
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print("подложка:", out, "| %.1f с | пик %.3f" % (DUR, np.max(np.abs(mixdown)) * AMP))


if __name__ == "__main__":
    main()
