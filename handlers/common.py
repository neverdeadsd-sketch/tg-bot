"""Меню, команды /start и /cancel, вопросы и обработка «протухших» кнопок."""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message

import db
import texts
import utils
from callbacks import MenuCB, OrderCB
from config import BASE_DIR, Config
from handlers.admin import notify_admins
from keyboards import common as kb

logger = logging.getLogger(__name__)

# Команды живут в отдельном роутере: он подключается раньше FSM-обработчиков,
# иначе /cancel во время шага с текстовым вводом улетел бы в описание задачи.
system_router = Router(name="system")
router = Router(name="common")


class QuestionForm(StatesGroup):
    waiting = State()


WELCOME_IMAGE = BASE_DIR / "assets" / "welcome.png"
# file_id первой удачной отправки: Telegram отдаёт картинку по нему сам,
# файл больше не заливается при каждом /start.
_welcome_file_id: str | None = None


async def _send_welcome_image(bot: Bot, chat_id: int) -> None:
    """Приветственный баннер. Нет файла или не отправился — просто пропускаем."""
    global _welcome_file_id

    if _welcome_file_id:
        try:
            await bot.send_photo(chat_id, _welcome_file_id)
            return
        except TelegramAPIError as error:
            logger.debug("file_id баннера устарел: %s", error)
            _welcome_file_id = None

    if not WELCOME_IMAGE.exists():
        logger.debug("Баннер не найден: %s", WELCOME_IMAGE)
        return
    try:
        message = await bot.send_photo(chat_id, FSInputFile(WELCOME_IMAGE))
    except TelegramAPIError:
        logger.warning("Не удалось отправить баннер", exc_info=True)
        return
    if message.photo:
        _welcome_file_id = message.photo[-1].file_id


async def _reset_anchor(bot: Bot, state: FSMContext, chat_id: int) -> None:
    """Снимаем клавиатуру со старого экрана, чтобы не было двух активных."""
    data = await state.get_data()
    anchor = data.get("anchor_id")
    if not anchor:
        return
    try:
        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=anchor, reply_markup=None)
    except TelegramAPIError as error:
        logger.debug("Старый экран недоступен: %s", error)


# --------------------------------------------------------------------------
# Команды
# --------------------------------------------------------------------------
@system_router.message(CommandStart())
async def cmd_start(
    message: Message, state: FSMContext, bot: Bot, command: CommandObject
) -> None:
    user = message.from_user
    # Метка из ссылки вида t.me/бот?start=avito — так видно, какой канал работает
    source = db.clean_source(command.args)
    await db.remember_user(
        user_id=user.id, username=user.username, full_name=user.full_name, source=source
    )

    await _reset_anchor(bot, state, message.chat.id)
    await state.clear()
    await _send_welcome_image(bot, message.chat.id)
    sent = await message.answer(
        texts.greeting(user.first_name or "друг"), reply_markup=kb.main_menu()
    )
    await utils.set_anchor(state, sent.message_id)
    logger.info("/start от user_id=%s, источник=%s", user.id, source or "—")


@system_router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, bot: Bot) -> None:
    current = await state.get_state()
    await utils.drop_user_message(bot, message.chat.id, message.message_id)
    if current is None:
        sent = await message.answer(texts.NOTHING_TO_CANCEL, reply_markup=kb.main_menu())
        await utils.set_anchor(state, sent.message_id)
        return
    data = await state.get_data()
    anchor = data.get("anchor_id")
    await state.clear()
    message_id = await utils.edit_or_send(
        bot, message.chat.id, anchor,
        f"{texts.CANCELLED}\n\n{texts.MENU_TITLE}", kb.main_menu(),
    )
    await utils.set_anchor(state, message_id)


@system_router.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext) -> None:
    sent = await message.answer(texts.MENU_TITLE, reply_markup=kb.main_menu())
    await utils.set_anchor(state, sent.message_id)


# --------------------------------------------------------------------------
# Экраны меню
# --------------------------------------------------------------------------
@router.callback_query(MenuCB.filter(F.action.in_({"home", "examples", "pricing"})))
async def menu_screen(
    callback: CallbackQuery, callback_data: MenuCB, state: FSMContext, bot: Bot
) -> None:
    await state.set_state(None)
    if callback.message:
        await state.update_data(anchor_id=callback.message.message_id)
    chat_id = callback.message.chat.id if callback.message else callback.from_user.id

    if callback_data.action == "examples":
        text, markup = texts.EXAMPLES, kb.info_screen()
    elif callback_data.action == "pricing":
        text, markup = texts.PRICING, kb.info_screen()
    else:
        text, markup = texts.MENU_TITLE, kb.main_menu()

    await utils.show(bot, state, chat_id, text, markup)
    await callback.answer()


@router.callback_query(MenuCB.filter(F.action == "question"))
async def ask_question(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if callback.message:
        await state.update_data(anchor_id=callback.message.message_id)
    await state.set_state(QuestionForm.waiting)
    chat_id = callback.message.chat.id if callback.message else callback.from_user.id
    await utils.show(bot, state, chat_id, texts.QUESTION_PROMPT, kb.question_screen())
    await callback.answer()


@router.message(QuestionForm.waiting, F.text)
async def receive_question(
    message: Message, state: FSMContext, bot: Bot, config: Config
) -> None:
    await utils.drop_user_message(bot, message.chat.id, message.message_id)
    value, error = utils.validate_text(
        message.text or "", min_len=5, max_len=utils.QUESTION_LIMIT
    )
    if error:
        notice = texts.BAD_TEXT_SHORT if error == "short" else texts.BAD_TEXT_LONG.format(
            limit=utils.QUESTION_LIMIT
        )
        await utils.show(
            bot, state, message.chat.id,
            f"⚠️ {notice}\n\n{texts.QUESTION_PROMPT}", kb.question_screen(),
        )
        return

    user = message.from_user
    question_id = await db.create_question(
        user_id=user.id, username=user.username, full_name=user.full_name, text=value
    )
    data = await state.get_data()
    anchor = data.get("anchor_id")
    await state.clear()
    message_id = await utils.edit_or_send(
        bot, message.chat.id, anchor,
        texts.question_sent(user.first_name or "друг"), kb.back_to_menu(),
    )
    await utils.set_anchor(state, message_id)
    await notify_admins(
        bot, config, texts.admin_question(question_id, utils.user_line(user), value)
    )
    logger.info("Вопрос %s от user_id=%s", question_id, user.id)


@router.message(QuestionForm.waiting)
async def question_non_text(message: Message, state: FSMContext, bot: Bot) -> None:
    await utils.drop_user_message(bot, message.chat.id, message.message_id)
    await utils.show(
        bot, state, message.chat.id,
        f"⚠️ {texts.EXPECTED_TEXT}\n\n{texts.QUESTION_PROMPT}", kb.question_screen(),
    )


# --------------------------------------------------------------------------
# Фолбэки
# --------------------------------------------------------------------------
@router.callback_query(OrderCB.filter())
async def stale_order_button(callback: CallbackQuery) -> None:
    """Кнопка из старого сообщения: состояние потеряно после рестарта."""
    await callback.answer(texts.SESSION_EXPIRED, show_alert=True)


@router.callback_query()
async def unknown_callback(callback: CallbackQuery) -> None:
    logger.debug("Неизвестный callback: %s", callback.data)
    await callback.answer(texts.SESSION_EXPIRED, show_alert=True)


@router.message(StateFilter(None))
async def fallback_message(message: Message, state: FSMContext) -> None:
    sent = await message.answer(texts.MENU_TITLE, reply_markup=kb.main_menu())
    await utils.set_anchor(state, sent.message_id)
