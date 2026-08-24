"""Все пользовательские тексты и справочники вариантов.

Модуль намеренно не импортирует ничего из логики бота: тексты и списки
вариантов можно править здесь, не трогая handlers/ и keyboards/.
"""
from __future__ import annotations

from html import escape

# --------------------------------------------------------------------------
# Справочники вариантов: (код, подпись). Код уходит в callback_data,
# поэтому он короткий и не меняется при правке подписи.
# --------------------------------------------------------------------------
BOT_TYPES: list[tuple[str, str]] = [
    ("lead", "📥 Приём заявок"),
    ("book", "📅 Запись на услуги"),
    ("shop", "🛒 Магазин"),
    ("help", "🛟 Поддержка клиентов"),
    ("other", "✏️ Другое"),
]

SPHERES: list[tuple[str, str]] = [
    ("beauty", "💇 Красота"),
    ("med", "🏥 Медицина"),
    ("edu", "🎓 Образование"),
    ("food", "🍽 Еда, доставка"),
    ("retail", "🛍 Товары"),
    ("realty", "🏠 Недвижимость"),
    ("it", "💻 IT и услуги"),
    ("other", "✏️ Другое"),
]

FEATURES: list[tuple[str, str]] = [
    ("pay", "Оплата в боте"),
    ("crm", "Интеграция с CRM"),
    ("sheets", "Google Таблицы"),
    ("admin", "Админ-панель"),
    ("mail", "Рассылки"),
    ("ai", "AI-ответы"),
    ("lang", "Мультиязычность"),
    ("stat", "Аналитика"),
]

BUDGETS: list[tuple[str, str]] = [
    ("b1", "до 15 000 ₽"),
    ("b2", "15 000 — 40 000 ₽"),
    ("b3", "40 000 — 100 000 ₽"),
    ("b4", "больше 100 000 ₽"),
    ("b0", "Пока не знаю"),
]

DEADLINES: list[tuple[str, str]] = [
    ("d1", "Срочно, до 3 дней"),
    ("d2", "1 — 2 недели"),
    ("d3", "до месяца"),
    ("d4", "Не горит"),
]

CATALOGS: dict[str, list[tuple[str, str]]] = {
    "bot_type": BOT_TYPES,
    "sphere": SPHERES,
    "features": FEATURES,
    "budget": BUDGETS,
    "deadline": DEADLINES,
}

STEP_TITLES: dict[str, str] = {
    "bot_type": "Тип бота",
    "sphere": "Сфера бизнеса",
    "features": "Функции",
    "budget": "Бюджет",
    "deadline": "Срок",
    "description": "Описание",
    "contact": "Контакт",
}

STATUS_LABELS: dict[str, str] = {
    "new": "🆕 новая",
    "in_work": "🔧 в работе",
    "rejected": "❌ отклонена",
}


def label(step: str, code: str) -> str:
    """Подпись варианта по коду; если кода нет — возвращаем сам код."""
    for item_code, item_label in CATALOGS.get(step, []):
        if item_code == code:
            return item_label
    return code


def labels(step: str, codes: list[str]) -> str:
    return ", ".join(label(step, code) for code in codes) or "—"


# --------------------------------------------------------------------------
# Главное меню и информационные экраны
# --------------------------------------------------------------------------
def greeting(name: str) -> str:
    return (
        f"👋 Привет, {escape(name)}!\n\n"
        "Я бот студии, которая делает <b>чат-ботов для бизнеса</b>: "
        "приём заявок, запись, магазины, поддержка.\n\n"
        "Заявка — 7 коротких шагов, почти везде кнопки. "
        "Ответим в течение рабочего дня.\n\n"
        "Выберите, с чего начнём 👇"
    )


MENU_TITLE = "Главное меню. Чем помочь?"

EXAMPLES = (
    "<b>💼 Примеры работ</b>\n\n"
    "• <b>Барбершоп</b> — запись на услугу, напоминания, отмена. "
    "Администратор освободился от 60% звонков.\n"
    "• <b>Онлайн-школа</b> — приём заявок + выдача материалов, интеграция с CRM.\n"
    "• <b>Доставка еды</b> — корзина, оплата, статусы заказа.\n"
    "• <b>Сервис B2B</b> — поддержка первой линии: FAQ, тикеты, эскалация оператору.\n\n"
    "Показать демо и разобрать ваш случай — оставьте заявку."
)

PRICING = (
    "<b>💰 Цены и сроки</b>\n\n"
    "• <b>до 15 000 ₽</b> — простой бот-анкета, 2–4 дня\n"
    "• <b>15 000 — 40 000 ₽</b> — заявки/запись + админ-панель, 1–2 недели\n"
    "• <b>40 000 — 100 000 ₽</b> — оплата, CRM, рассылки, 2–4 недели\n"
    "• <b>от 100 000 ₽</b> — сложная логика и интеграции, срок по ТЗ\n\n"
    "Точная оценка — после короткой заявки, она бесплатна."
)

