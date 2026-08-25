#!/usr/bin/env bash
# Установка бота на чистый Ubuntu/Debian VPS. Запускать от root:
#   sudo bash deploy/install.sh [git-url] [ветка]
# Скрипт идемпотентный: повторный запуск обновляет код и перезапускает сервис.
set -euo pipefail

REPO_URL="${1:-https://github.com/neverdeadsd-sketch/tg-bot.git}"
BRANCH="${2:-claude/telegram-chatbot-request-bot-ng1lsi}"
APP_DIR="/opt/tg-bot"
APP_USER="botuser"
SERVICE="tg-bot"

log() { printf '\n\033[1;34m==>\033[0m %s\n' "$1"; }

if [[ $EUID -ne 0 ]]; then
    echo "Запускайте через sudo: sudo bash deploy/install.sh" >&2
    exit 1
fi

log "Ставим системные пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git

log "Создаём пользователя ${APP_USER}"
if ! id -u "$APP_USER" >/dev/null 2>&1; then
    adduser --system --group --home "$APP_DIR" --disabled-login "$APP_USER"
fi
mkdir -p "$APP_DIR"

log "Забираем код (${BRANCH})"
if [[ -d "$APP_DIR/.git" ]]; then
    git -C "$APP_DIR" fetch origin "$BRANCH"
    git -C "$APP_DIR" checkout "$BRANCH"
    git -C "$APP_DIR" reset --hard "origin/$BRANCH"
else
    git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
mkdir -p "$APP_DIR/data"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

log "Виртуальное окружение и зависимости"
if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
    sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
fi
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

log "Конфигурация"
if [[ ! -f "$APP_DIR/.env" ]]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env"
    echo
    echo "  ВНИМАНИЕ: создан $APP_DIR/.env с заглушками."
    echo "  Впишите BOT_TOKEN и ADMIN_ID:  nano $APP_DIR/.env"
    echo "  Затем запустите:               systemctl restart $SERVICE"
    echo
else
    chmod 600 "$APP_DIR/.env"
fi

log "Регистрируем systemd-сервис"
install -m 644 "$APP_DIR/deploy/${SERVICE}.service" "/etc/systemd/system/${SERVICE}.service"
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null
systemctl restart "$SERVICE"

sleep 3
log "Статус"
systemctl --no-pager --lines=15 status "$SERVICE" || true
echo
echo "Логи в реальном времени:  journalctl -u $SERVICE -f"
