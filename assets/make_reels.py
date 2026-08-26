"""Сборка вертикального ролика 1080x1920 про бота Brief.

Кадры рисуются Pillow, склеиваются ffmpeg (libx264). Звука нет намеренно:
музыку накладывайте на площадке из её библиотеки, иначе трек приглушат.

    pip install Pillow imageio-ffmpeg
    python assets/make_reels.py
"""
from __future__ import annotations

import json
import subprocess
import unicodedata
import wave
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).resolve().parent
FONTS = ASSETS / "fonts"
OUT = ASSETS / "reels_brief.mp4"

W, H = 1080, 1920
FPS = 30

SEMIBOLD = str(FONTS / "InterDisplay-SemiBold.ttf")
MEDIUM = str(FONTS / "InterDisplay-Medium.ttf")
REGULAR = str(FONTS / "InterDisplay-Regular.ttf")
EMOJI = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"
EMOJI_NATIVE = 109  # NotoColorEmoji растрирован под этот кегль

# Палитра тёмной темы Telegram
BG = (14, 22, 33)
HEADER = (23, 33, 43)
BUBBLE = (24, 37, 51)
BTN = (34, 49, 66)
TEXT = (231, 237, 243)
MUTED = (138, 160, 180)
SCRIM = (7, 11, 16)

CHAT_TOP = 350
CHAT_BOTTOM = 1560
SIDE = 60
COL_W = 960


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


F_TITLE = font(SEMIBOLD, 44)
F_BODY = font(REGULAR, 40)
F_HINT = font(REGULAR, 34)
F_BTN = font(MEDIUM, 36)
F_NAME = font(SEMIBOLD, 42)
F_SMALL = font(MEDIUM, 30)
F_CAPTION = font(SEMIBOLD, 48)

_emoji_cache: dict[tuple[str, int], Image.Image] = {}