QUESTION_PROMPT = (
    "<b>💬 Вопрос</b>\n\n"
    "Напишите вопрос одним сообщением — передам его менеджеру.\n"
    "<i>От 5 до 1000 символов.</i>"
)


def question_sent(name: str) -> str:
    return (
        f"✅ Вопрос принят, {escape(name)}.\n\n"
        "Ответим в этом чате в течение рабочего дня."
    )


# --------------------------------------------------------------------------
# Шаги заявки
# --------------------------------------------------------------------------
STEP_PROMPTS: dict[str, str] = {
    "bot_type": "Какой бот нужен?",
    "sphere": "В какой сфере работаете?",
    "features": "Какие функции нужны?\n<i>Можно выбрать несколько, потом «Готово».</i>",
    "budget": "На какой бюджет ориентируетесь?\n<i>Это ориентир, не обязательство.</i>",
    "deadline": "К какому сроку нужен бот?",
    "description": (
        "Опишите задачу своими словами.\n"
        "<i>Что должен уметь бот, откуда идут клиенты. Шаг можно пропустить.</i>"
    ),
    "contact": "Как с вами связаться?",
}

CUSTOM_PROMPTS: dict[str, str] = {
    "bot_type": "Напишите одной строкой, какой бот нужен.",
    "sphere": "Напишите вашу сферу одной строкой.",
}

PHONE_PROMPT = (
    "Пришлите телефон для связи.\n"
    "<i>Например: +7 999 123-45-67</i>"
)


def step_header(index: int, total: int, title: str, edit_mode: bool = False) -> str:
    if edit_mode:
        return f"✏️ <b>Правим: {title}</b>"
    return f"<b>Шаг {index}/{total} · {title}</b>"


def step_text(step: str, index: int, total: int, edit_mode: bool = False) -> str:
    header = step_header(index, total, STEP_TITLES[step], edit_mode)
    return f"{header}\n\n{STEP_PROMPTS[step]}"


def contact_hint(has_username: bool) -> str:
    if has_username:
        return ""
    return "\n\n<i>У вас не задан @username, поэтому доступен только телефон.</i>"


# --------------------------------------------------------------------------
# Подтверждение и карточки
# --------------------------------------------------------------------------
def summary(answers: dict) -> str:
    description = answers.get("description") or "—"
    return (
        "<b>📋 Проверьте заявку</b>\n\n"
        f"<b>Тип:</b> {escape(answers.get('bot_type_label', '—'))}\n"
        f"<b>Сфера:</b> {escape(answers.get('sphere_label', '—'))}\n"
        f"<b>Функции:</b> {escape(answers.get('features_label', '—'))}\n"
        f"<b>Бюджет:</b> {escape(answers.get('budget_label', '—'))}\n"
        f"<b>Срок:</b> {escape(answers.get('deadline_label', '—'))}\n"
        f"<b>Задача:</b> {escape(description)}\n"
        f"<b>Контакт:</b> {escape(answers.get('contact', '—'))}\n\n"
        "Всё верно?"
    )


EDIT_MENU = "Что поправить?"


def order_created(order_id: int) -> str:
    return (
        f"✅ <b>Заявка №{order_id} отправлена</b>\n\n"
        "Менеджер посмотрит её и напишет вам в этом чате.\n"
        "Обычно отвечаем в течение рабочего дня."
    )


def admin_card(order_id: int, answers: dict, user_line: str, created_at: str) -> str:
    description = answers.get("description") or "—"
    return (
        f"🆕 <b>Заявка №{order_id}</b>\n"
        f"<i>{escape(created_at)}</i>\n\n"
        f"<b>От:</b> {user_line}\n"
        f"<b>Контакт:</b> {escape(answers.get('contact', '—'))}\n\n"
        f"<b>Тип:</b> {escape(answers.get('bot_type_label', '—'))}\n"
        f"<b>Сфера:</b> {escape(answers.get('sphere_label', '—'))}\n"
        f"<b>Функции:</b> {escape(answers.get('features_label', '—'))}\n"
        f"<b>Бюджет:</b> {escape(answers.get('budget_label', '—'))}\n"
        f"<b>Срок:</b> {escape(answers.get('deadline_label', '—'))}\n"
        f"<b>Задача:</b> {escape(description)}"
    )


def admin_question(question_id: int, user_line: str, text: str) -> str:
    return (
        f"💬 <b>Вопрос №{question_id}</b>\n\n"
        f"<b>От:</b> {user_line}\n\n"
        f"{escape(text)}"
    )


