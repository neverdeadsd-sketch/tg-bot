#!/usr/bin/env bash
#
# Установка сайта HollVPN и сервиса оплаты на сервер.
#
# Скрипт идемпотентный: его можно запускать повторно, он не перезаписывает
# .env и не трогает чужие конфигурации nginx. На сервере, где уже работает
# бот, ничего из этого его не заденет.
#
#   sudo bash deploy/install.sh
#
set -euo pipefail

DOMAIN="${DOMAIN:-hollvpn.ru}"
APP_DIR="${APP_DIR:-/opt/hollvpn}"
SITE_DIR="${SITE_DIR:-/var/www/hollvpn}"
SERVICE_USER="${SERVICE_USER:-hollvpn}"
PORT="${PORT:-8080}"
REPO="${REPO:-https://github.com/neverdeadsd-sketch/tg-bot.git}"
BRANCH="${BRANCH:-claude/hollvpn-website-3d-k9507m}"

say()  { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
ok()   { printf '    \033[0;32m✓\033[0m %s\n' "$*"; }
warn() { printf '    \033[0;33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[0;31mОстановлено:\033[0m %s\n\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- проверки --

[ "$(id -u)" -eq 0 ] || die "Запускайте через sudo: sudo bash deploy/install.sh"

# Дальше есть rm -rf по этим путям. Убеждаемся, что они не указывают
# на системный каталог: опечатка в APP_DIR не должна стоить сервера.
for path_var in APP_DIR SITE_DIR; do
  path_value="${!path_var}"
  case "$path_value" in
    /|/usr|/usr/*|/etc|/etc/*|/var|/home|/root|/boot|/bin|/sbin|/lib*|"")
      die "$path_var=$path_value — это системный путь, отказываюсь" ;;
  esac
  case "$path_value" in
    /*) ;;
    *) die "$path_var должен быть абсолютным путём, а не «$path_value»" ;;
  esac
done

command -v apt-get >/dev/null 2>&1 || die \
  "Скрипт рассчитан на Debian и Ubuntu. Определите систему командой
  cat /etc/os-release — и пришлите вывод, подготовлю вариант под неё."

say "Проверяю, что порт $PORT свободен"
PORT_BUSY=0
if command -v ss >/dev/null 2>&1; then
  ss -lnt 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$PORT\$" && PORT_BUSY=1
elif command -v netstat >/dev/null 2>&1; then
  netstat -lnt 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$PORT\$" && PORT_BUSY=1
fi
if [ "$PORT_BUSY" -eq 1 ]; then
  # При повторной установке порт держит наша же служба — это не конфликт.
  if systemctl is-active --quiet hollvpn-checkout 2>/dev/null; then
    ok "порт $PORT занят нашей службой — это переустановка, продолжаю"
  else
    die "Порт $PORT занят кем-то ещё — вероятно, ботом или панелью.
  Посмотреть кем:  ss -lntp | grep :$PORT
  Или взять другой: sudo PORT=8090 bash deploy/install.sh"
  fi
else
  ok "порт $PORT свободен"
fi

say "Проверяю, что домен $DOMAIN указывает на этот сервер"
SERVER_IP="$(curl -fsS --max-time 10 https://api.ipify.org 2>/dev/null || echo '')"
DOMAIN_IP="$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk 'NR==1{print $1}' || true)"
if [ -z "$DOMAIN_IP" ]; then
  warn "домен $DOMAIN не резолвится — сертификат получить не выйдет"
  warn "заведите A-запись на IP этого сервера и запустите скрипт снова"
elif [ -n "$SERVER_IP" ] && [ "$DOMAIN_IP" != "$SERVER_IP" ]; then
  warn "домен указывает на $DOMAIN_IP, а сервер — $SERVER_IP"
  warn "если DNS только что меняли, подождите и запустите снова"
else
  ok "домен указывает сюда ($DOMAIN_IP)"
fi

# --------------------------------------------------------------- пакеты ----

say "Ставлю недостающие пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq

for pkg in git curl nginx ca-certificates; do
  dpkg -s "$pkg" >/dev/null 2>&1 || apt-get install -y -qq "$pkg"
done
ok "git, curl, nginx на месте"

# node:sqlite появился в Node 22.5 — на более старом сервис не поднимется
NODE_OK=0
if command -v node >/dev/null 2>&1; then
  NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
  NODE_MINOR="$(node -p 'process.versions.node.split(".")[1]')"
  if [ "$NODE_MAJOR" -gt 22 ] || { [ "$NODE_MAJOR" -eq 22 ] && [ "$NODE_MINOR" -ge 5 ]; }; then
    NODE_OK=1
    ok "Node $(node -v) подходит"
  else
    warn "Node $(node -v) слишком старый, нужен 22.5+"
  fi
fi
if [ "$NODE_OK" -eq 0 ]; then
  say "Ставлю Node 22"
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null
  apt-get install -y -qq nodejs
  ok "поставлен Node $(node -v)"
fi

# ----------------------------------------------------------------- код -----

say "Загружаю код"
id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"

if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
  git -C "$APP_DIR" checkout --quiet "$BRANCH"
  git -C "$APP_DIR" reset --hard --quiet "origin/$BRANCH"
  ok "репозиторий обновлён"
else
  # Каталог есть, но это не наш репозиторий — там могут быть чужие данные.
  if [ -d "$APP_DIR" ] && [ -n "$(ls -A "$APP_DIR" 2>/dev/null)" ]; then
    die "$APP_DIR не пуст и не является нашей установкой.
  Уберите каталог или укажите другой:  sudo APP_DIR=/opt/hollvpn2 bash deploy/install.sh"
  fi
  rm -rf "${APP_DIR:?}.tmp"
  mkdir -p "$(dirname "$APP_DIR")"
  git clone --quiet --branch "$BRANCH" "$REPO" "$APP_DIR.tmp"
  rmdir "$APP_DIR" 2>/dev/null || true
  mv "$APP_DIR.tmp" "$APP_DIR"
  ok "репозиторий склонирован в $APP_DIR"
fi

say "Раскладываю сайт"
mkdir -p "$SITE_DIR"
cp -r "$APP_DIR/site/." "$SITE_DIR/"
chown -R www-data:www-data "$SITE_DIR"
ok "статика в $SITE_DIR"

# ------------------------------------------------------------------ .env ---

ENV_FILE="$APP_DIR/checkout/.env"
if [ -f "$ENV_FILE" ]; then
  ok ".env уже есть — секреты не трогаю"

  # PUBLIC_URL выводится из домена, а не вводится руками: при смене домена
  # он должен поехать следом, иначе адрес возврата после оплаты и правило
  # CORS останутся указывать на старый сайт.
  CURRENT_PUBLIC="$(grep -E "^PUBLIC_URL=" "$ENV_FILE" | head -1 | cut -d= -f2- || true)"
  if [ "$CURRENT_PUBLIC" != "https://$DOMAIN" ]; then
    tmp="$(mktemp)"
    NEWURL="https://$DOMAIN" awk '
      BEGIN { v = ENVIRON["NEWURL"]; done = 0 }
      index($0, "PUBLIC_URL=") == 1 { print "PUBLIC_URL=" v; done = 1; next }
      { print }
      END { if (!done) print "PUBLIC_URL=" v }
    ' "$ENV_FILE" > "$tmp"
    mv "$tmp" "$ENV_FILE"
    warn "домен сменился: PUBLIC_URL обновлён на https://$DOMAIN"
    warn "не забудьте поменять адрес вебхука в кабинете ЮKassa:"
    warn "  https://$DOMAIN/api/yookassa/webhook"
    RESTART_NEEDED=1
  fi
else
  say "Создаю .env из шаблона"
  cp "$APP_DIR/checkout/.env.example" "$ENV_FILE"
  # Значения, которые скрипт знает сам.
  sed -i "s|^PUBLIC_URL=.*|PUBLIC_URL=https://$DOMAIN|" "$ENV_FILE"
  sed -i "s|^PORT=.*|PORT=$PORT|" "$ENV_FILE"
  sed -i "s|^TRUST_PROXY=.*|TRUST_PROXY=true|" "$ENV_FILE"
  sed -i "s|^DB_PATH=.*|DB_PATH=$APP_DIR/checkout/orders.db|" "$ENV_FILE"
  ok "создан $ENV_FILE"
fi
chown "$SERVICE_USER:$SERVICE_USER" "$ENV_FILE"
chmod 600 "$ENV_FILE"
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/checkout"

# --------------------------------------------------------------- systemd ---

say "Настраиваю службу"
cat > /etc/systemd/system/hollvpn-checkout.service <<UNIT
[Unit]
Description=HollVPN checkout
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$APP_DIR/checkout
EnvironmentFile=$APP_DIR/checkout/.env
ExecStart=/usr/bin/node src/index.js
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=$APP_DIR/checkout
ProtectHome=true

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
ok "служба hollvpn-checkout описана"

# ----------------------------------------------------------------- nginx ---

NGINX_CONF="/etc/nginx/sites-available/hollvpn"
say "Настраиваю nginx"
if [ -f "$NGINX_CONF" ]; then
  cp "$NGINX_CONF" "$NGINX_CONF.bak.$(date +%s)"
  warn "прежний конфиг сохранён рядом с суффиксом .bak"
fi

cat > "$NGINX_CONF" <<NGINX
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN www.$DOMAIN;

    root $SITE_DIR;
    index index.html;

    # Статика отдаётся напрямую, /api уходит в чекаут.
    location / {
        try_files \$uri \$uri/ =404;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_set_header Host \$host;
        # Без X-Real-IP чекаут увидит адрес nginx и отклонит вебхуки ЮKassa.
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 30s;
    }

    location ~* \.(css|js|svg|woff2)\$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
    location ~* \.html\$ {
        add_header Cache-Control "no-cache";
    }

    gzip on;
    gzip_types text/css application/javascript image/svg+xml application/xml text/plain;
    gzip_min_length 512;
}
NGINX

ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/hollvpn
nginx -t >/dev/null 2>&1 || die "nginx не принял конфигурацию — смотрите: nginx -t"
systemctl reload nginx
ok "nginx настроен на $DOMAIN"

# ------------------------------------------------------------ сертификат ---

if [ -n "$DOMAIN_IP" ] && [ "${DOMAIN_IP}" = "${SERVER_IP:-$DOMAIN_IP}" ]; then
  say "Получаю сертификат Let's Encrypt"
  dpkg -s certbot >/dev/null 2>&1 || apt-get install -y -qq certbot python3-certbot-nginx
  if certbot certificates 2>/dev/null | grep -q "$DOMAIN"; then
    ok "сертификат для $DOMAIN уже есть"
  else
    certbot --nginx -d "$DOMAIN" -d "www.$DOMAIN" --non-interactive --agree-tos \
      --register-unsafely-without-email --redirect || \
      warn "certbot не справился — запустите вручную: certbot --nginx -d $DOMAIN"
  fi
else
  warn "сертификат пропущен: домен пока не указывает на этот сервер"
  warn "после настройки DNS выполните: certbot --nginx -d $DOMAIN -d www.$DOMAIN"
fi

# ----------------------------------------------------------------- итог ----

say "Проверяю, готов ли чекаут к запуску"
MISSING=""

# Ключ должен быть непустым.
if ! grep -qE '^YOOKASSA_SECRET_KEY=.+' "$ENV_FILE"; then
  MISSING="$MISSING YOOKASSA_SECRET_KEY"
fi

# Выдача: годится либо эндпоинт бота, либо уведомления в Telegram.
FULFIL_LINE="$(grep -E '^FULFILMENT_URL=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
TG_TOKEN="$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
TG_CHAT="$(grep -E '^TELEGRAM_ADMIN_CHAT_ID=' "$ENV_FILE" | head -1 | cut -d= -f2-)"

HAS_FULFIL=0
case "$FULFIL_LINE" in
  http://*|https://*) HAS_FULFIL=1 ;;
esac
HAS_TELEGRAM=0
if [ -n "$TG_TOKEN" ] && [ -n "$TG_CHAT" ]; then HAS_TELEGRAM=1; fi

if [ "$HAS_FULFIL" -eq 0 ] && [ "$HAS_TELEGRAM" -eq 0 ]; then
  MISSING="$MISSING способ-выдачи"
fi

if [ -n "$MISSING" ]; then
  systemctl enable hollvpn-checkout >/dev/null 2>&1 || true
  printf '\n\033[1;33mСайт уже открывается: https://%s\033[0m\n' "$DOMAIN"
  printf '\nОплата пока не включена — в %s не заполнено:%s\n' "$ENV_FILE" "$MISSING"
  cat <<NEXT

  1. Откройте файл:      nano $ENV_FILE
  2. Впишите значения:
       YOOKASSA_SECRET_KEY — кабинет ЮKassa → Интеграция → Ключи API

     И хотя бы одно из двух — как сообщать об оплате:
       FULFILMENT_URL         — бот выдаёт подписку сам
       TELEGRAM_BOT_TOKEN
       TELEGRAM_ADMIN_CHAT_ID — уведомление вам, выдаёте вручную
                                (токен у @BotFather, id у @userinfobot)
  3. Запустите службу:   systemctl start hollvpn-checkout
  4. Проверьте:          systemctl status hollvpn-checkout
                         curl localhost:$PORT/health

  Служба намеренно не стартует, пока не настроен ни один способ сообщить
  об оплате: иначе она принимала бы деньги, не говоря об этом никому.

NEXT
else
  if [ "${RESTART_NEEDED:-0}" = "1" ]; then
    ok "перезапускаю службу под новый домен"
  fi
  systemctl enable --now hollvpn-checkout >/dev/null 2>&1
  systemctl restart hollvpn-checkout >/dev/null 2>&1 || true
  sleep 2
  if systemctl is-active --quiet hollvpn-checkout; then
    ok "служба запущена"
    printf '\n\033[1;32mГотово: https://%s\033[0m\n\n' "$DOMAIN"
  else
    warn "служба не поднялась — смотрите: journalctl -u hollvpn-checkout -n 30"
  fi
fi
