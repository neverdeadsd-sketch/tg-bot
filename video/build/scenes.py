# -*- coding: utf-8 -*-
"""20 сцен ролика. Каждая функция рисует кадр по прогрессу t (0..1) внутри блока."""
import math
from draw_kit import (rrect, circle, ellipse, plate, dashed_rrect, grain, pot,
                      bottle, figure, knife, centered, font, seg, pulse, smooth,
                      ease_out, ease_in_out, back_out, clamp, lerp)

CX, CY = 960, 560           # центр сцены
STAGE = (200, 260, 1720, 860)


def mix(c1, c2, a):
    """Смешение цветов — так изображаем прозрачность на плоском фоне."""
    a = clamp(a)
    return tuple(int(round(c1[i] * a + c2[i] * (1 - a))) for i in range(3))


def button_grid(d, P, t, cols=13, rows=6, appear=True, keep=None, fade=0.0):
    """Панель управления: сетка кнопок. keep — индексы, которые остаются."""
    x0, x1 = 300, 1620
    y0, y1 = 320, 800
    bw = (x1 - x0) / cols
    bh = (y1 - y0) / rows
    accents = [P["steel"], P["steel"], P["brass"], P["steel"], P["terra"], P["olive"]]
    for j in range(rows):
        for i in range(cols):
            idx = j * cols + i
            if keep is not None and idx in keep:
                continue
            a = 1.0
            if appear:
                a = ease_out(seg(t, 0.02 + (idx % 29) * 0.012, 0.30 + (idx % 29) * 0.012))
            a *= (1 - fade)
            if a <= 0.02:
                continue
            cx = x0 + bw * (i + 0.5)
            cy = y0 + bh * (j + 0.5)
            w, h = bw * 0.72, bh * 0.52
            c = accents[(i * 3 + j * 5) % len(accents)]
            rrect(d, [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], h * 0.35,
                  fill=mix(c, P["bg"], 0.20 * a), outline=mix(c, P["bg"], 0.75 * a), width=3)
            if (i + j) % 3 == 0:
                circle(d, cx, cy, h * 0.16, fill=mix(c, P["bg"], 0.85 * a))


# --- 01 ---------------------------------------------------------------------
def s_panel(d, t, P):
    button_grid(d, P, t)
    a = ease_out(seg(t, 0.35, 0.6))
    if a > 0:
        figure(d, CX, 852 - 34 * a, 78, mix(P["ink"], P["bg"], 0.85 * a),
               mix(P["ink"], P["bg"], a))


# --- 02 ---------------------------------------------------------------------
def s_kitchen(d, t, P):
    button_grid(d, P, 1.0, appear=False, fade=ease_in_out(seg(t, 0.0, 0.32)))
    a = ease_out(seg(t, 0.26, 0.62))
    if a <= 0.01:
        return
    ink, edge = P["ink"], mix(P["ink"], P["bg"], a)
    # столешница
    y = 760
    rrect(d, [300, y, 1620, y + 26], 10, fill=mix(P["ink_soft"], P["bg"], a))
    # кастрюли
    for i, (x, w, h) in enumerate(((520, 190, 130), (760, 150, 105), (1180, 210, 145))):
        aa = ease_out(seg(t, 0.34 + i * 0.07, 0.66 + i * 0.07))
        if aa > 0.01:
            pot(d, x, y - h / 2 - 8, w, h, mix(P["terra"] if i != 1 else P["olive"], P["bg"], 0.30 * aa),
                mix(P["ink"], P["bg"], aa))
    # рейка с ножами
    ar = ease_out(seg(t, 0.46, 0.80))
    if ar > 0.01:
        rrect(d, [880, 330, 1420, 344], 7, fill=mix(P["ink_soft"], P["bg"], ar))
        for k in range(4):
            knife(d, 930 + k * 150, 400, 150, 90, mix(P["steel"], P["bg"], 0.55 * ar),
                  mix(P["ink"], P["bg"], ar), mix(P["ink"], P["bg"], 0.9 * ar))
    # вытяжка
    ah = ease_out(seg(t, 0.40, 0.75))
    if ah > 0.01:
        d.polygon([(400, 300), (760, 300), (700, 400), (460, 400)],
                  fill=mix(P["steel"], P["bg"], 0.25 * ah), outline=mix(P["ink"], P["bg"], ah))


