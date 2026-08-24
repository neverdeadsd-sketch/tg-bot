# Бот приёма заявок на разработку чат-ботов

Telegram-бот на **aiogram 3.x**: собирает заявку по шагам (почти везде — кнопки),
показывает сводку перед отправкой, пишет заявку в SQLite и присылает её админу
с кнопками «Взять в работу» / «Отклонить».

---

## Как устроен диалог

```
/start ─┬─ 📝 Оставить заявку → 7 шагов → 📋 Проверка → 🚀 Отправить
        ├─ 💼 Примеры работ
        ├─ 💰 Цены и сроки
        └─ 💬 Задать вопрос → текст → админу
```

Шаги заявки: тип бота → сфера → функции (мультивыбор) → бюджет → срок →
описание (можно пропустить) → контакт (@username или телефон).

Весь сценарий живёт **в одном сообщении**: бот редактирует его (`edit_text`),
а сообщения пользователя со свободным вводом удаляет — чат не превращается в ленту.
На каждом шаге есть «⬅️ Назад» и «✖️ Отмена», в любой момент работает `/cancel`.

## Что учтено из разбора чужих ботов

| Типичная ошибка | Как решено здесь |
|---|---|
| Простыня текста на `/start` | Приветствие в 4 строки: кто мы, сколько шагов, кнопки |
| Нет «Назад», ошибку не исправить | «Назад» на каждом шаге; с первого шага — в меню |
| Свободный ввод там, где хватило бы кнопок | Кнопки на 5 шагах из 7; текст только для описания и телефона |
| Заявка уходит без подтверждения | Экран сводки + «Изменить» (правка одного поля, возврат к сводке) |
| Лента из новых сообщений, контекст теряется | Один «якорный» экран + счётчик «Шаг N/7» |
| Тупик после «Другое» | «Другое» просит одну строку текста, а не бросает пользователя |
| Спам заявками и двойные нажатия | Лимит 3 заявки / 24 ч на `user_id` + троттлинг колбэков |
| Молчание после отправки | Номер заявки пользователю, карточка с кнопками — админу |

## Стек

- Python 3.10+
- aiogram 3.x (long polling, FSM, inline-клавиатуры)
- SQLite через aiosqlite (WAL)
- python-dotenv

## Структура

```
main.py              точка входа: Bot, Dispatcher, middleware, polling
config.py            чтение и валидация .env
db.py                схема и запросы SQLite, экспорт CSV
texts.py             ВСЕ тексты и справочники вариантов
utils.py             валидация ввода, работа с «якорным» сообщением
callbacks.py         фабрики callback_data
handlers/
  common.py          /start, /cancel, меню, вопросы, фолбэки
  order.py           FSM заявки: шаги, назад, проверка, отправка
  admin.py           /stats, /orders, /order, /export, статусы заявок
keyboards/
  common.py          меню и навигационные ряды
  order.py           клавиатуры шагов (не больше 2 кнопок в ряд)
  admin.py           действия по заявке и пагинация
middlewares/
  throttling.py      антифлуд по user_id
```

Тексты и списки вариантов правятся **только в `texts.py`** — коды вариантов
(`lead`, `b3`, `d2`) уходят в `callback_data`, подписи можно менять свободно.

---

## Запуск локально

```bash
git clone <repo> tg-bot && cd tg-bot

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# впишите BOT_TOKEN от @BotFather и свой ADMIN_ID (узнать: @userinfobot)

python main.py
```

В логе должно появиться `Запуск @your_bot (id=...)`. Откройте бота и нажмите `/start`.

### Переменные окружения

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `BOT_TOKEN` | — | Токен от @BotFather (обязательно) |
| `ADMIN_ID` | — | ID админа; несколько — через запятую (обязательно) |
| `DB_PATH` | `data/bot.db` | Файл SQLite |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `MAX_ORDERS_PER_DAY` | `3` | Лимит заявок с одного `user_id` за 24 часа |
| `THROTTLE_CALLBACK` | `0.4` | Минимальный интервал между нажатиями, сек |
| `THROTTLE_MESSAGE` | `0.5` | То же для сообщений, сек |
| `REQUEST_TIMEOUT` | `60` | Таймаут запросов к Telegram API, сек |
| `ORDERS_PAGE_SIZE` | `10` | Заявок на страницу в `/orders` |

