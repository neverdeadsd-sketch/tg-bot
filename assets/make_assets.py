"""Фирменная графика Brief: аватары и приветственный баннер.

Всё рисуется кодом — типографика остаётся чёткой, правки бесплатны.
Гарнитура: Inter Display (SIL OFL, лежит в assets/fonts).

    pip install Pillow
    python assets/make_assets.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ASSETS = Path(__file__).resolve().parent
FONTS = ASSETS / "fonts"

SEMIBOLD = str(FONTS / "InterDisplay-SemiBold.ttf")
MEDIUM = str(FONTS / "InterDisplay-Medium.ttf")
REGULAR = str(FONTS / "InterDisplay-Regular.ttf")

SS = 3  # супersampling: рисуем в 3x и уменьшаем — края выходят гладкими

# --- Палитра ---------------------------------------------------------------
NOIR_TOP = (13, 14, 19)
NOIR_BOTTOM = (23, 25, 33)
INDIGO_TOP = (11, 16, 44)
INDIGO_BOTTOM = (24, 31, 72)

PLATINUM = ((255, 255, 255), (168, 176, 194))       # верх -> низ градиента текста
CHAMPAGNE = ((240, 226, 194), (188, 156, 96))
MUTED = (138, 147, 166)
FAINT = (110, 118, 134)


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


# --- Базовые приёмы --------------------------------------------------------
def vertical_gradient(size: tuple[int, int], top, bottom) -> Image.Image:
    """Плавный вертикальный градиент без полос: считаем в миниатюре."""
    height = 256
    strip = Image.new("RGB", (1, height))
    pixels = strip.load()
    for y in range(height):
        t = y / (height - 1)
        pixels[0, y] = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom))
    return strip.resize(size, Image.BICUBIC)


def radial_glow(size: tuple[int, int], center: tuple[float, float],
                radius: float, strength: int) -> Image.Image:
    """Мягкое световое пятно как маска."""
    w, h = size
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    cx, cy = center[0] * w, center[1] * h
    r = radius * max(w, h)
    steps = 48
    for i in range(steps, 0, -1):
        t = i / steps
        value = int(strength * (1 - t) ** 2.2)
        draw.ellipse([cx - r * t, cy - r * t, cx + r * t, cy + r * t], fill=value)
    return mask.filter(ImageFilter.GaussianBlur(r * 0.10))


def vignette(size: tuple[int, int], strength: int = 80) -> Image.Image:
    """Маска затемнения к краям: 255 — где кадр гасим сильнее всего."""
    glow = radial_glow(size, (0.5, 0.5), 0.95, 255)
    return ImageChops.invert(glow).point(lambda value: value * strength // 255)


def add_grain(image: Image.Image, alpha: float = 0.035) -> Image.Image:
    """Микрозерно: убирает пластиковую гладкость градиента."""
    noise = Image.effect_noise(image.size, 22).convert("RGB")
    return Image.blend(image, ImageChops.overlay(image, noise), alpha)


def gradient_fill(mask: Image.Image, colors) -> Image.Image:
    """Красит непрозрачные пиксели маски вертикальным градиентом."""
    layer = vertical_gradient(mask.size, *colors).convert("RGBA")
    layer.putalpha(mask)
    return layer


def text_mask(size: tuple[int, int], position: tuple[int, int], text: str,
              fnt: ImageFont.FreeTypeFont, tracking: float = 0.0) -> Image.Image:
    """Маска текста с межбуквенным интервалом (PIL сам его не умеет)."""
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    x, y = position
    for char in text:
        draw.text((x, y), char, font=fnt, fill=255)
        x += draw.textlength(char, font=fnt) + tracking
    return mask


def tracked_width(draw: ImageDraw.ImageDraw, text: str,
                  fnt: ImageFont.FreeTypeFont, tracking: float = 0.0) -> float:
    return sum(draw.textlength(c, font=fnt) for c in text) + tracking * (len(text) - 1)


def hairline(draw: ImageDraw.ImageDraw, box, color, width: int) -> None:
    draw.line(box, fill=color, width=width)


# --- Знак ------------------------------------------------------------------
def mark(canvas: Image.Image, box: tuple[float, float, float, float],
         colors, stroke_ratio: float = 0.075) -> None:
    """Скруглённый контур с галочкой внутри — «бриф принят», одной толщиной линии."""
    x0, y0, x1, y1 = box
    side = x1 - x0
    stroke = max(2, int(side * stroke_ratio))

    shape = Image.new("L", canvas.size, 0)
    draw = ImageDraw.Draw(shape)
    draw.rounded_rectangle([x0, y0, x1, y1], radius=side * 0.28, outline=255, width=stroke)

    cx0, cy0 = x0 + side * 0.26, y0 + side * 0.52
    points = [(cx0, cy0), (x0 + side * 0.44, y0 + side * 0.70), (x0 + side * 0.76, y0 + side * 0.32)]
    draw.line(points, fill=255, width=stroke, joint="curve")
    for point in points:
        draw.ellipse([point[0] - stroke / 2, point[1] - stroke / 2,
                      point[0] + stroke / 2, point[1] + stroke / 2], fill=255)

    canvas.alpha_composite(gradient_fill(shape, colors))


# --- Аватары ---------------------------------------------------------------
def _avatar_base(size: int, top, bottom) -> Image.Image:
    s = size * SS
    base = vertical_gradient((s, s), top, bottom)
    glow = Image.new("RGB", (s, s), (255, 255, 255))
    base = Image.composite(glow, base, radial_glow((s, s), (0.30, 0.20), 0.55, 26))
    return base.convert("RGBA")


def _inner_ring(canvas: Image.Image, opacity: int = 26) -> None:
    s = canvas.size[0]
    ring = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(ring)
    inset = s * 0.085
    draw.ellipse([inset, inset, s - inset, s - inset],
                 outline=(255, 255, 255, opacity), width=max(2, int(s * 0.004)))
    canvas.alpha_composite(ring)


def avatar_monogram(size: int = 512, colors=PLATINUM, palette=(NOIR_TOP, NOIR_BOTTOM)) -> Image.Image:
    """Монограмма B: платиновая типографика на графитовом фоне."""
    s = size * SS
    canvas = _avatar_base(size, *palette)
    _inner_ring(canvas)

    fnt = font(SEMIBOLD, int(s * 0.46))
    probe = ImageDraw.Draw(canvas)
    left, top, right, bottom = probe.textbbox((0, 0), "B", font=fnt)
    position = (int((s - (right + left)) / 2), int((s - (bottom + top)) / 2))
    canvas.alpha_composite(gradient_fill(text_mask((s, s), position, "B", fnt), colors))

    return _finish(canvas, size)


def avatar_mark(size: int = 512, colors=PLATINUM, palette=(NOIR_TOP, NOIR_BOTTOM)) -> Image.Image:
    """Абстрактный знак: контур брифа с галочкой, без буквы."""
    s = size * SS
    canvas = _avatar_base(size, *palette)
    _inner_ring(canvas)
    side = s * 0.42
    offset = (s - side) / 2
    mark(canvas, (offset, offset, offset + side, offset + side), colors)
    return _finish(canvas, size)


def _finish(canvas: Image.Image, size: int) -> Image.Image:
    flat = Image.new("RGB", canvas.size, (0, 0, 0))
    flat.paste(canvas, mask=canvas.split()[3])
    flat = add_grain(flat, 0.030)
    return flat.resize((size, size), Image.LANCZOS)


# --- Баннер ----------------------------------------------------------------
def welcome_banner(width: int = 1600, height: int = 900,
                   palette=(NOIR_TOP, NOIR_BOTTOM), accent=PLATINUM) -> Image.Image:
    w, h = width * SS, height * SS
    base = vertical_gradient((w, h), *palette)
    glow = Image.new("RGB", (w, h), (255, 255, 255))
    base = Image.composite(glow, base, radial_glow((w, h), (0.74, 0.28), 0.42, 30))
    base = Image.composite(Image.new("RGB", (w, h), (0, 0, 0)), base, vignette((w, h), 70))
    canvas = base.convert("RGBA")
    draw = ImageDraw.Draw(canvas)

    # Огромный знак-водяной у правого края: даёт глубину, не спорит с текстом
    watermark = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    mark(watermark, (w * 0.70, -h * 0.16, w * 0.70 + h * 1.15, h * 0.99), accent, 0.055)
    canvas.alpha_composite(Image.blend(Image.new("RGBA", canvas.size, (0, 0, 0, 0)), watermark, 0.13))

    left = int(w * 0.085)
    side = int(h * 0.125)
    mark(canvas, (left, int(h * 0.155), left + side, int(h * 0.155) + side), accent, 0.070)

    # Название
    title = font(SEMIBOLD, int(h * 0.150))
    title_y = int(h * 0.345)
    bbox = draw.textbbox((0, 0), "Brief", font=title)
    canvas.alpha_composite(
        gradient_fill(text_mask((w, h), (left - bbox[0], title_y), "Brief", title, -h * 0.004), accent)
    )
    title_bottom = title_y + bbox[3]

    # Волосяная линия
    rule_y = int(title_bottom + h * 0.050)
    hairline(ImageDraw.Draw(canvas), [(left, rule_y), (int(left + w * 0.16), rule_y)],
             (255, 255, 255, 40), max(2, int(h * 0.0022)))

    # Подзаголовок капслоком с разрядкой
    sub = font(MEDIUM, int(h * 0.032))
    sub_y = rule_y + int(h * 0.045)
    canvas.alpha_composite(
        gradient_fill(
            text_mask((w, h), (left, sub_y), "ЗАЯВКИ НА РАЗРАБОТКУ ЧАТ-БОТОВ", sub, h * 0.0075),
            ((*MUTED,), (*MUTED,)),
        )
    )

    # Нижняя строка с тезисами через тонкие разделители
    small = font(REGULAR, int(h * 0.030))
    x = left
    y = int(h * 0.815)
    probe = ImageDraw.Draw(canvas)
    for index, item in enumerate(("7 шагов", "Кнопки вместо анкет", "Оценка бесплатно")):
        if index:
            probe.text((x, y), "·", font=small, fill=(*FAINT, 150))
            x += probe.textlength("·", font=small) + h * 0.020
        canvas.alpha_composite(
            gradient_fill(text_mask((w, h), (int(x), y), item, small, h * 0.0016),
                          ((*FAINT,), (*FAINT,)))
        )
        x += tracked_width(probe, item, small, h * 0.0016) + h * 0.020

    flat = Image.new("RGB", canvas.size, (0, 0, 0))
    flat.paste(canvas, mask=canvas.split()[3])
    return add_grain(flat, 0.028).resize((width, height), Image.LANCZOS)


def main() -> None:
    outputs = {
        "avatar_monogram.png": avatar_monogram(),
        "avatar_mark.png": avatar_mark(),
        "avatar_indigo.png": avatar_monogram(colors=CHAMPAGNE, palette=(INDIGO_TOP, INDIGO_BOTTOM)),
        "welcome.png": welcome_banner(),
        "welcome_indigo.png": welcome_banner(palette=(INDIGO_TOP, INDIGO_BOTTOM), accent=CHAMPAGNE),
    }
    for name, image in outputs.items():
        path = ASSETS / name
        image.save(path, "PNG", optimize=True)
        print(f"{name:24} {image.size[0]}x{image.size[1]}  {path.stat().st_size // 1024} КБ")


if __name__ == "__main__":
    main()
