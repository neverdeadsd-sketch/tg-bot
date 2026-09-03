# -*- coding: utf-8 -*-
"""Подбор темпа речи и раскладка блоков по кадрам -> timing.json."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tts import Espeak
from script_data import BLOCKS

TARGET, MINPAD, FPS = 240.0, 0.5, 30
VOICE, PITCH, GAP = b"ru+m3", 40, 5


def main(vo_dir="/tmp/vo"):
    os.makedirs(vo_dir, exist_ok=True)
    chosen = None
    for rate in (150, 160, 170, 175, 180, 186, 192, 200):
        e = Espeak(voice=VOICE, rate=rate, pitch=PITCH, gap=GAP)
        ds = [e.say(vo, os.path.join(vo_dir, "%02d.wav" % n)) for n, _, _, vo, _ in BLOCKS]
        print("rate %3d -> речь %.1f с, свободно %.1f с" % (rate, sum(ds), TARGET - sum(ds)))
        if TARGET - sum(ds) >= MINPAD * len(BLOCKS):
            chosen = (rate, ds)
            break
    if not chosen:
        raise SystemExit("речь не влезает в хронометраж — сократите реплики")
    rate, ds = chosen
    extra = (TARGET - sum(ds)) - MINPAD * len(ds)
    w = sum(ds)
    frames = [round((d + MINPAD + extra * (d / w)) * FPS) for d in ds]
    frames[-1] += int(TARGET * FPS) - sum(frames)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "timing.json")
    json.dump({"rate": rate, "voice": VOICE.decode(), "fps": FPS,
               "speech": ds, "frames": frames}, open(out, "w"))
    print("выбран rate %d | кадров %d = %.1f с" % (rate, sum(frames), sum(frames) / FPS))


if __name__ == "__main__":
    main()