# --- 03 ---------------------------------------------------------------------
def s_grain(d, t, P):
    cols_pal = [P["terra"], P["brass"], P["olive"], P["steel"], P["ink_soft"]]
    a1 = 1 - ease_in_out(seg(t, 0.42, 0.60))
    if a1 > 0.01:  # миска с крупой
        ellipse(d, CX, CY + 60, 300 * a1 + 1, 110 * a1 + 1,
                fill=mix(P["cream"], P["bg"], a1), outline=mix(P["ink"], P["bg"], a1), width=5)
        grain(d, CX, CY + 40, 250 * a1, 60 * a1, 26, 7, 14 * a1 + 1,
              [mix(c, P["bg"], a1) for c in cols_pal])
    a2 = ease_in_out(seg(t, 0.50, 0.78))
    if a2 > 0.01:  # мозаика складывается в лицо
        n = 22
        rx, ry = 210 * a2, 250 * a2
        px, py = 2 * rx / n, 2 * ry / n
        if px < 1.5 or py < 1.5:
            return
        gap = min(2.0, px * 0.3, py * 0.3)

        def face(i, j, u, v):
            dx, dy = (u - 0.5) * 2, (v - 0.5) * 2
            if dx * dx + (dy * 1.15) ** 2 > 0.92:
                return False
            return True

        for j in range(n):
            for i in range(n):
                u, v = (i + 0.5) / n, (j + 0.5) / n
                if not face(i, j, u, v):
                    continue
                dx, dy = (u - 0.5) * 2, (v - 0.5) * 2
                eye = (abs(abs(dx) - 0.34) < 0.11 and abs(dy + 0.16) < 0.10)
                mouth = (abs(dy - 0.42) < 0.07 and abs(dx) < 0.28)
                base = P["ink"] if (eye or mouth) else cols_pal[(i * 5 + j * 3) % len(cols_pal)]
                sh = 0.55 + 0.35 * (1 - v)
                c = mix(base, P["bg"], (0.30 + 0.55 * sh) * a2)
                x = CX + (u - 0.5) * 2 * rx
                y = CY + (v - 0.5) * 2 * ry - 20
                d.rectangle([x - px / 2, y - py / 2, x + px / 2 - gap, y + py / 2 - gap], fill=c)


# --- 04 ---------------------------------------------------------------------
def s_crates(d, t, P):
    board_a = ease_out(seg(t, 0.05, 0.3))
    rrect(d, [1300, 620, 1660, 700], 14, fill=mix(P["cream"], P["bg"], board_a),
          outline=mix(P["ink"], P["bg"], board_a), width=5)
    labels = ("камера", "сканер", "нейросеть")
    for i in range(3):
        p = ease_out(seg(t, 0.10 + i * 0.13, 0.58 + i * 0.13))
        if p <= 0.01:
            continue
        x = lerp(120, 380 + i * 300, p)
        y = 620
        rrect(d, [x - 120, y - 130, x + 120, y + 10], 16,
              fill=mix(P["brass"], P["bg"], 0.22 * p), outline=mix(P["ink"], P["bg"], p), width=5)
        ec = mix(P["ink"], P["bg"], p)
        if i == 0:      # камера
            rrect(d, [x - 62, y - 100, x + 62, y - 26], 10, fill=None, outline=ec, width=5)
            circle(d, x, y - 63, 24, fill=None, outline=ec, width=5)
        elif i == 1:    # сканер
            rrect(d, [x - 66, y - 96, x + 66, y - 32], 8, fill=None, outline=ec, width=5)
            d.line([x - 46, y - 64, x + 46, y - 64], fill=mix(P["terra"], P["bg"], p), width=6)
        else:           # нейросеть — искра
            for k in range(8):
                a = k * math.pi / 4
                d.line([x + math.cos(a) * 16, y - 64 + math.sin(a) * 16,
                        x + math.cos(a) * 44, y - 64 + math.sin(a) * 44], fill=ec, width=5)
        centered(d, x, y + 26, labels[i], font(28, False), mix(P["ink_soft"], P["bg"], p))


