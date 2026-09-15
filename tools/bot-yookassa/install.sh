#!/usr/bin/env bash
#
# Установка оплаты через ЮKassa в бота.
#
#   sudo bash /opt/hollvpn/tools/bot-yookassa/install.sh
#   sudo BOT_DIR=/путь/к/боту bash .../install.sh
#
# Делает механическую часть: кладёт модуль рядом с кодом бота, заводит
# переменные в .env, дописывает две строки в config.py и прогоняет тесты.
# Повторный запуск ничего не портит: всё, что уже сделано, пропускается.
#
# Секретный ключ спрашивается с клавиатуры и не появляется ни на экране,
# ни в истории команд, ни в списке процессов — только в .env с правами 600.
#
# Две зацепки в коде бота — выдача подписки и кнопка оплаты — остаются
# за человеком: их места скрипт находит и печатает в конце.
#
set -euo pipefail

BOT_DIR="${BOT_DIR:-/opt/tg-bot}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Запускать вчерашнюю копию — значит получать вчерашнее поведение.
# shellcheck source=_fresh.sh
. "$HERE/_fresh.sh"
_freshen "$@"
SHOP_ID_DEFAULT='139865'

red()  { printf '\033[0;31m%s\033[0m\n' "$*" >&2; }
grn()  { printf '\033[0;32m✓\033[0m %s\n' "$*"; }
ylw()  { printf '\033[0;33m%s\033[0m\n' "$*"; }
die()  { red "✗ $*"; exit 1; }

[ -d "$BOT_DIR" ] || die "Нет каталога $BOT_DIR. Укажите его: sudo BOT_DIR=... bash $0"
[ -f "$BOT_DIR/config.py" ] || die "В $BOT_DIR нет config.py — это точно каталог бота?"
command -v python3 >/dev/null || die 'нужен python3'

echo "Бот: $BOT_DIR"

# --- чем бот запускается ---------------------------------------------------
# Зависимости модуля (aiohttp, aiosqlite) стоят там же, где aiogram, —
# то есть в окружении бота, а не в системном python. Проверять модуль
# системным значит проверять не то окружение, в котором он будет жить.
BOT_PY=''
for candidate in "$BOT_DIR/venv/bin/python" "$BOT_DIR/.venv/bin/python" \
                 "$BOT_DIR/env/bin/python" "$BOT_DIR/venv/bin/python3" \
                 "$BOT_DIR/.venv/bin/python3"; do
  [ -x "$candidate" ] && { BOT_PY="$candidate"; break; }
