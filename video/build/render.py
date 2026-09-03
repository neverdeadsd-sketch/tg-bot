# -*- coding: utf-8 -*-
"""Рендер кадров ролика и склейка в MP4 через ffmpeg."""
import json
import math
import os
import re
import subprocess
import sys

from PIL import Image, ImageDraw

import draw_kit
from draw_kit import font, centered, wrap, clamp, ease_out, seg, lerp
import scenes
from scenes import mix
from script_data import BLOCKS, PALETTE

W, H, FPS = 1920, 1080, 30
SS = 2                      # суперсэмплинг


class SDraw:
    """Обёртка над ImageDraw: принимает координаты в 1920x1080, рисует в SS-разрешении."""

    def __init__(self, raw, s):
        self.raw, self.s = raw, s

    def _p(self, xy):
        s = self.s
        if isinstance(xy[0], (list, tuple)):
            return [(p[0] * s, p[1] * s) for p in xy]
        return [v * s for v in xy]

    def _w(self, kw):
        if kw.get("width"):
            kw["width"] = max(1, int(round(kw["width"] * self.s)))
        return kw

    def line(self, xy, **kw):
        self.raw.line(self._p(xy), **self._w(kw))

    def rectangle(self, xy, **kw):
        self.raw.rectangle(self._p(xy), **self._w(kw))

    def polygon(self, xy, **kw):
        kw.pop("width", None)
        self.raw.polygon(self._p(xy), **kw)

    def ellipse(self, xy, **kw):
        self.raw.ellipse(self._p(xy), **self._w(kw))

    def pieslice(self, xy, start, end, **kw):
        self.raw.pieslice(self._p(xy), start, end, **self._w(kw))

    def rounded_rectangle(self, xy, radius=0, **kw):
        self.raw.rounded_rectangle(self._p(xy), radius=radius * self.s, **self._w(kw))

    def regular_polygon(self, bound, n, rotation=0, **kw):
        x, y, r = bound
        self.raw.regular_polygon((x * self.s, y * self.s, r * self.s), n, rotation=rotation,
                                 **self._w(kw))

    def text(self, xy, s, **kw):
        self.raw.text((xy[0] * self.s, xy[1] * self.s), s, **kw)

    def textbbox(self, xy, s, **kw):
        return self.raw.textbbox(xy, s, **kw)


# --- субтитры ---------------------------------------------------------------
def chunk_vo(text, limit=104):
    parts = re.split(r"(?<=[.!?:])\s+", text.strip())
    out = []
    for p in parts:
        if len(p) <= limit:
            out.append(p)
            continue
        buf = ""
        for piece in re.split(r"(?<=[,—])\s+", p):
            if len(buf) + len(piece) + 1 <= limit or not buf:
                buf = (buf + " " + piece).strip()
            else:
                out.append(buf)
                buf = piece
        if buf:
            out.append(buf)
    merged = []
    for p in out:
        if merged and len(merged[-1]) + len(p) + 1 <= limit:
            merged[-1] += " " + p
        else:
            merged.append(p)
    return merged


def sub_spans(text, speech_dur):
    ch = chunk_vo(text)
    tot = sum(len(c) for c in ch) or 1
    spans, acc = [], 0.0
    for c in ch:
        share = len(c) / tot * speech_dur
        spans.append((acc, acc + share, c))
        acc += share
    return spans


# --- хром кадра -------------------------------------------------------------
def draw_chrome(d, P, num, plaque, spans, tb, gp):
    d.text((100, 46), "PHOTOSHOP · С ЧЕМ ЕГО ЕДЯТ", font=font(25, False), fill=P["ink_soft"])
    lab = "%02d / 20" % num
    f = font(25, True)
    d.text((1820 - draw_kit.text_w(d, lab, f), 46), lab, font=f, fill=P["ink_soft"])
    d.line([100, 92, 1820, 92], fill=P["bg_deep"], width=2)

    a = ease_out(seg(tb, 0.0, 0.55) if tb < 0.5 else 1.0)
    y = 152 - 14 * (1 - a)
    centered(d, W / 2, y, plaque, font(58, True), mix(P["terra"], P["bg"], a))

    d.line([100, 872, 1820, 872], fill=P["bg_deep"], width=2)
    d.rectangle([0, H - 7, W, H], fill=P["bg_deep"])
    d.rectangle([0, H - 7, W * gp, H], fill=P["terra"])


def draw_subs(d, P, spans, tsec):
    cur = None
    for s0, s1, txt in spans:
        if s0 <= tsec < s1:
            cur = (s0, s1, txt)
            break
    if cur is None and spans and tsec >= spans[-1][1]:
        cur = spans[-1]
    if cur is None:
        return
    s0, s1, txt = cur
    a = ease_out(seg(tsec, s0, s0 + 0.18))
    f = font(38, False)
    lines = wrap(d, txt, f, 1420)[:2]
    y = 930 if len(lines) > 1 else 948
    for i, ln in enumerate(lines):
        centered(d, W / 2, y + i * 50, ln, f, mix(P["ink"], P["bg"], a))


# --- основной цикл ----------------------------------------------------------
def render_range(out, first, last, only=0):
    """Рендер блоков с индексами [first, last] включительно в отдельный файл."""
    tm = json.load(open(os.path.join(os.path.dirname(__file__), "timing.json")))
    frames = tm["frames"]
    speech = tm["speech"]

    draw_kit.S = SS
    P = PALETTE
    total = sum(frames)

    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.Popen(
        [ff, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H),
         "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-preset", "medium",
         "-crf", "19", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    done = sum(frames[:first])
    for bi, (num, _plan, plaque, vo, sid) in enumerate(BLOCKS):
        if not (first <= bi <= last):
            continue
        nf = frames[bi]
        spans = sub_spans(vo, speech[bi])
        fn = scenes.SCENES[sid]
        rng = range(nf) if not only else range(min(only, nf))
        for k in rng:
            img = Image.new("RGB", (W * SS, H * SS), P["bg"])
            raw = ImageDraw.Draw(img)
            d = SDraw(raw, SS)
            tb = (k + 0.5) / nf
            fn(d, tb, P)
            draw_chrome(d, P, num, plaque, spans, tb, (done + k) / total)
            draw_subs(d, P, spans, (k + 0.5) / FPS)
            proc.stdin.write(img.resize((W, H), Image.BOX).tobytes())
        done += nf
        print("блок %02d готов (%d кадров)" % (num, nf), flush=True)
    proc.stdin.close()
    proc.wait()
    print("ГОТОВО:", out)


if __name__ == "__main__":
    render_range(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]),
                 int(sys.argv[4]) if len(sys.argv) > 4 else 0)
