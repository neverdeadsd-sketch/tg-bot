"""FSM-сценарий заявки: шаги, «Назад», подтверждение, отправка."""
from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, User

import db
import texts
import utils
from callbacks import MenuCB, OrderCB
from config import Config
from handlers.admin import notify_admins
from keyboards import admin as admin_kb
from keyboards import common as common_kb
from keyboards import order as kb

logger = logging.getLogger(__name__)
router = Router(name="order")


class OrderForm(StatesGroup):
    bot_type = State()
    sphere = State()
    features = State()
    budget = State()
    deadline = State()
    description = State()
    contact = State()
    custom = State()   # свободный ввод для варианта «Другое»
    phone = State()    # ввод телефона на шаге контакта
    confirm = State()  # экран проверки
    edit = State()     # выбор поля для правки


STEPS: tuple[str, ...] = (
    "bot_type", "sphere", "features", "budget", "deadline", "description", "contact",
)
CHOICE_STEPS = frozenset({"bot_type", "sphere", "budget", "deadline"})
CUSTOM_STEPS = frozenset({"bot_type", "sphere"})
STEP_STATES = tuple(getattr(OrderForm, step) for step in STEPS)
ORDER_STATES = STEP_STATES + (
    OrderForm.custom, OrderForm.phone, OrderForm.confirm, OrderForm.edit,
)
# Шаги, где ждём текст: остальные реагируют на текст подсказкой «нажмите кнопку».
TEXT_STATES = (OrderForm.description, OrderForm.phone, OrderForm.custom)


# --------------------------------------------------------------------------
# Вспомогательное
# --------------------------------------------------------------------------
def _chat_id(callback: CallbackQuery) -> int:
    return callback.message.chat.id if callback.message else callback.from_user.id


def _step_of_state(raw_state: str | None) -> str | None:
    return raw_state.split(":")[-1] if raw_state else None


def answer_labels(answers: dict[str, Any]) -> dict[str, Any]:
    """Коды -> человекочитаемые подписи для сводки и карточки админа."""
    return {
        "bot_type_label": answers.get("bot_type_custom")
        or texts.label("bot_type", answers.get("bot_type", "")),
        "sphere_label": answers.get("sphere_custom")
        or texts.label("sphere", answers.get("sphere", "")),
        "features_label": texts.labels("features", answers.get("features", [])),
        "budget_label": texts.label("budget", answers.get("budget", "")),
        "deadline_label": texts.label("deadline", answers.get("deadline", "")),
        "description": answers.get("description"),
        "contact": answers.get("contact", "—"),
    }


def _missing_steps(answers: dict[str, Any]) -> list[str]:
    required = [step for step in STEPS if step != "description"]
    return [step for step in required if not answers.get(step)]


async def show_step(
    bot: Bot,
    state: FSMContext,
    chat_id: int,
    step: str,
    user: User,
    notice: str | None = None,
) -> None:
    """Рисует шаг в том же сообщении и переводит FSM в нужное состояние."""
    await state.set_state(getattr(OrderForm, step))
    data = await state.get_data()
    answers: dict[str, Any] = data.get("answers", {})
    edit_mode = bool(data.get("edit_field"))
    text = texts.step_text(step, STEPS.index(step) + 1, len(STEPS), edit_mode)

    if step in CHOICE_STEPS:
        markup = kb.choice(step, answers.get(step))
    elif step == "features":
        markup = kb.features(answers.get("features", []))
    elif step == "description":
        markup = kb.description()
    else:  # contact
        text += texts.contact_hint(bool(user.username))
        markup = kb.contact(user.username)

    if notice:
        text = f"⚠️ {notice}\n\n{text}"
    await utils.show(bot, state, chat_id, text, markup)


async def show_confirm(bot: Bot, state: FSMContext, chat_id: int) -> None:
    await state.set_state(OrderForm.confirm)
    await state.update_data(edit_field=None)
    data = await state.get_data()
    summary = texts.summary(answer_labels(data.get("answers", {})))
    await utils.show(bot, state, chat_id, summary, kb.confirm())


async def advance(bot: Bot, state: FSMContext, chat_id: int, step: str, user: User) -> None:
    """Следующий шаг — или сразу экран проверки, если правим одно поле."""
    data = await state.get_data()
    if data.get("edit_field"):
        await show_confirm(bot, state, chat_id)
        return
    index = STEPS.index(step)
    if index + 1 < len(STEPS):
        await show_step(bot, state, chat_id, STEPS[index + 1], user)
    else:
        await show_confirm(bot, state, chat_id)