# --- 05 / 06 ----------------------------------------------------------------
def _plate_stack(d, P, spread, items_a=1.0, pulled=None, pull=0.0):
    names = ("ФОН", "МОДЕЛЬ", "ЛОГОТИП", "ТЕКСТ")
    cols = (P["steel"], P["terra"], P["brass"], P["olive"])
    for i in range(4):
        gy = CY + 190 - i * (34 + 118 * spread)
        gx = CX + (240 * pull if pulled == i else 0)
        a = items_a
        plate(d, gx, gy, 330, mix(P["cream"], P["bg"], a), mix(P["ink"], P["bg"], a), width=5)
        c = mix(cols[i], P["bg"], a)
        if i == 0:
            rrect(d, [gx - 150, gy - 46, gx + 150, gy - 6], 8, fill=c)
        elif i == 1:
            figure(d, gx, gy - 4, 62, c, mix(P["ink"], P["bg"], a))
        elif i == 2:
            circle(d, gx, gy - 26, 30, fill=None, outline=c, width=9)
        else:
            for k in range(2):
                rrect(d, [gx - 120 + k * 26, gy - 44 + k * 26, gx + 120 - k * 40, gy - 26 + k * 26],
                      6, fill=c)
        centered(d, gx + 430, gy - 34, names[i], font(30, True), mix(P["ink_soft"], P["bg"], a))


def s_layers(d, t, P):
    _plate_stack(d, P, ease_in_out(seg(t, 0.12, 0.62)))


def s_layers_pull(d, t, P):
    p = pulse(t, 0.15, 0.72)
    _plate_stack(d, P, 1.0, pulled=1, pull=ease_in_out(p))


# --- 07 ---------------------------------------------------------------------
def s_knife(d, t, P):
    for i, x in enumerate((520, 960, 1400)):
        hero = (i == 1)
        a = 1.0 if hero else 0.42
        bottle(d, x, CY + 20, 150 if hero else 130, 320 if hero else 280,
               mix(P["olive"] if hero else P["steel"], P["bg"], 0.28 * a),
               mix(P["ink"], P["bg"], a))
    box = [960 - 105, CY - 165, 960 + 105, CY + 185]
    pr = ease_in_out(seg(t, 0.22, 0.70))
    dashed_rrect(d, box, 0, P["terra"], 5, 11, phase=t * 260, progress=pr)
    kp = seg(t, 0.22, 0.70)
    if 0 < kp < 1:
        peri = 2 * ((box[2] - box[0]) + (box[3] - box[1]))
        s = ease_in_out(kp) * peri
        w, h = box[2] - box[0], box[3] - box[1]
        if s <= w:
            kx, ky, ang = box[0] + s, box[1], 90
        elif s <= w + h:
            kx, ky, ang = box[2], box[1] + (s - w), 180
        elif s <= 2 * w + h:
            kx, ky, ang = box[2] - (s - w - h), box[3], 270
        else:
            kx, ky, ang = box[0], box[3] - (s - 2 * w - h), 0
        knife(d, kx, ky, 190, ang, P["steel"], P["ink"], P["ink"])


# --- 08 ---------------------------------------------------------------------
def s_stencil(d, t, P):
    plate(d, CX, CY + 170, 330, P["cream"], P["ink"], width=5)
    circle(d, CX, CY + 150, 96, fill=mix(P["olive"], P["bg"], 0.35), outline=P["ink"], width=4)
    drop = ease_in_out(seg(t, 0.10, 0.34))
    lift = ease_in_out(seg(t, 0.72, 0.95))
    sy = lerp(200, 440, drop)
    sy = lerp(sy, 150, lift)
    holes = [(-120, 0), (0, 0), (120, 0), (-60, 46), (60, 46)]
    rrect(d, [CX - 260, sy - 60, CX + 260, sy + 60], 14,
          fill=P["bg_deep"], outline=P["ink"], width=5)
    for hx, hy in holes:
        circle(d, CX + hx, sy + hy * 0.3, 22, fill=P["bg"], outline=P["ink"], width=3)
    fall = seg(t, 0.36, 0.72)
    if 0 < fall < 1:
        for k in range(34):
            hx, hy = holes[k % len(holes)]
            ph = (fall * 2.4 + k * 0.09) % 1.0
            py = sy + 30 + ph * (CY + 140 - sy)
            if py > CY + 150:
                continue
            c = (P["terra"], P["brass"], P["olive"])[k % 3]
            d.rectangle([CX + hx - 5, py - 5, CX + hx + 5, py + 5], fill=c)


