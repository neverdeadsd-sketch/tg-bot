"""Генерация графики бота: аватар и приветственный баннер.

Всё рисуется кодом, поэтому текст всегда чёткий и правки бесплатны.
Запуск (нужен Pillow, в рантайме бота он не требуется):

    pip install Pillow
    python assets/make_assets.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).resolve().parent

# --- Фирменные цвета -------------------------------------------------------
GRAD_FROM = (47, 75, 224)     # индиго
GRAD_TO = (123, 63, 228)      # фиолетовый
ACCENT = (255, 194, 75)       # янтарный
WHITE = (255, 255, 255)
INK = (30, 34, 56)

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

SCALE = 2  # рисуем крупнее и уменьшаем — так края получаются гладкими


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def gradient(width: int, height: int) -> Image.Image:
    """Диагональный градиент: считаем в миниатюре и растягиваем."""
    small = Image.new("RGB", (64, 64))
    pixels = small.load()
    for y in range(64):
        for x in range(64):
            t = (x + y) / 126
            pixels[x, y] = tuple(
                round(a + (b - a) * t) for a, b in zip(GRAD_FROM, GRAD_TO)
            )
    return small.resize((width, height), Image.LANCZOS)


def checkmark(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int],
              color: tuple[int, int, int], width: int) -> None:
    """Галочка, вписанная в прямоугольник."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    points = [
        (x0 + w * 0.08, y0 + h * 0.55),
        (x0 + w * 0.38, y0 + h * 0.85),
        (x0 + w * 0.92, y0 + h * 0.15),
    ]
    draw.line(points, fill=color, width=width, joint="curve")
    for point in points:
        radius = width / 2
        draw.ellipse(
            [point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius],
            fill=color,
        )


def centered_text(draw: ImageDraw.ImageDraw, center: tuple[int, int], text: str,
                  fnt: ImageFont.FreeTypeFont, fill) -> None:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=fnt)
    draw.text(
        (center[0] - (right + left) / 2, center[1] - (bottom + top) / 2),
        text, font=fnt, fill=fill,
    )


def brief_mark(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    """Белый лист-бриф со строчками и янтарной галочкой."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    draw.rounded_rectangle(box, radius=int(w * 0.16), fill=WHITE)
    line_x0, line_x1 = x0 + w * 0.18, x1 - w * 0.18
    thickness = max(2, int(h * 0.055))
    for index, ratio in enumerate((0.28, 0.44)):
        draw.rounded_rectangle(
            [line_x0, y0 + h * ratio, line_x1 - (w * 0.18 if index else 0),
             y0 + h * ratio + thickness],
            radius=thickness, fill=(206, 212, 232),
        )
    checkmark(
        draw,
        (int(x0 + w * 0.2), int(y0 + h * 0.58), int(x1 - w * 0.2), int(y1 - h * 0.12)),
        ACCENT, max(3, int(h * 0.09)),
    )


# --- Аватары ---------------------------------------------------------------
def avatar_monogram(size: int = 512) -> Image.Image:
    """Монограмма «B» + янтарная галочка-бейдж."""
    s = size * SCALE
    image = gradient(s, s)
    draw = ImageDraw.Draw(image)

    centered_text(draw, (int(s * 0.47), int(s * 0.46)), "B", font(FONT_BOLD, int(s * 0.62)), WHITE)

    badge = int(s * 0.30)
    bx1, by1 = int(s * 0.80), int(s * 0.80)
    bx0, by0 = bx1 - badge, by1 - badge
    draw.ellipse([bx0, by0, bx1, by1], fill=ACCENT)
    inset = badge * 0.26
    checkmark(draw, (int(bx0 + inset), int(by0 + inset), int(bx1 - inset), int(by1 - inset)),
              INK, max(4, int(badge * 0.13)))
    return image.resize((size, size), Image.LANCZOS)


def avatar_sheet(size: int = 512) -> Image.Image:
    """Лист-бриф с галочкой, без буквы — работает при любом названии."""
    s = size * SCALE
    image = gradient(s, s)
    draw = ImageDraw.Draw(image)
    margin = s * 0.27
    brief_mark(draw, (int(margin), int(margin * 0.92), int(s - margin), int(s - margin * 0.92)))
    return image.resize((size, size), Image.LANCZOS)


# --- Приветственный баннер -------------------------------------------------
def welcome_banner(width: int = 1280, height: int = 720) -> Image.Image:
    w, h = width * SCALE, height * SCALE
    image = gradient(w, h)
    draw = ImageDraw.Draw(image, "RGBA")

    # Мягкие круги для глубины
    draw.ellipse([w * 0.62, -h * 0.30, w * 1.25, h * 0.72], fill=(255, 255, 255, 16))
    draw.ellipse([w * 0.70, h * 0.42, w * 1.12, h * 1.25], fill=(255, 255, 255, 12))

    left = int(w * 0.09)
    mark = int(h * 0.20)
    brief_mark(draw, (left, int(h * 0.16), left + mark, int(h * 0.16) + int(mark * 1.18)))

    title_font = font(FONT_BOLD, int(h * 0.20))
    draw.text((left - int(w * 0.004), int(h * 0.42)), "Brief", font=title_font, fill=WHITE)

    subtitle_font = font(FONT_REGULAR, int(h * 0.058))
    draw.text((left, int(h * 0.655)), "Заявки на разработку чат-ботов",
              font=subtitle_font, fill=(255, 255, 255, 224))

    pill_font = font(FONT_BOLD, int(h * 0.040))
    x = left
    for label in ("7 шагов", "Кнопки вместо анкет", "Оценка бесплатно"):
        bbox = draw.textbbox((0, 0), label, font=pill_font)
        text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        pad_x, pad_y = int(h * 0.030), int(h * 0.022)
        pill = [x, int(h * 0.775), x + text_w + pad_x * 2, int(h * 0.775) + text_h + pad_y * 2]
        draw.rounded_rectangle(pill, radius=(pill[3] - pill[1]) // 2, fill=(255, 255, 255, 38))
        draw.text((x + pad_x, int(h * 0.775) + pad_y - bbox[1]), label, font=pill_font, fill=WHITE)
        x = pill[2] + int(w * 0.018)

    return image.resize((width, height), Image.LANCZOS)


def main() -> None:
    outputs = {
        "avatar_monogram.png": avatar_monogram(),
        "avatar_sheet.png": avatar_sheet(),
        "welcome.png": welcome_banner(),
    }
    for name, image in outputs.items():
        path = ASSETS / name
        image.save(path, "PNG", optimize=True)
        print(f"{path}  {image.size[0]}x{image.size[1]}  {path.stat().st_size // 1024} КБ")


if __name__ == "__main__":
    main()
