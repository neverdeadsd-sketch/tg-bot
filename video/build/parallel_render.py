# -*- coding: utf-8 -*-
"""Рендер блоков в четыре процесса и склейка сегментов в один файл."""
import json
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor

import imageio_ffmpeg

HERE = os.path.dirname(os.path.abspath(__file__))
SEG = "/tmp/seg"


def one(bi):
    out = os.path.join(SEG, "b%02d.mp4" % bi)
    subprocess.run([sys.executable, os.path.join(HERE, "render.py"), out, str(bi), str(bi)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    return bi, out


def main(final="/tmp/video_silent.mp4", workers=4):
    os.makedirs(SEG, exist_ok=True)
    n = len(json.load(open(os.path.join(HERE, "timing.json")))["frames"])
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for bi, out in ex.map(one, range(n)):
            print("блок %02d готов" % (bi + 1), flush=True)
    lst = os.path.join(SEG, "list.txt")
    with open(lst, "w") as f:
        for bi in range(n):
            f.write("file '%s/b%02d.mp4'\n" % (SEG, bi))
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", final], check=True)
    print("ГОТОВО:", final)


if __name__ == "__main__":
    main(*sys.argv[1:])