def user_status_changed(order_id: int, status: str) -> str:
    if status == "in_work":
        return (
            f"🔧 Заявка №{order_id} взята в работу.\n"
            "Менеджер свяжется с вами для деталей."
        )
    return (
        f"❌ Заявка №{order_id} отклонена.\n"
        "Если это ошибка — напишите нам через «Задать вопрос»."
    )


def admin_status_footer(status: str, admin_name: str) -> str:
    return f"\n\n— {STATUS_LABELS.get(status, status)} · {escape(admin_name)}"


# --------------------------------------------------------------------------
# Ошибки и служебные сообщения
# --------------------------------------------------------------------------
CANCELLED = "Заявка отменена. Ничего не отправлено."
NOTHING_TO_CANCEL = "Сейчас нечего отменять."
SESSION_EXPIRED = "Кнопка устарела — бот перезапускался. Нажмите /start."
TOO_FAST = "Слишком быстро 🙂 Секунду."
PICK_AT_LEAST_ONE = "Выберите хотя бы одну функцию."
UNKNOWN_OPTION = "Такого варианта уже нет, обновите шаг через «Назад»."
BAD_PHONE = (
    "Не похоже на телефон. Пришлите в формате <code>+7 999 123-45-67</code> "
    "или нажмите «Назад»."
)
BAD_TEXT_SHORT = "Слишком коротко — напишите чуть подробнее."
BAD_TEXT_LONG = "Слишком длинно. Уложитесь в {limit} символов."
EXPECTED_BUTTON = "На этом шаге нужно нажать кнопку 👆"
EXPECTED_TEXT = "Здесь нужен текст сообщением — файлы и стикеры не подойдут."
ERROR_GENERIC = "⚠️ Что-то пошло не так. Попробуйте ещё раз или нажмите /start."


def limit_reached(limit: int) -> str:
    return (
        f"🚧 С одного аккаунта можно отправить {limit} заявки в сутки.\n\n"
        "Если нужно срочно — напишите через «Задать вопрос»."
    )


# --------------------------------------------------------------------------
# Админские экраны
# --------------------------------------------------------------------------
ADMIN_ONLY = "Команда только для администратора."


def stats(day: int, week: int, total: int, by_status: dict[str, int]) -> str:
    lines = [
        "<b>📊 Статистика заявок</b>\n",
        f"За 24 часа: <b>{day}</b>",
        f"За 7 дней: <b>{week}</b>",
        f"Всего: <b>{total}</b>\n",
        "<b>По статусам</b>",
    ]
    for status, title in STATUS_LABELS.items():
        lines.append(f"{title}: {by_status.get(status, 0)}")
    return "\n".join(lines)


ORDERS_EMPTY = "Заявок пока нет."


def orders_page(rows: list[dict], page: int, pages: int, total: int) -> str:
    lines = [f"<b>📄 Заявки · страница {page}/{pages}</b> (всего {total})\n"]
    for row in rows:
        contact = escape(row["contact"] or "—")
        lines.append(
            f"<b>№{row['id']}</b> · {escape(row['created_at_local'])} · "
            f"{STATUS_LABELS.get(row['status'], row['status'])}\n"
            f"{escape(row['bot_type'])} · {escape(row['budget'])} · {contact}"
        )
    lines.append("\nПодробнее: <code>/order &lt;номер&gt;</code>")
    return "\n".join(lines)


def order_card(row: dict) -> str:
    return (
        f"<b>Заявка №{row['id']}</b> · {STATUS_LABELS.get(row['status'], row['status'])}\n"
        f"<i>{escape(row['created_at_local'])}</i>\n\n"
        f"<b>От:</b> {escape(row['full_name'] or '—')} "
        f"{('@' + row['username']) if row['username'] else ''} "
        f"(<code>{row['user_id']}</code>)\n"
        f"<b>Контакт:</b> {escape(row['contact'] or '—')}\n\n"
        f"<b>Тип:</b> {escape(row['bot_type'])}\n"
        f"<b>Сфера:</b> {escape(row['sphere'])}\n"
        f"<b>Функции:</b> {escape(row['features'] or '—')}\n"
        f"<b>Бюджет:</b> {escape(row['budget'])}\n"
        f"<b>Срок:</b> {escape(row['deadline'])}\n"
        f"<b>Задача:</b> {escape(row['description'] or '—')}"
    )


ORDER_NOT_FOUND = "Заявка не найдена."
ORDER_USAGE = "Формат: <code>/order 12</code>"
EXPORT_EMPTY = "Нечего выгружать — заявок нет."


def export_caption(count: int) -> str:
    return f"📤 Выгрузка: {count} заявок, CSV (разделитель «;», UTF-8)."


STATUS_ALREADY = "Статус уже изменён."