# --- 09 ---------------------------------------------------------------------
def s_hide(d, t, P):
    plate(d, CX, CY + 150, 360, P["cream"], P["ink"], width=5)
    grain(d, CX, CY + 80, 250, 90, 20, 7, 20, [P["terra"], P["brass"], P["olive"], P["steel"]])
    p = pulse(t, 0.14, 0.86)
    w = ease_in_out(p) * 760
    if w > 2:
        x0 = CX - 380
        d.rectangle([x0, CY - 60, x0 + w, CY + 230], fill=P["ink"])
        centered(d, x0 + w / 2, CY + 60, "СКРЫТО", font(40, True), P["bg"]) if w > 260 else None


# --- 10 ---------------------------------------------------------------------
def s_spices(d, t, P):
    warm = ease_in_out(seg(t, 0.42, 0.80))
    base = mix(P["steel"], P["bg"], 0.30)
    hot = mix(P["terra"], P["bg"], 0.55)
    plate(d, CX, CY + 190, 340, mix(base, hot, 1 - warm), P["ink"], width=5)
    circle(d, CX, CY + 168, 104, fill=mix(mix(P["steel"], P["bg"], 0.5),
                                          mix(P["brass"], P["bg"], 0.75), warm),
           outline=P["ink"], width=4)
    names = ("ЯРКОСТЬ", "КОНТРАСТ", "ТОН", "НАСЫЩ.")
    cols = (P["brass"], P["ink_soft"], P["terra"], P["olive"])
    for i in range(4):
        a = ease_out(seg(t, 0.06 + i * 0.07, 0.34 + i * 0.07))
        if a <= 0.01:
            continue
        x = 460 + i * 340
        tip = ease_in_out(seg(t, 0.40, 0.62)) if i == 2 else 0.0
        yy = CY - 190 - 30 * tip
        ang = -26 * tip
        rr = 60
        d.regular_polygon((x, yy, rr), 4, rotation=ang,
                          fill=mix(cols[i], P["bg"], 0.35 * a), outline=mix(P["ink"], P["bg"], a))
        centered(d, x, yy + 78, names[i], font(26, True), mix(P["ink_soft"], P["bg"], a))
        if i == 2 and tip > 0.15:
            for k in range(16):
                ph = (tip * 1.8 + k * 0.06) % 1.0
                py = yy + 60 + ph * (CY + 120 - yy)
                d.rectangle([x + 30 - k % 5 * 12, py - 4, x + 38 - k % 5 * 12, py + 4],
                            fill=P["terra"])


# --- 11 ---------------------------------------------------------------------
def s_adj_layer(d, t, P):
    lift = ease_in_out(seg(t, 0.52, 0.88))
    tint = 1 - lift
    plate(d, CX, CY + 200, 340, mix(P["cream"], P["terra"], 0.45 * tint), P["ink"], width=5)
    circle(d, CX, CY + 178, 100, fill=mix(mix(P["olive"], P["bg"], 0.4), P["terra"], 0.55 * tint),
           outline=P["ink"], width=4)
    sy = lerp(CY - 10, CY - 330, lift)
    rrect(d, [CX - 300, sy - 46, CX + 300, sy + 46], 12,
          fill=mix(P["terra"], P["bg"], 0.34), outline=P["terra"], width=4)
    centered(d, CX, sy - 16, "КОРРЕКТИРУЮЩИЙ СЛОЙ", font(30, True), P["ink"])
    for k in range(3):
        yy = sy + 70 + k * 16
        if yy < CY + 120:
            d.line([CX - 60 + k * 20, yy, CX + 60 - k * 20, yy],
                   fill=mix(P["terra"], P["bg"], 0.5 * (1 - lift)), width=4)