### Команды

Пользователю: `/start`, `/cancel`, `/help`.
Админу дополнительно (видны только ему):

| Команда | Что делает |
|---|---|
| `/stats` | Заявки за 24 часа, за 7 дней, всего + разбивка по статусам |
| `/orders` | Последние заявки постранично (кнопки ⬅️ ➡️) |
| `/order 12` | Полная карточка заявки по номеру |
| `/export` | Выгрузка всех заявок в CSV (`;`, UTF-8 с BOM — Excel открывает как есть) |

---

## Деплой на VPS через systemd

Дальше — Ubuntu/Debian, бот работает от отдельного пользователя `botuser`.

### 1. Пользователь и код

```bash
sudo adduser --system --group --home /opt/tg-bot botuser
sudo -u botuser git clone <repo> /opt/tg-bot
cd /opt/tg-bot
```

### 2. Окружение

```bash
sudo apt update && sudo apt install -y python3-venv
sudo -u botuser python3 -m venv /opt/tg-bot/.venv
sudo -u botuser /opt/tg-bot/.venv/bin/pip install -r /opt/tg-bot/requirements.txt

sudo -u botuser cp /opt/tg-bot/.env.example /opt/tg-bot/.env
sudo -u botuser nano /opt/tg-bot/.env       # BOT_TOKEN и ADMIN_ID
sudo chmod 600 /opt/tg-bot/.env             # токен не должен читаться всеми
```

### 3. Unit-файл

`sudo nano /etc/systemd/system/tg-bot.service`

```ini
[Unit]
Description=Telegram bot: приём заявок
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=botuser
Group=botuser
WorkingDirectory=/opt/tg-bot
ExecStart=/opt/tg-bot/.venv/bin/python /opt/tg-bot/main.py
Restart=always
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=20
Environment=PYTHONUNBUFFERED=1
Environment=TZ=Europe/Moscow

# Логи уходят в journald
StandardOutput=journal
StandardError=journal

# Минимальные привилегии
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=/opt/tg-bot/data

[Install]
WantedBy=multi-user.target
```

### 4. Запуск

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tg-bot
sudo systemctl status tg-bot
```

### 5. Эксплуатация

```bash
journalctl -u tg-bot -f              # живой лог
journalctl -u tg-bot --since "1 hour ago"
sudo systemctl restart tg-bot        # после правки .env или кода
```

Обновление:

```bash
cd /opt/tg-bot
sudo -u botuser git pull
sudo -u botuser /opt/tg-bot/.venv/bin/pip install -r requirements.txt
sudo systemctl restart tg-bot
```

Бэкап базы (SQLite в режиме WAL, копировать на ходу безопасно только так):

```bash
sudo -u botuser /opt/tg-bot/.venv/bin/python - <<'PY'
import sqlite3
src = sqlite3.connect("/opt/tg-bot/data/bot.db")
dst = sqlite3.connect("/opt/tg-bot/data/backup.db")
src.backup(dst); dst.close(); src.close()
PY
```

---

## Заметки по эксплуатации

- **Состояние FSM хранится в памяти.** После рестарта незаконченные заявки
  теряются: старые кнопки отвечают «Кнопка устарела, нажмите /start».
  Нужна устойчивость — подключите `RedisStorage` в `main.py`, схема БД не меняется.
- **Один бот — один процесс.** Long polling не терпит двух запущенных копий:
  Telegram отдаст `409 Conflict`.
- **Лимит заявок** считается скользящим окном в 24 часа, не по календарным суткам.
- **Часовой пояс** для отображения дат берётся из `TZ` процесса (в unit-файле выше — `Europe/Moscow`);
  в базе всё хранится в UTC.
- **Ошибки** ловит глобальный `errors`-хендлер: пользователь видит короткое
  сообщение, полный traceback уходит в лог.