async def save_answer(state: FSMContext, step: str, value: Any) -> None:
    data = await state.get_data()
    answers = dict(data.get("answers", {}))
    answers[step] = value
    await state.update_data(answers=answers)


async def to_menu(bot: Bot, state: FSMContext, chat_id: int) -> None:
    data = await state.get_data()
    anchor = data.get("anchor_id")
    await state.clear()
    await state.update_data(anchor_id=anchor)
    await utils.show(bot, state, chat_id, texts.MENU_TITLE, common_kb.main_menu())


# --------------------------------------------------------------------------
# Старт сценария
# --------------------------------------------------------------------------
@router.callback_query(MenuCB.filter(F.action == "order"))
async def start_order(
    callback: CallbackQuery, state: FSMContext, bot: Bot, config: Config
) -> None:
    user = callback.from_user
    chat_id = _chat_id(callback)
    anchor = callback.message.message_id if callback.message else None

    await state.clear()
    if anchor:
        await state.update_data(anchor_id=anchor)

    used = await db.count_orders_last_day(user.id)
    if used >= config.max_orders_per_day:
        logger.info("Лимит заявок исчерпан для user_id=%s (%s)", user.id, used)
        await utils.show(
            bot, state, chat_id,
            texts.limit_reached(config.max_orders_per_day),
            kb.limit_reached(),
        )
        await callback.answer()
        return

    await state.update_data(answers={}, edit_field=None)
    await show_step(bot, state, chat_id, STEPS[0], user)
    await callback.answer()


# --------------------------------------------------------------------------
# Шаги с одиночным выбором
# --------------------------------------------------------------------------
@router.callback_query(
    OrderCB.filter(F.action == "pick"),
    StateFilter(OrderForm.bot_type, OrderForm.sphere, OrderForm.budget, OrderForm.deadline),
)
async def pick_option(
    callback: CallbackQuery, callback_data: OrderCB, state: FSMContext, bot: Bot
) -> None:
    step = _step_of_state(await state.get_state())
    if step is None:
        await callback.answer(texts.SESSION_EXPIRED, show_alert=True)
        return

    codes = {code for code, _ in texts.CATALOGS[step]}
    if callback_data.value not in codes:
        await callback.answer(texts.UNKNOWN_OPTION, show_alert=True)
        return

    await save_answer(state, step, callback_data.value)
    chat_id = _chat_id(callback)

    if callback_data.value == "other" and step in CUSTOM_STEPS:
        await state.set_state(OrderForm.custom)
        await state.update_data(custom_step=step)
        await utils.show(bot, state, chat_id, texts.CUSTOM_PROMPTS[step], kb.text_input())
        await callback.answer()
        return

    await save_answer(state, f"{step}_custom", None)
    await advance(bot, state, chat_id, step, callback.from_user)
    await callback.answer()