done
if [ -z "$BOT_PY" ]; then
  # Спрашиваем systemd: в ExecStart записан ровно тот интерпретатор,
  # которым бот запускается на самом деле.
  unit=$(grep -rls "$BOT_DIR" /etc/systemd/system/*.service 2>/dev/null | head -1 || true)
  if [ -n "$unit" ]; then
    exec_py=$(grep -m1 '^ExecStart=' "$unit" | sed -E 's/^ExecStart=//' | awk '{print $1}')
    [ -x "$exec_py" ] && BOT_PY="$exec_py"
    [ -n "$unit" ] && grn "юнит systemd: $(basename "$unit")"
  fi
fi
if [ -n "$BOT_PY" ]; then
  grn "интерпретатор бота: $BOT_PY"
else
  BOT_PY='python3'
  ylw 'Окружение бота не нашлось — проверяю системным python3.'
  ylw 'Если бот живёт в venv, укажите его: BOT_PY=/путь/к/venv/bin/python'
fi
BOT_PY="${BOT_PY_OVERRIDE:-$BOT_PY}"

# --- куда класть модуль ----------------------------------------------------
# Рядом с config.py, внутрь того же пакета, что и остальной код бота.
if [ -d "$BOT_DIR/app" ]; then
  PKG="$BOT_DIR/app"; IMPORT='app.payments'
else
  PKG="$BOT_DIR";     IMPORT='payments'
fi
DEST="$PKG/payments"

if [ -d "$DEST" ] && ! diff -rq "$HERE/payments" "$DEST" \
     --exclude='__pycache__' >/dev/null 2>&1; then
  ylw "В $DEST уже лежит другая версия модуля — сохраняю её рядом."
  mv "$DEST" "$DEST.before-$(date +%Y%m%d-%H%M%S)"
fi
mkdir -p "$DEST"
cp "$HERE"/payments/*.py "$DEST"/
grn "модуль в $DEST (импорт: $IMPORT)"

# --- .env ------------------------------------------------------------------
ENV="$BOT_DIR/.env"
[ -f "$ENV" ] || { touch "$ENV"; chmod 600 "$ENV"; }

have_key() { grep -qE "^[[:space:]]*$1[[:space:]]*=" "$ENV"; }

if have_key YOOKASSA_SHOP_ID; then
  grn 'YOOKASSA_SHOP_ID уже в .env'
else
  printf 'YOOKASSA_SHOP_ID=%s\n' "$SHOP_ID_DEFAULT" >> "$ENV"
  grn "YOOKASSA_SHOP_ID=$SHOP_ID_DEFAULT добавлен в .env"
fi

if have_key YOOKASSA_SECRET_KEY; then
  grn 'YOOKASSA_SECRET_KEY уже в .env — не трогаю'
else
  echo
  echo 'Секретный ключ: кабинет ЮKassa → Интеграция → Ключи API.'
  echo 'Он не отобразится при вводе — это нормально.'
  printf 'YOOKASSA_SECRET_KEY: '
  # -s: ключ не попадает ни на экран, ни в историю.
  read -rs SECRET || true
  echo
  if [ -z "${SECRET:-}" ]; then
    ylw 'Ключ не введён. Допишите строку сами:'
    ylw "  echo 'YOOKASSA_SECRET_KEY=ключ' >> $ENV"
  else
    printf 'YOOKASSA_SECRET_KEY=%s\n' "$SECRET" >> "$ENV"
    unset SECRET
    grn 'YOOKASSA_SECRET_KEY добавлен в .env'
  fi
fi
chmod 600 "$ENV"

# --- config.py -------------------------------------------------------------
# Дописываем в том же виде, в каком там читаются остальные переменные,
# и проверяем, что файл после правки разбирается. Не разобрался —
# возвращаем как было: неработающий config.py останавливает бота целиком.
python3 - "$BOT_DIR/config.py" <<'PY'
import ast, pathlib, re, shutil, sys, time

path = pathlib.Path(sys.argv[1])
src = path.read_text(encoding='utf-8')

needed = ['YOOKASSA_SHOP_ID', 'YOOKASSA_SECRET_KEY']
missing = [n for n in needed
           if not re.search(rf'^\s*{n}\s*=', src, re.M)]
if not missing:
    print('\033[0;32m✓\033[0m config.py: переменные уже есть')
    raise SystemExit

lines = src.splitlines(keepends=True)

# Пишем в том же виде, в каком config.py читает остальные переменные:
# у файла уже есть свой способ, и вводить рядом второй — значит оставить
# следующему читателю загадку, почему их два.
STYLES = [
    (r'^[A-Z][A-Z0-9_]*\s*=\s*_env\(',            '{n} = _env("{n}")'),
    (r'^[A-Z][A-Z0-9_]*\s*=\s*os\.getenv\(',      '{n} = os.getenv("{n}", "")'),
    (r'^[A-Z][A-Z0-9_]*\s*=\s*os\.environ\.get\(', '{n} = os.environ.get("{n}", "")'),
]

anchor, template = None, None
for pattern, tpl in STYLES:
    hit = max((i for i, l in enumerate(lines) if re.match(pattern, l)), default=None)
    if hit is not None and (anchor is None or hit > anchor):
        anchor, template = hit, tpl

if anchor is None:
    print('\033[0;33mНе нашлось, куда вписать: config.py не читает окружение')
    print('ни через _env, ни через os.getenv. Допишите сами, рядом с остальными:\033[0m')
    for n in missing:
        print(f'  {n} = os.getenv("{n}", "")')
    raise SystemExit

block = ['\n', '# Оплата картой через ЮKassa. shop id не секрет, ключ — секрет.\n']
block += [template.format(n=n) + '\n' for n in missing]
new = ''.join(lines[:anchor + 1] + block + lines[anchor + 1:])

# os.getenv без import os — это AttributeError при старте бота.
if 'os.' in template and not re.search(r'^\s*import os\b', new, re.M):
    new = 'import os\n' + new

try:
    ast.parse(new)
except SyntaxError as e:
    print(f'\033[0;31m✗\033[0m После правки config.py не разбирается ({e}) — не трогаю.')
    raise SystemExit(1)

backup = path.with_suffix(f'.py.before-{time.strftime("%Y%m%d-%H%M%S")}')
shutil.copy2(path, backup)
path.write_text(new, encoding='utf-8')
print(f'\033[0;32m✓\033[0m config.py: добавлены {", ".join(missing)} (копия: {backup.name})')
PY

# --- проверки в окружении бота --------------------------------------------
# Ни одна из них не должна обрывать установку. Самое ценное здесь —
# отчёт в конце, и потерять его из-за упавшей проверки было бы обидно:
# первый же настоящий прогон так и закончился, ничего не напечатав.
echo
echo 'Проверки:'

# Модуль должен импортироваться именно у бота: там, где стоит aiogram,
# стоят и aiohttp с aiosqlite. Если импорт не прошёл — оплата не поднимется
# при старте, и узнать об этом сейчас дешевле, чем ночью по тишине в заказах.
if out=$("$BOT_PY" -c "
import sys; sys.path.insert(0, '$PKG')
import payments                       # noqa: F401
print('ok')
" 2>&1); then
  grn "модуль импортируется ($BOT_PY)"
else
  red "✗ модуль не импортируется интерпретатором $BOT_PY:"
  printf '%s\n' "$out" | tail -3 | sed 's/^/    /'
  ylw '  Скорее всего не хватает aiohttp или aiosqlite. Поставьте их тем же'
  ylw '  интерпретатором, которым запускается бот, и повторите установку:'
  echo "    sudo $BOT_PY -m pip install aiohttp aiosqlite"
fi

# Тесты гоняем системным python: им нужен только stdlib и те же два пакета.
# Падение здесь — повод посмотреть, а не повод остановить установку.
if out=$( cd "$HERE" && "$BOT_PY" -m unittest discover -s test 2>&1 ); then
  grn "тесты модуля: $(printf '%s' "$out" | grep -E '^Ran ' || echo пройдены)"
else
  ylw 'Тесты не прошли:'
  printf '%s\n' "$out" | tail -12 | sed 's/^/    /'
fi

# .env сам по себе ничего не делает: его должен кто-то прочитать.
# Если не читает никто, ключ в файле есть, а у бота его нет — и оплата
# молча не работает, без единой ошибки в журнале.
if grep -rqs 'load_dotenv' "$BOT_DIR" --include='*.py'; then
  grn '.env читается через load_dotenv'
elif grep -rqs 'EnvironmentFile' /etc/systemd/system/*.service 2>/dev/null; then
  grn '.env передаётся через systemd (EnvironmentFile)'
else
  ylw '⚠ Не видно, чтобы .env кто-то читал: ни load_dotenv в коде,'
  ylw '  ни EnvironmentFile в юните systemd. Тогда записанное в .env'
  ylw '  до бота не доходит, и оплата не заработает молча.'
  ylw '  Проверьте, откуда бот берёт BOT_TOKEN, — ключи ЮKassa нужны оттуда же.'
fi

# --- что осталось ----------------------------------------------------------
cat <<TEXT

────────────────────────────────────────────────────────────────────────
Механическая часть готова. Осталось две зацепки в коде бота:

  1. выдать подписку после оплаты
  2. кнопка «оплатить картой» в покупке

Ниже — места, где они, скорее всего, живут. Здесь только имена функций
и их аргументы: ни строк, ни значений, ни токенов. Этот вывод можно
показывать целиком.
────────────────────────────────────────────────────────────────────────

TEXT
python3 "$HERE/report-hooks.py" "$BOT_DIR" || true
