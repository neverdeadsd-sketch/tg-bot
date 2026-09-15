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
SHOP_ID_DEFAULT='139865'

red()  { printf '\033[0;31m%s\033[0m\n' "$*" >&2; }
grn()  { printf '\033[0;32m✓\033[0m %s\n' "$*"; }
ylw()  { printf '\033[0;33m%s\033[0m\n' "$*"; }
die()  { red "✗ $*"; exit 1; }

[ -d "$BOT_DIR" ] || die "Нет каталога $BOT_DIR. Укажите его: sudo BOT_DIR=... bash $0"
[ -f "$BOT_DIR/config.py" ] || die "В $BOT_DIR нет config.py — это точно каталог бота?"
command -v python3 >/dev/null || die 'нужен python3'

echo "Бот: $BOT_DIR"

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

if not re.search(r'\b_env\s*\(', src):
    print('\033[0;33mconfig.py читает окружение не через _env — допишите сами:\033[0m')
    for n in missing:
        print(f'  {n} = os.getenv("{n}", "")')
    raise SystemExit

lines = src.splitlines(keepends=True)
# Встаём сразу за последним присваиванием вида ИМЯ = _env(...) на верхнем
# уровне: там же, где живут остальные ключи, а не в конце файла среди
# производных значений.
last = max((i for i, l in enumerate(lines)
            if re.match(r'^[A-Z][A-Z0-9_]*\s*=\s*_env\(', l)), default=None)
if last is None:
    print('\033[0;33mНе нашлось, куда вписать. Допишите сами:\033[0m')
    for n in missing:
        print(f'  {n} = _env("{n}")')
    raise SystemExit

block = ['\n', '# Оплата картой через ЮKassa. shop id не секрет, ключ — секрет.\n']
block += [f'{n} = _env("{n}")\n' for n in missing]
new = ''.join(lines[:last + 1] + block + lines[last + 1:])

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

# --- тесты -----------------------------------------------------------------
echo
echo 'Тесты модуля:'
( cd "$HERE" && python3 -m unittest discover -s test 2>&1 | tail -3 )

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
python3 "$HERE/report-hooks.py" "$BOT_DIR"
