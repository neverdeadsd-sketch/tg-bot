#!/usr/bin/env bash
#
# Готовит код бота к отправке в приватный репозиторий.
#
#   sudo bash /opt/hollvpn/tools/bot-yookassa/share-bot.sh
#
# Сам не пушит: для этого нужны ваши учётные данные. Он делает то, на чём
# легко ошибиться, — исключает всё, что нельзя публиковать, и проверяет,
# что в подготовленном к отправке наборе не осталось ни одного секрета.
# Найдёт хоть один — остановится.
#
# Код бота секретов не содержит: токен, пути к панели, uuid администратора
# и реквизиты лежат в .env, и .env сюда не попадёт.
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Запускать вчерашнюю копию — значит получать вчерашнее поведение.
# shellcheck source=_fresh.sh
. "$HERE/_fresh.sh"
_freshen "$@"

BOT_DIR="${BOT_DIR:-/opt/tg-bot}"

red() { printf '\033[0;31m%s\033[0m\n' "$*" >&2; }
grn() { printf '\033[0;32m✓\033[0m %s\n' "$*"; }
ylw() { printf '\033[0;33m%s\033[0m\n' "$*"; }
die() { red "✗ $*"; exit 1; }

[ -d "$BOT_DIR" ] || die "Нет каталога $BOT_DIR"
command -v git >/dev/null || die 'нужен git'
cd "$BOT_DIR"

# --- что никогда не уходит -------------------------------------------------
IGNORE='.env
.env.*
*.db
*.db-journal
*.sqlite
*.sqlite3
*.session
*.log
venv/
.venv/
env/
__pycache__/
*.pyc'

if [ -f .gitignore ]; then
  cp .gitignore ".gitignore.before-$(date +%Y%m%d-%H%M%S)"
fi
# Дописываем недостающее, не выбрасывая то, что уже есть.
while IFS= read -r line; do
  grep -qxF "$line" .gitignore 2>/dev/null || printf '%s\n' "$line" >> .gitignore
done <<< "$IGNORE"
grn '.gitignore закрывает .env, базу, venv и сессии'

[ -d .git ] || { git init -q; grn 'git init'; }
git add -A

# --- проверка: не осталось ли секретов в том, что уйдёт --------------------
# Смотрим именно на подготовленное к отправке, а не на каталог: важно,
# что уедет, а не что лежит рядом.
staged=$(git diff --cached --name-only)
[ -n "$staged" ] || die 'Нечего отправлять: git add ничего не набрал.'

bad=''
# Файлы, которых быть не должно.
while IFS= read -r f; do
  case "$f" in
    .env|.env.*|*.db|*.sqlite|*.sqlite3|*.session|venv/*|.venv/*)
      bad="$bad\n  файл целиком: $f" ;;
  esac
done <<< "$staged"

# Значения, которых быть не должно. Ищем по содержимому, а не по имени:
# секрет, вписанный в обычный .py, именем себя не выдаст.
PAT='[0-9]{8,10}:AA[A-Za-z0-9_-]{30,}|live_[A-Za-z0-9_-]{30,}|test_[A-Za-z0-9_-]{40,}|-----BEGIN [A-Z ]*PRIVATE KEY-----'
while IFS= read -r f; do
  [ -f "$f" ] || continue
  if hit=$(grep -nEo "$PAT" "$f" 2>/dev/null | head -1); then
    bad="$bad\n  значение в $f (строка ${hit%%:*})"
  fi
done <<< "$staged"

if [ -n "$bad" ]; then
  git reset -q
  red '✗ В отправку попало то, что публиковать нельзя:'
  printf "$bad\n" >&2
  echo
  ylw 'Ничего не отправлено и ничего не закоммичено. Уберите найденное'
  ylw 'в .env и запустите ещё раз.'
  exit 1
fi

count=$(printf '%s\n' "$staged" | wc -l)
grn "к отправке $count файлов, секретов среди них нет"

if git diff --cached --quiet; then
  grn 'коммитить нечего — всё уже зафиксировано'
else
  git -c user.name="$(whoami)" -c user.email="$(whoami)@$(hostname)" \
      commit -q -m 'Код бота HollVPN'
  grn 'коммит создан'
fi

cat <<'TEXT'

────────────────────────────────────────────────────────────────────────
Дальше — руками, потому что нужны ваши учётные данные GitHub.

1. Создайте ПРИВАТНЫЙ репозиторий: github.com/new
   Имя, например, hollvpn-bot. Обязательно Private — публичным код бота
   делать незачем.

2. Отправьте:

   git remote add origin https://github.com/<ваш-логин>/hollvpn-bot.git
   git branch -M main
   git push -u origin main

3. Скажите мне его имя — подключу к сессии и допишу оплату прямо в коде.
────────────────────────────────────────────────────────────────────────
TEXT
