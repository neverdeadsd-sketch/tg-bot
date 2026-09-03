# -*- coding: utf-8 -*-
"""Мелкие помощники отрисовки: сглаживание, easing, фигуры, текст."""
import math
from PIL import Image, ImageDraw, ImageFont

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
S = 1          # коэффициент суперсэмплинга, выставляется рендерером
_font_cache = {}


def font(size, bold=True):
    """Размер задаётся в единицах 1920x1080; наружу отдаётся шрифт под текущий S."""
    key = (size, bold, S)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(FONT_BOLD if bold else FONT_REG, max(1, int(size * S)))
    return _font_cache[key]


# --- easing -----------------------------------------------------------------
def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def lerp(a, b, t):
    return a + (b - a) * t


def smooth(t):
    t = clamp(t)
    return t * t * (3 - 2 * t)


def ease_out(t, p=3):
    return 1 - (1 - clamp(t)) ** p


def ease_in_out(t):
    t = clamp(t)
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def back_out(t, s=1.70158):
    t = clamp(t) - 1
    return t * t * ((s + 1) * t + s) + 1


def seg(t, a, b):
    """Прогресс 0..1 внутри отрезка [a,b] общего прогресса t."""
    if b <= a:
        return 1.0 if t >= b else 0.0
    return clamp((t - a) / (b - a))


def pulse(t, a, b):
    """0→1→0 внутри отрезка."""
    p = seg(t, a, b)
    return math.sin(p * math.pi)


# --- фигуры -----------------------------------------------------------------
def rrect(d, box, r, fill=None, outline=None, width=3):
    x0, y0, x1, y1 = [int(v) for v in box]
    if x1 - x0 < 2 or y1 - y0 < 2:
        return
    r = int(min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    d.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=fill, outline=outline, width=width)


def circle(d, cx, cy, r, fill=None, outline=None, width=3):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill, outline=outline, width=width)


def ellipse(d, cx, cy, rx, ry, fill=None, outline=None, width=3):
    d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=fill, outline=outline, width=width)


def plate(d, cx, cy, rx, fill, edge, ry_ratio=0.26, width=4):
    """Тарелка в лёгкой изометрии."""
    ry = rx * ry_ratio
    ellipse(d, cx, cy, rx, ry, fill=fill, outline=edge, width=width)
    ellipse(d, cx, cy, rx * 0.72, ry * 0.72, fill=None, outline=edge, width=max(2, width - 2))


def dashed_rrect(d, box, r, color, width, dash, phase=0.0, progress=1.0):
    """Пунктирная рамка «бегущие муравьи» с прогрессом обводки."""
    x0, y0, x1, y1 = box
    pts = []
    steps = 260
    for i in range(steps + 1):
        u = i / steps
        peri = 2 * ((x1 - x0) + (y1 - y0))
        s = u * peri
        w, h = x1 - x0, y1 - y0
        if s <= w:
            pts.append((x0 + s, y0))
        elif s <= w + h:
            pts.append((x1, y0 + (s - w)))
        elif s <= 2 * w + h:
            pts.append((x1 - (s - w - h), y1))
        else:
            pts.append((x0, y1 - (s - 2 * w - h)))
    n = int(len(pts) * clamp(progress))
    for i in range(n - 1):
        if (int(i + phase) // dash) % 2 == 0:
            d.line([pts[i], pts[i + 1]], fill=color, width=width)


def grain(d, cx, cy, rx, ry, cols, rows, size, colors, gap=0.0, alpha_fn=None):
    """Сетка «крупинок» — используется и для пикселей, и для текстуры."""
    for j in range(rows):
        for i in range(cols):
            u = (i + 0.5) / cols
            v = (j + 0.5) / rows
            x = cx + (u - 0.5) * 2 * rx
            y = cy + (v - 0.5) * 2 * ry
            c = colors[(i * 7 + j * 3) % len(colors)]
            if alpha_fn is not None and not alpha_fn(i, j, u, v):
                continue
            s = size / 2
            d.rectangle([x - s, y - s, x + s - gap, y + s - gap], fill=c)


def pot(d, cx, cy, w, h, body, edge, lid=True):
    """Кастрюля."""
    rrect(d, [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], w * 0.12,
          fill=body, outline=edge, width=4)
    d.line([cx - w / 2 - 22, cy - h * 0.18, cx - w / 2, cy - h * 0.18], fill=edge, width=9)
    d.line([cx + w / 2, cy - h * 0.18, cx + w / 2 + 22, cy - h * 0.18], fill=edge, width=9)
    if lid:
        ellipse(d, cx, cy - h / 2, w / 2, w * 0.09, fill=body, outline=edge, width=4)


def bottle(d, cx, cy, w, h, body, edge):
    """Флакон для предметки."""
    bh = h * 0.68
    rrect(d, [cx - w / 2, cy - bh / 2, cx + w / 2, cy + bh / 2], w * 0.22,
          fill=body, outline=edge, width=4)
    nw = w * 0.30
    rrect(d, [cx - nw / 2, cy - bh / 2 - h * 0.20, cx + nw / 2, cy - bh / 2 + 6], nw * 0.3,
          fill=body, outline=edge, width=4)
    cw = w * 0.40
    rrect(d, [cx - cw / 2, cy - bh / 2 - h * 0.31, cx + cw / 2, cy - bh / 2 - h * 0.17], 6,
          fill=edge, outline=edge, width=2)


def figure(d, cx, cy, s, body, edge):
    """Силуэт человека."""
    circle(d, cx, cy - s * 0.72, s * 0.30, fill=body, outline=edge, width=4)
    d.pieslice([cx - s * 0.52, cy - s * 0.42, cx + s * 0.52, cy + s * 0.78],
               180, 360, fill=body, outline=edge, width=4)


def knife(d, cx, cy, ln, ang, blade, edge, handle):
    """Нож под углом ang (градусы)."""
    a = math.radians(ang)
    dx, dy = math.cos(a), math.sin(a)
    tip = (cx + dx * ln * 0.62, cy + dy * ln * 0.62)
    heel = (cx - dx * ln * 0.16, cy - dy * ln * 0.16)
    px, py = -dy, dx
    wid = ln * 0.085
    d.polygon([tip, (heel[0] + px * wid, heel[1] + py * wid),
               (heel[0] - px * wid * 0.35, heel[1] - py * wid * 0.35)],
              fill=blade, outline=edge)
    hx, hy = heel[0] - dx * ln * 0.30, heel[1] - dy * ln * 0.30
    d.line([heel, (hx, hy)], fill=handle, width=int(wid * 1.5))


# --- текст ------------------------------------------------------------------
def text_w(d, s, f):
    """Ширина в единицах 1920x1080."""
    return d.raw.textbbox((0, 0), s, font=f)[2] / S


def centered(d, cx, y, s, f, fill):
    bb = d.raw.textbbox((0, 0), s, font=f)
    d.text((cx - (bb[2] - bb[0]) / 2 / S - bb[0] / S, y - bb[1] / S), s, font=f, fill=fill)


def wrap(d, s, f, maxw):
    words, lines, cur = s.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if text_w(d, trial, f) <= maxw or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines
