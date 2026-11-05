#!/usr/bin/env bash
#
# Установка и обновление memebot на сервере (Ubuntu/Debian), без Docker.
# Ставит Python-окружение в /opt/memebot, спрашивает токен и ID, запускает как службу systemd.
# Повторный запуск обновляет код и не трогает .env и базу.
#
#   curl -fsSL https://raw.githubusercontent.com/neverdeadsd-sketch/tg-bot/claude/memebot/deploy.sh | bash
#
# Docker намеренно не используется: при установке он меняет правила iptables,
# а на сервере с VPN это может задеть его трафик. Бот сеть не настраивает и порты не открывает.
#
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/memebot}"
REPO="${REPO:-https://github.com/neverdeadsd-sketch/tg-bot.git}"
BRANCH="${BRANCH:-claude/memebot}"
SERVICE="memebot"
SERVICE_USER="memebot"

say()  { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
ok()   { printf '    \033[0;32m✓\033[0m %s\n' "$*"; }
warn() { printf '    \033[0;33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[0;31mОстановлено:\033[0m %s\n\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Запусти от root или через sudo."
command -v apt-get >/dev/null 2>&1 || die "Скрипт рассчитан на Ubuntu и Debian."
command -v systemctl >/dev/null 2>&1 || die "Нужен systemd."

case "$APP_DIR" in
  /opt/?*|/srv/?*) ;;
  *) die "APP_DIR=$APP_DIR — ожидался каталог внутри /opt или /srv" ;;
esac

APT_UPDATED=0
apt_install() {
  # Сломанный сторонний репозиторий (например, haproxy) не должен мешать установке:
  # apt всё равно обновит остальные списки пакетов.
  if [ "$APT_UPDATED" -eq 0 ]; then
    apt-get update -qq >/dev/null 2>&1 || warn "apt-get update завершился с ошибкой в каком-то стороннем репозитории — продолжаю"
    APT_UPDATED=1
  fi
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@" >/dev/null 2>&1
}

# ------------------------------------------------------------------ Python --
say "Python"
command -v python3 >/dev/null 2>&1 || apt_install python3 || die "не удалось установить python3"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || die "нужен Python 3.10 или новее, на сервере $(python3 --version 2>&1)"
PYVER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if ! python3 -c 'import ensurepip, venv' >/dev/null 2>&1; then
  apt_install "python${PYVER}-venv" || apt_install python3-venv \
    || die "не удалось установить python3-venv. Пришли вывод команды: apt-get install -y python3-venv"
fi
command -v git >/dev/null 2>&1 || apt_install git || die "не удалось установить git"
ok "Python $PYVER, venv и git на месте"

# -------------------------------------------------------------------- код --
say "Код бота → $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
  git -C "$APP_DIR" reset --quiet --hard "origin/$BRANCH"   # .env и data/ не в git — не затрагиваются
  ok "обновлён до $(git -C "$APP_DIR" log -1 --format=%h)"
else
  git clone --quiet --branch "$BRANCH" --single-branch "$REPO" "$APP_DIR"
  ok "скачан"
fi
cd "$APP_DIR"

say "Зависимости"
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/pip install --quiet --disable-pip-version-check --upgrade pip
.venv/bin/pip install --quiet --disable-pip-version-check -r requirements.txt
ok "установлены"

# ---------------------------------------------------------------- настройки --
say "Настройки (.env)"
if [ -f .env ]; then
  ok "уже есть — не трогаю (править: nano $APP_DIR/.env)"
else
  [ -r /dev/tty ] || die "Нет терминала для вопросов. Создай $APP_DIR/.env из .env.example вручную и запусти скрипт снова."
  cp .env.example .env

  while :; do
    # Токен не показываем на экране, чтобы он не попал на скриншот.
    read -rsp "    Токен бота от @BotFather (ввод скрыт): " TOKEN < /dev/tty; echo
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

# --------------------------------------------------- пользователь и служба --
say "Служба $SERVICE"
id "$SERVICE_USER" >/dev/null 2>&1 \
  || useradd --system --home-dir "$APP_DIR" --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
mkdir -p data
chown -R "$SERVICE_USER:$SERVICE_USER" data
chown "root:$SERVICE_USER" .env
chmod 640 .env

cat > "/etc/systemd/system/$SERVICE.service" <<EOF
[Unit]
Description=memebot — торговля мемкоинами на Solana
After=network-online.target
Wants=network-online.target

[Service]
User=$SERVICE_USER
WorkingDirectory=$APP_DIR
# Настройки бот читает сам из $APP_DIR/.env
Environment=PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
ExecStart=$APP_DIR/.venv/bin/python -m memebot
Restart=on-failure
RestartSec=15
# Код 2 — ошибка настроек: перезапускать бессмысленно, нужно править .env.
RestartPreventExitStatus=2
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$APP_DIR/data
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --quiet "$SERVICE"
systemctl restart "$SERVICE"
ok "служба установлена и запущена"

# ---------------------------------------------------------------- проверка --
say "Проверка"
sleep 10
journalctl -u "$SERVICE" -n 15 --no-pager -o cat || true
if systemctl is-active --quiet "$SERVICE"; then
  ok "бот работает"
  cat <<EOF

  Дальше:
    1. Открой своего бота в Telegram и нажми Start.
    2. Отправь /status, потом /scan — увидишь, что бот находит на рынке.

  Логи:        journalctl -u $SERVICE -f
  Настройки:   nano $APP_DIR/.env   затем   systemctl restart $SERVICE
  Обновить:    запусти эту же команду установки ещё раз
  Остановить:  systemctl stop $SERVICE

EOF
else
  die "бот не запустился. Пришли строки лога выше (или вывод: journalctl -u $SERVICE -n 40 --no-pager)."
fi