def emoji_image(char: str, size: int) -> Image.Image:
    key = (char, size)
    if key not in _emoji_cache:
        fnt = ImageFont.truetype(EMOJI, EMOJI_NATIVE)
        tile = Image.new("RGBA", (EMOJI_NATIVE + 40, EMOJI_NATIVE + 40), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((0, 0), char, font=fnt, embedded_color=True)
        box = tile.getbbox() or (0, 0, EMOJI_NATIVE, EMOJI_NATIVE)
        _emoji_cache[key] = tile.crop(box).resize((size, size), Image.LANCZOS)
    return _emoji_cache[key]


def split_emoji(label: str) -> tuple[str | None, str]:
    """Отделяет ведущий эмодзи от подписи кнопки."""
    if label and unicodedata.category(label[0]) == "So":
        return label[0], label[1:].strip()
    return None, label


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words, current = paragraph.split(" "), ""
        for word in words:
            probe = f"{current} {word}".strip()
            if draw.textlength(probe, font=fnt) <= max_width or not current:
                current = probe
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def rounded(canvas: Image.Image, box, radius: int, fill) -> None:
    ImageDraw.Draw(canvas).rounded_rectangle(box, radius=radius, fill=fill)


# --- Экраны ----------------------------------------------------------------
BOT_TITLE = "Brief"
BOT_HANDLE = "@brief7_bot"


def draw_chrome(canvas: Image.Image) -> None:
    """Оформление iOS: Dynamic Island, шапка с центрированным именем,
    аватар справа, поле ввода и индикатор home внизу."""
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, 0, W, 300], fill=HEADER)

    # Статус-бар
    draw.text((92, 44), "9:41", font=F_SMALL, fill=TEXT)
    for index in range(4):                                   # уровень сигнала
        x = W - 240 + index * 22
        height = 12 + index * 8
        draw.rounded_rectangle([x, 66 - height, x + 14, 66], radius=4, fill=TEXT)
    for index, radius in enumerate((30, 20, 10)):            # wi-fi
        cx, cy = W - 150, 70
        draw.arc([cx - radius, cy - radius, cx + radius, cy + radius],
                 start=215, end=325, fill=TEXT, width=6)
    draw.ellipse([W - 154, 62, W - 146, 70], fill=TEXT)
    draw.rounded_rectangle([W - 108, 40, W - 44, 70], radius=9, outline=TEXT, width=4)
    draw.rounded_rectangle([W - 104, 44, W - 64, 66], radius=6, fill=TEXT)
    draw.rounded_rectangle([W - 40, 50, W - 34, 60], radius=3, fill=TEXT)

    # Dynamic Island
    draw.rounded_rectangle([(W - 320) // 2, 30, (W + 320) // 2, 122], radius=46, fill=(0, 0, 0))

    # Шапка чата
    draw.line([(44, 222), (76, 190)], fill=(94, 165, 240), width=7)
    draw.line([(44, 222), (76, 254)], fill=(94, 165, 240), width=7)

    title_w = draw.textlength(BOT_TITLE, font=F_NAME)
    draw.text(((W - title_w) / 2, 172), BOT_TITLE, font=F_NAME, fill=TEXT)
    handle_w = draw.textlength(BOT_HANDLE, font=F_SMALL)
    draw.text(((W - handle_w) / 2, 232), BOT_HANDLE, font=F_SMALL, fill=MUTED)

    avatar = Image.open(ASSETS / "avatar_monogram.png").resize((104, 104), Image.LANCZOS)
    mask = Image.new("L", (104, 104), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, 104, 104], fill=255)
    canvas.paste(avatar, (W - 150, 148), mask)

    # Поле ввода и индикатор home
    draw.ellipse([48, 1782, 108, 1842], outline=MUTED, width=5)
    draw.line([(78, 1798), (78, 1826)], fill=MUTED, width=5)
    draw.line([(64, 1812), (92, 1812)], fill=MUTED, width=5)
    draw.rounded_rectangle([130, 1774, 950, 1850], radius=38, fill=(28, 40, 54))
    draw.text((168, 1793), "Сообщение", font=F_BODY, fill=MUTED)
    draw.rounded_rectangle([990, 1786, 1010, 1822], radius=10, fill=MUTED)
    draw.arc([978, 1810, 1022, 1846], start=0, end=180, fill=MUTED, width=5)
    draw.rounded_rectangle([(W - 380) // 2, 1888, (W + 380) // 2, 1898], radius=5, fill=(120, 132, 148))


def build_column(state: dict) -> tuple[Image.Image, list[tuple[int, int, int, int]]]:
    """Колонка сообщений: баннер, пузырь и инлайн-кнопки. Возвращает боксы кнопок."""
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    blocks: list[tuple[str, object]] = []
    height = 0

    if state.get("banner"):
        banner = Image.open(ASSETS / "welcome.png").resize((COL_W, int(COL_W * 9 / 16)), Image.LANCZOS)
        blocks.append(("banner", banner))
        height += banner.height + 16

    pad = 34
    title_lines = wrap(probe, state["title"], F_TITLE, COL_W - pad * 2) if state.get("title") else []
    body_lines = wrap(probe, state["body"], F_BODY, COL_W - pad * 2) if state.get("body") else []
    hint_lines = wrap(probe, state["hint"], F_HINT, COL_W - pad * 2) if state.get("hint") else []
    bubble_h = pad * 2 + len(title_lines) * 58 + len(body_lines) * 54 + len(hint_lines) * 46
    if title_lines and (body_lines or hint_lines):
        bubble_h += 12
    blocks.append(("bubble", (title_lines, body_lines, hint_lines, bubble_h)))
    height += bubble_h + 14

    rows = state.get("buttons", [])
    row_h, gap = 96, 12
    height += len(rows) * (row_h + gap)

    column = Image.new("RGBA", (W, max(height, 1)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(column)
    y = 0
    boxes: list[tuple[int, int, int, int]] = []

    for kind, payload in blocks:
        if kind == "banner":
            rounded_mask = Image.new("L", payload.size, 0)
            ImageDraw.Draw(rounded_mask).rounded_rectangle([0, 0, *payload.size], radius=28, fill=255)
            column.paste(payload, (SIDE, y), rounded_mask)
            y += payload.height + 16
        else:
            title_lines, body_lines, hint_lines, bubble_h = payload
            draw.rounded_rectangle([SIDE, y, SIDE + COL_W, y + bubble_h], radius=28, fill=BUBBLE)
            ty = y + pad
            for line in title_lines:
                draw.text((SIDE + pad, ty), line, font=F_TITLE, fill=TEXT)
                ty += 58
            if title_lines and (body_lines or hint_lines):
                ty += 12
            for line in body_lines:
                draw.text((SIDE + pad, ty), line, font=F_BODY, fill=TEXT)
                ty += 54
            for line in hint_lines:
                draw.text((SIDE + pad, ty), line, font=F_HINT, fill=MUTED)
                ty += 46
            y += bubble_h + 14

    for row in rows:
        cell_w = (COL_W - gap * (len(row) - 1)) // len(row)
        for index, label in enumerate(row):
            x = SIDE + index * (cell_w + gap)
            box = (x, y, x + cell_w, y + row_h)
            draw.rounded_rectangle(box, radius=20, fill=BTN)
            icon, caption = split_emoji(label)
            text_w = draw.textlength(caption, font=F_BTN)
            total = text_w + (52 if icon else 0)
            tx = x + (cell_w - total) / 2
            if icon:
                column.paste(emoji_image(icon, 40), (int(tx), y + 28), emoji_image(icon, 40))
                tx += 52
            draw.text((tx, y + row_h / 2 - 24), caption, font=F_BTN, fill=TEXT)
            boxes.append(box)
        y += row_h + gap

    return column, boxes


def render_state(state: dict) -> tuple[Image.Image, list[tuple[int, int, int, int]]]:
    canvas = Image.new("RGB", (W, H), BG)
    column, boxes = build_column(state)
    top = min(CHAT_TOP, CHAT_BOTTOM - column.height)
    canvas.paste(column, (0, top), column)
    canvas.paste(Image.new("RGB", (W, 300), HEADER), (0, 0))
    draw_chrome(canvas)
    shifted = [(x0, y0 + top, x1, y1 + top) for x0, y0, x1, y1 in boxes]
    return canvas, shifted


def with_caption(frame: Image.Image, caption: str, alpha: float = 1.0) -> Image.Image:
    if not caption or alpha <= 0.01:
        return frame
    layer = frame.convert("RGBA")
    scrim = Image.new("RGBA", (W, 300), (0, 0, 0, 0))
    ImageDraw.Draw(scrim).rectangle([0, 0, W, 300], fill=(*SCRIM, int(200 * alpha)))
    layer.alpha_composite(scrim.filter(__import__("PIL.ImageFilter", fromlist=["ImageFilter"]).GaussianBlur(0)), (0, 1450))

    draw = ImageDraw.Draw(layer)
    lines = wrap(draw, caption, F_CAPTION, W - 160)
    y = 1500 + (200 - len(lines) * 62) // 2
    for line in lines:
        width_px = draw.textlength(line, font=F_CAPTION)
        draw.text(((W - width_px) / 2, y), line, font=F_CAPTION,
                  fill=(255, 255, 255, int(255 * alpha)))
        y += 62
    return layer.convert("RGB")


# --- Сцены -----------------------------------------------------------------
NAV = ["⬅️ Назад", "✖️ Отмена"]

MENU = {
    "banner": True,
    "body": "Я бот студии, которая делает чат-ботов для бизнеса: приём заявок, запись, магазины, поддержка.",
    "hint": "Заявка — 7 коротких шагов, почти везде кнопки.",
    "buttons": [["📝 Оставить заявку"], ["💼 Примеры работ", "💰 Цены и сроки"], ["💬 Задать вопрос"]],
}

STEP1 = {
    "title": "Шаг 1/7 · Тип бота", "body": "Какой бот нужен?",
    "buttons": [["📥 Приём заявок"], ["📅 Запись на услуги"], ["🛒 Магазин"],
                ["🛟 Поддержка клиентов"], ["✏️ Другое"], NAV],
}

STEP2 = {
    "title": "Шаг 2/7 · Сфера бизнеса", "body": "В какой сфере работаете?",
    "buttons": [["💇 Красота", "🏥 Медицина"], ["🎓 Образование", "🍽 Еда, доставка"],
                ["🛍 Товары", "🏠 Недвижимость"], ["💻 IT и услуги", "✏️ Другое"], NAV],
}


def features(selected: set[str]) -> dict:
    items = ["Оплата в боте", "Интеграция с CRM", "Google Таблицы", "Админ-панель",
             "Рассылки", "AI-ответы", "Мультиязычность", "Аналитика"]
    rows = [[f"{'✅' if item in selected else '▫️'} {item}"] for item in items]
    rows.append([f"✅ Готово ({len(selected)})"])
    rows.append(NAV)
    return {"title": "Шаг 3/7 · Функции", "body": "Какие функции нужны?", "buttons": rows}


STEP4 = {
    "title": "Шаг 4/7 · Бюджет", "body": "На какой бюджет ориентируетесь?",
    "buttons": [["до 15 000 ₽"], ["15 000 — 40 000 ₽"], ["40 000 — 100 000 ₽"],
                ["больше 100 000 ₽"], ["Пока не знаю"], NAV],
}

STEP5 = {
    "title": "Шаг 5/7 · Срок", "body": "К какому сроку нужен бот?",
    "buttons": [["Срочно, до 3 дней"], ["1 — 2 недели"], ["до месяца"], ["Не горит"], NAV],
}

STEP6 = {
    "title": "Шаг 6/7 · Описание", "body": "Опишите задачу своими словами.",
    "hint": "Что должен уметь бот. Шаг можно пропустить.",
    "buttons": [["⏭ Пропустить"], NAV],
}

STEP7 = {
    "title": "Шаг 7/7 · Контакт", "body": "Как с вами связаться?",
    "buttons": [["📎 Отправить @alex_m"], ["📱 Ввести телефон"], NAV],
}

CONFIRM = {
    "title": "Проверьте заявку",
    "body": "Тип: Приём заявок\nСфера: Красота\nФункции: Оплата в боте, Интеграция с CRM\n"
            "Бюджет: 40 000 — 100 000 ₽\nСрок: 1 — 2 недели\nКонтакт: @alex_m",
    "hint": "Всё верно?",
    "buttons": [["🚀 Отправить", "✏️ Изменить"], ["✖️ Отменить"]],
}

DONE = {
    "title": "Заявка №1 отправлена",
    "body": "Менеджер посмотрит её и напишет вам в этом чате.",
    "hint": "Обычно отвечаем в течение рабочего дня.",
    "buttons": [["💼 Примеры работ", "⬅️ В меню"]],
}

ADMIN = {
    "title": "Заявка №1",
    "body": "От: Алексей @alex_m\nКонтакт: @alex_m\nТип: Приём заявок\nСфера: Красота\n"
            "Бюджет: 40 000 — 100 000 ₽\nСрок: 1 — 2 недели",
    "hint": "25.08.2026 14:30 · avito",
    "buttons": [["🔧 Взять в работу", "❌ Отклонить"]],
}

# (состояние, длительность, индекс кнопки для тапа, подпись)
TIMELINE = [
    (MENU, 2.4, 0, "Клиент открывает бота"),
    (STEP1, 2.2, 0, "7 шагов — и почти везде кнопки"),
    (STEP2, 1.8, 0, "Ни одного поля для ввода"),
    (features(set()), 1.3, 0, "Нужные функции — галочками"),
    (features({"Оплата в боте"}), 1.0, 1, None),
    (features({"Оплата в боте", "Интеграция с CRM"}), 1.4, 8, None),
    (STEP4, 1.8, 2, "Бюджет и срок — диапазонами"),
    (STEP5, 1.6, 1, None),
    (STEP6, 1.8, 0, "Текст — только если сам захочет"),
    (STEP7, 1.8, 0, "Контакт в один тап"),
    (CONFIRM, 3.0, 0, "Сводка: всё видно и можно поправить"),
    (DONE, 2.0, None, "Клиенту — номер заявки"),
    (ADMIN, 3.2, None, "А вам — готовая карточка с кнопками"),
]

CARD_IN, CARD_OUT = ASSETS / "reels_hook.png", ASSETS / "reels_cta.png"
VOICE_PARTS = ASSETS / "voice_parts"
VOICE_PLAN = ASSETS / "voice_plan.json"

INTRO_SECONDS, OUTRO_SECONDS = 2.4, 4.0
TRANSITION_FRAMES = 7
TAIL = 0.35        # запас тишины после реплики, чтобы сцена не обрывалась на слове

# Какие сцены озвучивает каждая реплика. Индексы: 0 — вступительный титр,
# 1..13 — сцены TIMELINE по порядку, 14 — финальный титр.
PHRASE_GROUPS = [[0], [1], [2, 3], [4, 5, 6], [7, 8], [9, 10], [11], [12, 13], [14]]


def part_durations() -> list[float]:
    """Длительности наговорённых фраз, если они уже записаны."""
    if not VOICE_PARTS.is_dir():
        return []
    durations = []
    for path in sorted(VOICE_PARTS.glob("*.wav")):
        with wave.open(str(path), "rb") as handle:
            durations.append(handle.getnframes() / handle.getframerate())
    return durations


def plan() -> tuple[list[float], list[float], float]:
    """Длительности сцен, время начала каждой и общая длина.

    Если фразы записаны, сцены растягиваются под них: подгонять голос под
    картинку бессмысленно, а картинку под голос — бесплатно.
    """
    base = [INTRO_SECONDS] + [seconds for _, seconds, _, _ in TIMELINE] + [OUTRO_SECONDS]
    spoken = part_durations()

    if len(spoken) == len(PHRASE_GROUPS):
        for group, duration in zip(PHRASE_GROUPS, spoken):
            have = sum(base[index] for index in group)
            have += TRANSITION_FRAMES / FPS * (len(group) - 1)
            need = duration + TAIL
            if need > have:
                factor = need / have
                for index in group:
                    base[index] *= factor
    elif spoken:
        print(f"! фраз {len(spoken)}, а групп {len(PHRASE_GROUPS)} — тайминги оставляю базовыми")

    starts, cursor = [], 0.0
    for index, seconds in enumerate(base):
        starts.append(cursor)
        cursor += seconds
        if 1 <= index <= len(TIMELINE) - 1:      # переход между соседними сценами
            cursor += TRANSITION_FRAMES / FPS
    return base, starts, cursor


# --- Анимация --------------------------------------------------------------
def ease(t: float) -> float:
    return t * t * (3 - 2 * t)


def ripple(frame: Image.Image, box, progress: float) -> Image.Image:
    """След касания: расходящийся круг на месте нажатой кнопки."""
    layer = frame.convert("RGBA")
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    draw.rounded_rectangle(box, radius=20, fill=(255, 255, 255, int(30 * (1 - progress))))
    radius = 40 + 150 * ease(progress)
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                 outline=(255, 255, 255, int(150 * (1 - progress))), width=6)
    layer.alpha_composite(overlay)
    return layer.convert("RGB")


def card_frames(path: Path, seconds: float, zoom_from: float = 1.0, zoom_to: float = 1.06):
    source = Image.open(path).convert("RGB")
    total = int(seconds * FPS)
    for index in range(total):
        t = ease(index / max(total - 1, 1))
        scale = zoom_from + (zoom_to - zoom_from) * t
        crop_w, crop_h = int(W / scale), int(H / scale)
        left, top = (W - crop_w) // 2, (H - crop_h) // 2
        frame = source.crop((left, top, left + crop_w, top + crop_h)).resize((W, H), Image.LANCZOS)
        if index < 6:
            frame = Image.blend(Image.new("RGB", (W, H), (0, 0, 0)), frame, index / 6)
        elif index > total - 7:
            frame = Image.blend(frame, Image.new("RGB", (W, H), (0, 0, 0)), (index - (total - 7)) / 6)
        yield frame


def build_frames(base: list[float]):
    yield from card_frames(CARD_IN, base[0])

    rendered = []
    for (state, _, tap, caption), seconds in zip(TIMELINE, base[1:]):
        image, boxes = render_state(state)
        rendered.append((image, boxes, seconds, tap, caption))

    previous_caption = None
    for index, (image, boxes, seconds, tap, caption) in enumerate(rendered):
        text = caption if caption is not None else previous_caption
        previous_caption = text
        captioned = with_caption(image, text or "")

        total = int(seconds * FPS)
        fade = 8 if caption else 0
        tap_start = total - 12 if tap is not None else total + 1

        for frame_index in range(total):
            if frame_index < fade:
                frame = with_caption(image, text or "", frame_index / fade)
            elif frame_index >= tap_start:
                frame = ripple(captioned, boxes[tap], (frame_index - tap_start) / 12)
            else:
                frame = captioned
            yield frame

        if index + 1 < len(rendered):
            next_image, _, _, _, next_caption = rendered[index + 1]
            next_captioned = with_caption(next_image, (next_caption if next_caption is not None else text) or "")
            for step in range(7):
                yield Image.blend(captioned, next_captioned, ease((step + 1) / 8))

    yield from card_frames(CARD_OUT, base[-1])


def main() -> None:
    base, starts, total = plan()
    phrase_starts = [round(starts[group[0]], 3) for group in PHRASE_GROUPS]
    VOICE_PLAN.write_text(
        json.dumps({"phrases": phrase_starts, "total": round(total, 3)},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    if part_durations():
        print("Подгоняю сцены под записанные фразы:")
        for index, start in enumerate(phrase_starts, 1):
            print(f"  фраза {index}: старт {start:5.1f} с")

    exe = imageio_ffmpeg.get_ffmpeg_exe()
    command = [
        exe, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
        "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-preset", "slow",
        "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(OUT),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE)
    count = 0
    for frame in build_frames(base):
        process.stdin.write(frame.tobytes())
        count += 1
    process.stdin.close()
    if process.wait() != 0:
        raise SystemExit(process.stderr.read().decode()[-2000:])
    size = OUT.stat().st_size / 1024 / 1024
    print(f"{OUT}  {count} кадров  {count / FPS:.1f} с  {size:.1f} МБ")


if __name__ == "__main__":
    main()
