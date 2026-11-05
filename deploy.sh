#!/usr/bin/env bash
#
# Установка и обновление memebot на сервере (Ubuntu/Debian).
# Ставит Docker, если его нет, скачивает бота в /opt/memebot, спрашивает токен и ID,
# запускает. Повторный запуск обновляет код и не трогает .env и базу.
#
#   curl -fsSL https://raw.githubusercontent.com/neverdeadsd-sketch/tg-bot/claude/memebot/deploy.sh | bash
#
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/memebot}"
REPO="${REPO:-https://github.com/neverdeadsd-sketch/tg-bot.git}"
BRANCH="${BRANCH:-claude/memebot}"

say()  { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
ok()   { printf '    \033[0;32m✓\033[0m %s\n' "$*"; }
warn() { printf '    \033[0;33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[0;31mОстановлено:\033[0m %s\n\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Запусти от root или через sudo."
command -v apt-get >/dev/null 2>&1 || die "Скрипт рассчитан на Ubuntu и Debian."

case "$APP_DIR" in
  /opt/*|/srv/*) ;;
  *) die "APP_DIR=$APP_DIR — ожидался каталог внутри /opt или /srv" ;;
esac

# ------------------------------------------------------------------ Docker --
say "Docker"
if ! command -v docker >/dev/null 2>&1; then
  command -v curl >/dev/null 2>&1 || { apt-get update -qq && apt-get install -y -qq curl; }
  curl -fsSL https://get.docker.com | sh
  ok "Docker установлен"
else
  ok "уже установлен: $(docker --version)"
fi
if ! docker compose version >/dev/null 2>&1; then
  apt-get update -qq && apt-get install -y -qq docker-compose-plugin
fi
systemctl enable --now docker >/dev/null 2>&1 || true
docker compose version >/dev/null 2>&1 || die "docker compose не работает — пришли вывод команды: docker compose version"
ok "docker compose работает"

# -------------------------------------------------------------------- код --
say "Код бота → $APP_DIR"
command -v git >/dev/null 2>&1 || { apt-get update -qq && apt-get install -y -qq git; }
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
  git -C "$APP_DIR" reset --quiet --hard "origin/$BRANCH"   # .env и data/ не в git — не затрагиваются
  ok "обновлён до $(git -C "$APP_DIR" log -1 --format=%h)"
else
  git clone --quiet --branch "$BRANCH" --single-branch "$REPO" "$APP_DIR"
  ok "скачан"
fi
cd "$APP_DIR"

# ---------------------------------------------------------------- настройки --
say "Настройки (.env)"
if [ -f .env ]; then
  ok "уже есть — не трогаю (править: nano $APP_DIR/.env)"
else
  [ -r /dev/tty ] || die "Нет терминала для вопросов. Создай $APP_DIR/.env из .env.example вручную и запусти скрипт снова."
  cp .env.example .env
  chmod 600 .env

  while :; do
    read -rp "    Токен бота от @BotFather: " TOKEN < /dev/tty
    TOKEN="$(printf '%s' "$TOKEN" | tr -d '[:space:]')"
    [[ "$TOKEN" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]] && break
    warn "не похоже на токен (пример: 123456789:AAH...). Попробуй ещё раз."
  done
  while :; do
    read -rp "    Твой Telegram ID (число от @userinfobot): " ADMIN < /dev/tty
    ADMIN="$(printf '%s' "$ADMIN" | tr -d '[:space:]')"
    [[ "$ADMIN" =~ ^-?[0-9]+$ ]] && break
    warn "нужно только число. Попробуй ещё раз."
  done

  sed -i "s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=$TOKEN|" .env
  sed -i "s|^ADMIN_CHAT_ID=.*|ADMIN_CHAT_ID=$ADMIN|" .env
  ok "сохранено, режим: бумажный (виртуальные SOL)"
fi

# ----------------------------------------------------------------- запуск --
say "Запуск"
docker compose up -d --build
sleep 8
state="$(docker inspect -f '{{.State.Status}} {{.State.Restarting}}' memebot 2>/dev/null || echo 'нет false')"
docker compose logs --tail 15
if [ "$state" = "running false" ]; then
  ok "бот работает"
  cat <<EOF

  Дальше:
    1. Открой своего бота в Telegram и нажми Start.
    2. Отправь /status, потом /scan — увидишь, что бот находит на рынке.

  Логи:        cd $APP_DIR && docker compose logs -f
  Настройки:   nano $APP_DIR/.env   затем   cd $APP_DIR && docker compose up -d
  Обновить:    запусти эту же команду установки ещё раз
  Остановить:  cd $APP_DIR && docker compose down

EOF
else
  die "бот не запустился (состояние: $state). Пришли последние строки лога выше."
fi