@router.message(OrderForm.custom, F.text)
async def custom_value(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    step = data.get("custom_step")
    await utils.drop_user_message(bot, message.chat.id, message.message_id)
    if step not in CUSTOM_STEPS:
        await to_menu(bot, state, message.chat.id)
        return

    value, error = utils.validate_text(message.text or "", min_len=2, max_len=utils.CUSTOM_LIMIT)
    if error:
        notice = texts.BAD_TEXT_SHORT if error == "short" else texts.BAD_TEXT_LONG.format(
            limit=utils.CUSTOM_LIMIT
        )
        await utils.show(
            bot, state, message.chat.id,
            f"⚠️ {notice}\n\n{texts.CUSTOM_PROMPTS[step]}",
            kb.text_input(),
        )
        return

    await save_answer(state, f"{step}_custom", value)
    await advance(bot, state, message.chat.id, step, message.from_user)


# --------------------------------------------------------------------------
# Мультивыбор функций
# --------------------------------------------------------------------------
@router.callback_query(OrderForm.features, OrderCB.filter(F.action == "feat"))
async def toggle_feature(
    callback: CallbackQuery, callback_data: OrderCB, state: FSMContext, bot: Bot
) -> None:
    codes = {code for code, _ in texts.FEATURES}
    if callback_data.value not in codes:
        await callback.answer(texts.UNKNOWN_OPTION, show_alert=True)
        return

    data = await state.get_data()
    answers = dict(data.get("answers", {}))
    selected: list[str] = list(answers.get("features", []))
    if callback_data.value in selected:
        selected.remove(callback_data.value)
    else:
        selected.append(callback_data.value)
    answers["features"] = selected
    await state.update_data(answers=answers)

    edit_mode = bool(data.get("edit_field"))
    text = texts.step_text("features", STEPS.index("features") + 1, len(STEPS), edit_mode)
    await utils.show(bot, state, _chat_id(callback), text, kb.features(selected))
    await callback.answer()


@router.callback_query(OrderForm.features, OrderCB.filter(F.action == "done"))
async def features_done(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    if not data.get("answers", {}).get("features"):
        await callback.answer(texts.PICK_AT_LEAST_ONE, show_alert=True)
        return
    await advance(bot, state, _chat_id(callback), "features", callback.from_user)
    await callback.answer()


# --------------------------------------------------------------------------
# Описание задачи
# --------------------------------------------------------------------------
@router.callback_query(OrderForm.description, OrderCB.filter(F.action == "skip"))
async def skip_description(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await save_answer(state, "description", None)
    await advance(bot, state, _chat_id(callback), "description", callback.from_user)
    await callback.answer()


@router.message(OrderForm.description, F.text)
async def set_description(message: Message, state: FSMContext, bot: Bot) -> None:
    await utils.drop_user_message(bot, message.chat.id, message.message_id)
    value, error = utils.validate_text(
        message.text or "", min_len=5, max_len=utils.DESCRIPTION_LIMIT
    )
    if error:
        notice = texts.BAD_TEXT_SHORT if error == "short" else texts.BAD_TEXT_LONG.format(
            limit=utils.DESCRIPTION_LIMIT
        )
        await show_step(bot, state, message.chat.id, "description", message.from_user, notice)
        return
    await save_answer(state, "description", value)
    await advance(bot, state, message.chat.id, "description", message.from_user)


# --------------------------------------------------------------------------
# Контакт
# --------------------------------------------------------------------------
@router.callback_query(OrderForm.contact, OrderCB.filter(F.action == "uname"))
async def contact_username(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    username = callback.from_user.username
    if not username:
        await callback.answer(texts.EXPECTED_BUTTON, show_alert=True)
        return
    await save_answer(state, "contact", f"@{username}")
    await advance(bot, state, _chat_id(callback), "contact", callback.from_user)
    await callback.answer()


@router.callback_query(OrderForm.contact, OrderCB.filter(F.action == "phone"))
async def ask_phone(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.set_state(OrderForm.phone)
    await utils.show(bot, state, _chat_id(callback), texts.PHONE_PROMPT, kb.text_input())
    await callback.answer()


@router.message(OrderForm.phone, F.text)
async def set_phone(message: Message, state: FSMContext, bot: Bot) -> None:
    await utils.drop_user_message(bot, message.chat.id, message.message_id)
    phone = utils.normalize_phone(message.text or "")
    if phone is None:
        await utils.show(
            bot, state, message.chat.id,
            f"⚠️ {texts.BAD_PHONE}\n\n{texts.PHONE_PROMPT}",
            kb.text_input(),
        )
        return
    await save_answer(state, "contact", phone)
    await advance(bot, state, message.chat.id, "contact", message.from_user)


# --------------------------------------------------------------------------
# Навигация: назад / отмена
# --------------------------------------------------------------------------
@router.callback_query(StateFilter(*ORDER_STATES), OrderCB.filter(F.action == "back"))
async def go_back(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    raw_state = await state.get_state()
    data = await state.get_data()
    chat_id = _chat_id(callback)
    user = callback.from_user
    current = _step_of_state(raw_state)

    if current == "custom":
        step = data.get("custom_step", STEPS[0])
        await show_step(bot, state, chat_id, step, user)
    elif current == "phone":
        await show_step(bot, state, chat_id, "contact", user)
    elif current == "edit":
        await show_confirm(bot, state, chat_id)
    elif current == "confirm":
        await show_step(bot, state, chat_id, STEPS[-1], user)
    elif data.get("edit_field"):
        await show_confirm(bot, state, chat_id)
    elif current in STEPS:
        index = STEPS.index(current)
        if index == 0:
            await to_menu(bot, state, chat_id)
        else:
            await show_step(bot, state, chat_id, STEPS[index - 1], user)
    else:
        await to_menu(bot, state, chat_id)
    await callback.answer()


@router.callback_query(StateFilter(*ORDER_STATES), OrderCB.filter(F.action == "cancel"))
async def cancel_order(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    chat_id = _chat_id(callback)
    data = await state.get_data()
    anchor = data.get("anchor_id")
    await state.clear()
    await state.update_data(anchor_id=anchor)
    await utils.show(
        bot, state, chat_id,
        f"{texts.CANCELLED}\n\n{texts.MENU_TITLE}",
        common_kb.main_menu(),
    )
    await callback.answer()


# --------------------------------------------------------------------------
# Проверка и отправка
# --------------------------------------------------------------------------
@router.callback_query(OrderForm.confirm, OrderCB.filter(F.action == "edit"))
async def edit_menu(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.set_state(OrderForm.edit)
    await utils.show(bot, state, _chat_id(callback), texts.EDIT_MENU, kb.edit_menu(STEPS))
    await callback.answer()


@router.callback_query(OrderForm.edit, OrderCB.filter(F.action == "field"))
async def edit_field(
    callback: CallbackQuery, callback_data: OrderCB, state: FSMContext, bot: Bot
) -> None:
    step = callback_data.value
    if step not in STEPS:
        await callback.answer(texts.UNKNOWN_OPTION, show_alert=True)
        return
    await state.update_data(edit_field=step)
    await show_step(bot, state, _chat_id(callback), step, callback.from_user)
    await callback.answer()


@router.callback_query(OrderForm.confirm, OrderCB.filter(F.action == "submit"))
async def submit_order(
    callback: CallbackQuery, state: FSMContext, bot: Bot, config: Config
) -> None:
    user = callback.from_user
    chat_id = _chat_id(callback)
    data = await state.get_data()
    answers: dict[str, Any] = data.get("answers", {})

    missing = _missing_steps(answers)
    if missing:
        logger.warning("Неполная заявка user_id=%s, нет шагов: %s", user.id, missing)
        await state.update_data(edit_field=missing[0])
        await show_step(bot, state, chat_id, missing[0], user, texts.EXPECTED_BUTTON)
        await callback.answer()
        return

    used = await db.count_orders_last_day(user.id)
    if used >= config.max_orders_per_day:
        anchor = data.get("anchor_id")
        await state.clear()
        await utils.edit_or_send(
            bot, chat_id, anchor,
            texts.limit_reached(config.max_orders_per_day),
            kb.limit_reached(),
        )
        await callback.answer()
        return

    labels = answer_labels(answers)
    source = await db.get_user_source(user.id)
    try:
        order_id, created_at = await db.create_order(
            user_id=user.id,
            source=source,
            username=user.username,
            full_name=user.full_name,
            bot_type=labels["bot_type_label"],
            sphere=labels["sphere_label"],
            features=labels["features_label"],
            budget=labels["budget_label"],
            deadline=labels["deadline_label"],
            description=labels["description"],
            contact=labels["contact"],
        )
    except Exception:  # noqa: BLE001 — заполненную форму терять нельзя
        logger.exception("Не удалось сохранить заявку user_id=%s", user.id)
        await callback.answer(texts.ERROR_GENERIC, show_alert=True)
        return

    anchor = data.get("anchor_id")
    await state.clear()
    await utils.edit_or_send(
        bot, chat_id, anchor, texts.order_created(order_id), common_kb.after_order()
    )
    await callback.answer()
    logger.info("Заявка %s создана (user_id=%s)", order_id, user.id)

    card = texts.admin_card(
        order_id, labels, utils.user_line(user), db.to_local(created_at), source
    )
    delivered = await notify_admins(bot, config, card, admin_kb.order_actions(order_id))
    if not delivered:
        logger.error("Заявка %s сохранена, но админ не уведомлён", order_id)


# --------------------------------------------------------------------------
# Текст там, где ждём кнопку
# --------------------------------------------------------------------------
@router.message(StateFilter(*STEP_STATES, OrderForm.confirm, OrderForm.edit))
async def unexpected_input(message: Message, state: FSMContext, bot: Bot) -> None:
    await utils.drop_user_message(bot, message.chat.id, message.message_id)
    step = _step_of_state(await state.get_state())
    if step in STEPS:
        notice = texts.EXPECTED_TEXT if step == "description" else texts.EXPECTED_BUTTON
        await show_step(bot, state, message.chat.id, step, message.from_user, notice)
    else:
        await show_confirm(bot, state, message.chat.id)


@router.message(StateFilter(OrderForm.custom, OrderForm.phone))
async def unexpected_non_text(message: Message, state: FSMContext, bot: Bot) -> None:
    """В состояниях ввода ждём именно текст (не фото/стикер/файл)."""
    await utils.drop_user_message(bot, message.chat.id, message.message_id)
    raw_state = await state.get_state()
    data = await state.get_data()
    if _step_of_state(raw_state) == "phone":
        prompt = texts.PHONE_PROMPT
    else:
        prompt = texts.CUSTOM_PROMPTS.get(data.get("custom_step", ""), texts.EXPECTED_BUTTON)
    await utils.show(
        bot, state, message.chat.id, f"⚠️ {texts.EXPECTED_TEXT}\n\n{prompt}", kb.text_input()
    )
