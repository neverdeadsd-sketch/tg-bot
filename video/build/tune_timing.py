# -*- coding: utf-8 -*-
"""Подбор темпа речи и раскладка блоков по кадрам -> timing.json."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tts_piper import Piper
from script_data import BLOCKS

TARGET, MINPAD, FPS = 240.0, 0.5, 30
# (темп, максимальная пауза) — от самого естественного к более плотному;
# берём первый вариант, который укладывается в хронометраж
SCALES = ((1.00, 0.20), (1.00, 0.16), (0.98, 0.16), (0.96, 0.14),
          (0.94, 0.14), (0.92, 0.12), (0.88, 0.12))


def main(vo_dir="/tmp/vo"):
    os.makedirs(vo_dir, exist_ok=True)
    chosen = None
    for ls, gap in SCALES:
        p = Piper(length_scale=ls)
        ds = [p.say(vo, os.path.join(vo_dir, "%02d.wav" % n), max_gap=gap)
              for n, _, _, vo, _ in BLOCKS]
        free = TARGET - sum(ds)
        print("темп %.2f, пауза<=%.2f -> речь %.1f с, свободно %.1f с" % (ls, gap, sum(ds), free))
        if free >= MINPAD * len(BLOCKS):
            chosen = (ls, gap, ds)
            break
    if not chosen:
        raise SystemExit("речь не влезает в хронометраж — сократите реплики")
    ls, gap, ds = chosen
    extra = (TARGET - sum(ds)) - MINPAD * len(ds)
    w = sum(ds)
    frames = [round((d + MINPAD + extra * (d / w)) * FPS) for d in ds]
    frames[-1] += int(TARGET * FPS) - sum(frames)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "timing.json")
    json.dump({"engine": "piper", "voice": "ru-irinia-medium", "length_scale": ls,
               "max_gap": gap, "fps": FPS, "speech": ds, "frames": frames}, open(out, "w"))
    print("выбран темп %.2f (пауза<=%.2f) | кадров %d = %.1f с"
          % (ls, gap, sum(frames), sum(frames) / FPS))


if __name__ == "__main__":
    main()