# --- 12 ---------------------------------------------------------------------
def s_patch(d, t, P):
    rrect(d, [CX - 420, CY - 200, CX + 420, CY + 240], 40,
          fill=mix(P["brass"], P["bg"], 0.30), outline=P["ink"], width=5)
    grain(d, CX, CY + 20, 380, 190, 30, 15, 8, [mix(P["brass"], P["bg"], 0.42),
                                                mix(P["brass"], P["bg"], 0.34),
                                                mix(P["terra"], P["bg"], 0.22)])
    spot = (CX + 110, CY - 40)
    healed = ease_in_out(seg(t, 0.60, 0.80))
    if healed < 0.99:
        circle(d, spot[0], spot[1], 30 * (1 - healed) + 1,
               fill=mix(P["ink"], P["bg"], 0.85 * (1 - healed)))
    src = (CX - 250, CY + 120)
    mv = ease_in_out(seg(t, 0.30, 0.60))
    if seg(t, 0.16, 0.95) > 0:
        px = lerp(src[0], spot[0], mv)
        py = lerp(src[1], spot[1], mv)
        a = 1 - ease_in_out(seg(t, 0.80, 0.96))
        if a > 0.01:
            rrect(d, [px - 44, py - 44, px + 44, py + 44], 12,
                  fill=mix(P["brass"], P["bg"], 0.40 * a), outline=mix(P["olive"], P["bg"], a), width=4)
        if mv < 1:
            dashed_rrect(d, [src[0] - 44, src[1] - 44, src[0] + 44, src[1] + 44], 0,
                         P["olive"], 3, 8, phase=t * 200)


