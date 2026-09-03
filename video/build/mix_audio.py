# -*- coding: utf-8 -*-
"""Сборка дорожки: реплики раскладываются по началу своих блоков, хвост — тишина."""
import json
import os
import wave

SR = 22050
LEAD = 0.15          # небольшой вдох перед репликой


def main(vo_dir="/tmp/vo", out="/tmp/voice.wav"):
    tm = json.load(open(os.path.join(os.path.dirname(__file__), "timing.json")))
    frames, fps = tm["frames"], tm["fps"]
    total = sum(frames) / fps
    buf = bytearray(int(total * SR) * 2)
    pos_f = 0
    for i, nf in enumerate(frames):
        path = os.path.join(vo_dir, "%02d.wav" % (i + 1))
        with wave.open(path, "rb") as w:
            assert w.getframerate() == SR, (path, w.getframerate())
            data = w.readframes(w.getnframes())
        off = int((pos_f / fps + LEAD) * SR) * 2
        end = min(off + len(data), len(buf))
        buf[off:end] = data[:end - off]
        pos_f += nf
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(bytes(buf))
    print("дорожка:", out, "| %.2f с" % (len(buf) / 2 / SR))


if __name__ == "__main__":
    main()