# --- 13 ---------------------------------------------------------------------
def s_sieve(d, t, P):
    pot(d, CX, 350, 260, 150, mix(P["steel"], P["bg"], 0.3), P["ink"], lid=False)
    pour = seg(t, 0.14, 0.86)
    # сито
    rrect(d, [CX - 270, 500, CX + 270, 534], 14, fill=mix(P["steel"], P["bg"], 0.35),
          outline=P["ink"], width=4)
    for k in range(15):
        d.line([CX - 248 + k * 35, 503, CX - 248 + k * 35, 531], fill=P["ink"], width=2)
    if pour > 0:
        d.line([CX, 420, CX, 500], fill=mix(P["brass"], P["bg"], 0.7), width=24)
    lp, rp = CX - 330, CX + 330
    for side, x, lab in ((0, lp, "ЦВЕТ И ТЕНИ"), (1, rp, "ТЕКСТУРА")):
        pot(d, x, 700, 310, 200, mix(P["cream"], P["bg"], 0.9), P["ink"], lid=False)
        fill = ease_in_out(seg(t, 0.24 + side * 0.06, 0.88))
        if fill > 0.02:
            h = 145 * fill
            if side == 0:
                for k in range(10):
                    circle(d, x - 105 + (k % 5) * 52, 768 - (k // 5) * 46, 30 * fill + 1,
                           fill=mix((P["terra"], P["olive"], P["brass"])[k % 3], P["bg"], 0.45))
            else:
                grain(d, x, 776 - h / 2, 130, h / 2, 18, max(2, int(h / 12)), 8,
                      [mix(P["ink"], P["bg"], 0.55), mix(P["ink_soft"], P["bg"], 0.5)])
        centered(d, x, 828, lab, font(27, True), P["ink_soft"])


# --- 14 ---------------------------------------------------------------------
def s_composite(d, t, P):
    xs = (420, 700, 980, 1260)
    parts = ("блик", "форма", "цвет", "резкость")
    fly = ease_in_out(seg(t, 0.42, 0.80))
    for i, x in enumerate(xs):
        a = ease_out(seg(t, 0.04 + i * 0.06, 0.30 + i * 0.06)) * (1 - 0.55 * fly)
        if a <= 0.01:
            continue
        bottle(d, x, CY, 120, 260, mix(P["steel"], P["bg"], 0.22 * a), mix(P["ink"], P["bg"], a))
        centered(d, x, CY + 170, parts[i], font(26, False), mix(P["ink_soft"], P["bg"], a))
    tx = 1560
    for i, x in enumerate(xs):
        p = ease_in_out(seg(t, 0.42 + i * 0.05, 0.80 + i * 0.05))
        if p <= 0.01:
            continue
        px, py = lerp(x, tx, p), lerp(CY - 60 + i * 34, CY - 40, p)
        rrect(d, [px - 34, py - 22, px + 34, py + 22], 8,
              fill=mix(P["brass"], P["bg"], 0.55), outline=P["ink"], width=3)
    done = ease_out(seg(t, 0.72, 0.94))
    if done > 0.01:
        plate(d, tx, CY + 190, 200, mix(P["cream"], P["bg"], done), mix(P["ink"], P["bg"], done), width=5)
        bottle(d, tx, CY + 30, 150, 300, mix(P["olive"], P["bg"], 0.32 * done),
               mix(P["ink"], P["bg"], done))


# --- 15 ---------------------------------------------------------------------
def s_smart(d, t, P):
    dr = ease_out(seg(t, 0.02, 0.22))
    rrect(d, [300, 300, 700, 470], 16, fill=mix(P["cold"], P["bg"], 0.22 * dr),
          outline=mix(P["ink"], P["bg"], dr), width=5)
    d.line([340, 385 + 30 * dr, 660, 385 + 30 * dr], fill=mix(P["cold"], P["bg"], dr), width=8)
    centered(d, 500, 500, "МОРОЗИЛКА", font(28, True), mix(P["ink_soft"], P["bg"], dr))
    sx, sy, rot = 1.0, 1.0, 0.0
    sx = lerp(1.0, 0.42, pulse(t, 0.24, 0.44))
    sy = lerp(1.0, 1.45, pulse(t, 0.46, 0.64))
    rot = 28 * pulse(t, 0.64, 0.82)
    w, h = 300 * sx, 220 * sy
    cx, cy = 1220, CY + 40
    box = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    a = math.radians(rot)
    pts = [(cx + px * math.cos(a) - py * math.sin(a), cy + px * math.sin(a) + py * math.cos(a))
           for px, py in box]
    d.polygon(pts, fill=mix(P["cold"], P["bg"], 0.30), outline=P["ink"])
    for k in range(3):
        d.line([pts[0], pts[2]] if k == 1 else [pts[1], pts[3]],
               fill=mix(P["cold"], P["bg"], 0.55), width=3)
    snap = ease_out(seg(t, 0.84, 0.97))
    if snap > 0.3:
        dashed_rrect(d, [cx - 155, cy - 115, cx + 155, cy + 115], 0, P["olive"], 4, 10, phase=t * 220)


# --- 16 ---------------------------------------------------------------------
def s_rgbcmyk(d, t, P):
    d.line([CX, 300, CX, 830], fill=mix(P["ink_soft"], P["bg"], 0.4), width=3)
    la = ease_out(seg(t, 0.06, 0.34))
    if la > 0.01:
        for r in range(5, 0, -1):
            circle(d, 620, CY + 60, 150 + r * 26, fill=mix(P["brass"], P["bg"], 0.06 * r * la))
        plate(d, 620, CY + 190, 250, mix(P["cream"], P["bg"], la), mix(P["ink"], P["bg"], la), width=5)
        circle(d, 620, CY + 160, 88, fill=mix(P["terra"], P["bg"], 0.75 * la), outline=P["ink"], width=4)
        centered(d, 620, CY + 280, "RGB — СВЕТИТСЯ", font(32, True), mix(P["ink"], P["bg"], la))
    ar = ease_out(seg(t, 0.44, 0.78))
    if ar > 0.01:
        rrect(d, [1130, CY - 40, 1690, CY + 250], 16, fill=mix(P["cream"], P["bg"], ar),
              outline=mix(P["ink"], P["bg"], ar), width=5)
        for j in range(9):
            for i in range(18):
                rr = 4 + 4 * ((i + j) % 3)
                circle(d, 1180 + i * 29, CY + j * 26, rr * ar,
                       fill=mix((P["terra"], P["olive"], P["steel"])[(i + j) % 3], P["bg"], 0.7 * ar))
        centered(d, 1410, CY + 280, "CMYK — КРАСКА", font(32, True), mix(P["ink"], P["bg"], ar))
    p = ease_in_out(seg(t, 0.36, 0.60))
    if 0 < p < 1:
        ax = lerp(800, 1100, p)
        d.line([800, CY + 60, ax, CY + 60], fill=P["terra"], width=8)
        d.polygon([(ax + 26, CY + 60), (ax - 6, CY + 42), (ax - 6, CY + 78)], fill=P["terra"])


# --- 17 ---------------------------------------------------------------------
def s_serving(d, t, P):
    tilt = ease_in_out(seg(t, 0.60, 0.92))
    for i, side in enumerate((-1, 1)):
        a = ease_out(seg(t, 0.08 + i * 0.10, 0.38 + i * 0.10)) * (1 - tilt)
        if a > 0.01:
            x = CX + side * lerp(520, 330, a)
            d.line([x, CY + 40, x, CY + 240], fill=mix(P["ink"], P["bg"], a), width=8)
            if side < 0:
                for k in range(3):
                    d.line([x - 16 + k * 16, CY - 30, x - 16 + k * 16, CY + 46],
                           fill=mix(P["ink"], P["bg"], a), width=6)
            else:
                knife(d, x, CY - 10, 130, 90, mix(P["steel"], P["bg"], 0.5 * a),
                      mix(P["ink"], P["bg"], a), mix(P["ink"], P["bg"], a))
    an = ease_out(seg(t, 0.24, 0.50)) * (1 - tilt)
    if an > 0.01:
        d.polygon([(CX - 470, CY + 250), (CX - 300, CY + 190), (CX - 250, CY + 300)],
                  fill=mix(P["olive"], P["bg"], 0.3 * an), outline=mix(P["ink"], P["bg"], an))
    h = lerp(0.30, 1.0, tilt)
    ph = 250 * h
    rrect(d, [CX - 190, CY + 200 - ph, CX + 190, CY + 200 + 40], 14,
          fill=P["cream"], outline=P["ink"], width=5)
    if tilt > 0.25:
        a = (tilt - 0.25) / 0.75
        centered(d, CX, CY + 210 - ph + 34, "ОБЛОЖКА", font(int(34 * a) + 1, True),
                 mix(P["terra"], P["bg"], a))
        for k in range(3):
            d.line([CX - 130, CY + 300 - ph + k * 30, CX + 130 - k * 46, CY + 300 - ph + k * 30],
                   fill=mix(P["ink_soft"], P["bg"], a), width=6)
    else:
        circle(d, CX, CY + 150, 70, fill=mix(P["terra"], P["bg"], 0.4), outline=P["ink"], width=4)


# --- 18 ---------------------------------------------------------------------
def s_export(d, t, P):
    la = ease_out(seg(t, 0.04, 0.30))
    if la > 0.01:
        for i, (x, y, w, h) in enumerate(((420, 700, 190, 130), (620, 720, 150, 110),
                                          (500, 560, 210, 140), (720, 570, 130, 100))):
            pot(d, x, y, w * la, h * la, mix((P["terra"], P["olive"], P["steel"], P["brass"])[i],
                                             P["bg"], 0.28 * la), mix(P["ink"], P["bg"], la))
        centered(d, 560, 830, "PSD / TIFF — СЕБЕ", font(34, True), mix(P["ink"], P["bg"], la))
    d.line([980, 300, 980, 860], fill=mix(P["ink_soft"], P["bg"], 0.35), width=3)
    dr = ease_out(seg(t, 0.30, 0.52))
    if dr > 0.01:
        rrect(d, [1520, 340, 1720, 800], 12, fill=mix(P["bg_deep"], P["bg"], dr),
              outline=mix(P["ink"], P["bg"], dr), width=5)
        circle(d, 1552, 580, 9, fill=mix(P["ink"], P["bg"], dr))
    p = ease_in_out(seg(t, 0.46, 0.86))
    if p > 0.01:
        x = lerp(1120, 1560, p)
        plate(d, x, 700, 150, P["cream"], P["ink"], width=5)
        d.pieslice([x - 130, 580, x + 130, 760], 180, 360,
                   fill=mix(P["steel"], P["bg"], 0.35), outline=P["ink"], width=5)
        circle(d, x, 578, 12, fill=P["ink"])
        centered(d, 1300, 830, "JPEG / PNG — ГОСТЯМ", font(34, True), mix(P["ink"], P["bg"], p))


# --- 19 ---------------------------------------------------------------------
def s_usecases(d, t, P):
    caps = ("ПОРТРЕТ\nи ретушь", "ПРЕДМЕТКА\nи каталог", "ОБЛОЖКА\nи реклама",
            "КОЛЛАЖ\nи композит", "МАКЕТ\nв печать")
    cols = (P["terra"], P["olive"], P["brass"], P["steel"], P["ink_soft"])
    for i in range(5):
        p = back_out(seg(t, 0.06 + i * 0.11, 0.34 + i * 0.11))
        if p <= 0.02:
            continue
        x = 320 + i * 330
        w, h = 130 * p, 150 * p
        rrect(d, [x - w, CY - h, x + w, CY + h], 18 * p,
              fill=mix(cols[i], P["bg"], 0.18), outline=mix(cols[i], P["bg"], 0.9), width=5)
        if i == 0:
            figure(d, x, CY - 6, 66 * p, mix(cols[i], P["bg"], 0.45), mix(P["ink"], P["bg"], p))
        elif i == 1:
            bottle(d, x, CY - 6, 74 * p, 150 * p, mix(cols[i], P["bg"], 0.4), mix(P["ink"], P["bg"], p))
        elif i == 2:
            rrect(d, [x - 60 * p, CY - 80 * p, x + 60 * p, CY + 60 * p], 8,
                  fill=None, outline=mix(P["ink"], P["bg"], p), width=5)
            d.line([x - 36 * p, CY + 16 * p, x + 36 * p, CY + 16 * p],
                   fill=mix(cols[i], P["bg"], p), width=8)
        elif i == 3:
            for k in range(3):
                rrect(d, [x - 66 * p + k * 22 * p, CY - 60 * p + k * 22 * p,
                          x + 20 * p + k * 22 * p, CY + 30 * p + k * 22 * p], 6,
                      fill=mix(cols[i], P["bg"], 0.30), outline=mix(P["ink"], P["bg"], p), width=3)
        else:
            rrect(d, [x - 62 * p, CY - 74 * p, x + 62 * p, CY + 66 * p], 6,
                  fill=P["cream"], outline=mix(P["ink"], P["bg"], p), width=4)
            for k in range(4):
                d.line([x - 40 * p, CY - 40 * p + k * 30 * p, x + 40 * p - k * 12 * p,
                        CY - 40 * p + k * 30 * p], fill=mix(cols[i], P["bg"], 0.8), width=5)
        for li, line in enumerate(caps[i].split("\n")):
            centered(d, x, CY + 180 + li * 34, line, font(27, li == 0),
                     mix(P["ink"] if li == 0 else P["ink_soft"], P["bg"], p))


# --- 20 ---------------------------------------------------------------------
def s_four(d, t, P):
    collapse = ease_in_out(seg(t, 0.10, 0.55))
    button_grid(d, P, 1.0, appear=False, fade=collapse)
    show = ease_out(seg(t, 0.45, 0.78))
    if show <= 0.01:
        return
    names = ("СЛОИ", "ВЫДЕЛЕНИЕ", "МАСКА", "КОРРЕКЦИЯ")
    cols = (P["terra"], P["olive"], P["brass"], P["steel"])
    for i in range(4):
        p = back_out(seg(t, 0.45 + i * 0.07, 0.78 + i * 0.07))
        if p <= 0.02:
            continue
        x = 390 + i * 393
        w, h = 165 * p, 90 * p
        rrect(d, [x - w, CY - h, x + w, CY + h], 22 * p,
              fill=mix(cols[i], P["bg"], 0.22), outline=mix(cols[i], P["bg"], 1.0), width=6)
        centered(d, x, CY - 20 * p, names[i], font(max(1, int(36 * p)), True),
                 mix(P["ink"], P["bg"], p))


SCENES = {
    "panel": s_panel, "kitchen": s_kitchen, "grain": s_grain, "crates": s_crates,
    "layers": s_layers, "layers_pull": s_layers_pull, "knife": s_knife,
    "stencil": s_stencil, "hide": s_hide, "spices": s_spices, "adj_layer": s_adj_layer,
    "patch": s_patch, "sieve": s_sieve, "composite": s_composite, "smart": s_smart,
    "rgbcmyk": s_rgbcmyk, "serving": s_serving, "export": s_export,
    "usecases": s_usecases, "four": s_four,
}
