#!/usr/bin/env bash
#
# Выпуск сертификата Let's Encrypt и перевод сайта на HTTPS.
#
#   sudo bash /opt/hollvpn/deploy/enable-https.sh
#
# Сначала проверяет, что домен указывает на этот сервер и что файл-проверка
# отдаётся по HTTP: certbot в этих случаях падает с невнятной ошибкой,
# а причина всегда одна из двух.
#
# certbot здесь работает в режиме webroot и с флагом certonly: он только
# кладёт файл-проверку в корень сайта и забирает сертификат. Конфигурацию
# nginx он не правит и nginx не перезапускает — конфигурацию пишем сами
# и применяем через reload. Reload не переоткрывает слушающий сокет, поэтому
# «bind() to 0.0.0.0:80 failed (98: Address already in use)» тут невозможен,
# а бот за тем же nginx перезапуска не замечает.
#
set -euo pipefail

DOMAIN="${DOMAIN:-hollvpn.ru}"
SITE_DIR="${SITE_DIR:-/var/www/hollvpn}"
PORT="${PORT:-8080}"
NGINX_CONF="${NGINX_CONF:-/etc/nginx/sites-available/hollvpn}"

bold() { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
ok()   { printf '    \033[0;32m✓\033[0m %s\n' "$*"; }
warn() { printf '    \033[0;33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[0;31mОстановлено:\033[0m %s\n\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Запускайте через sudo"
[ -d "$SITE_DIR" ] || die "Каталога $SITE_DIR нет — сайт ещё не установлен.
  Сначала:  sudo DOMAIN=$DOMAIN bash /opt/hollvpn/deploy/install.sh"

# --------------------------------------------------------------------- DNS --

bold "Проверяю DNS для $DOMAIN"

SERVER_IP="$(curl -fsS4 --max-time 10 https://api.ipify.org 2>/dev/null || echo '')"
if [ -n "$SERVER_IP" ]; then
  ok "IP этого сервера: $SERVER_IP"
else
  warn "не удалось определить внешний IP сервера"
fi

# getent возвращает 2, когда имя не резолвится, и под `set -e` это убивало
# скрипт молча — ровно в том случае, ради которого он и написан.
resolve() {
  local out
  out="$(getent ahostsv4 "$1" 2>/dev/null || true)"
  printf '%s' "$out" | awk 'NR==1{print $1}'
}

APEX="$(resolve "$DOMAIN")"
WWW="$(resolve "www.$DOMAIN")"

if [ -z "$APEX" ]; then
  cat <<MSG

  Домен $DOMAIN не резолвится — A-записи ещё нет.

  В панели регистратора домена заведите:
      A    @      ${SERVER_IP:-IP-этого-сервера}
      A    www    ${SERVER_IP:-IP-этого-сервера}

  Затем подождите (обычно минуты) и запустите этот скрипт снова.
  Проверить, разошлось ли: getent ahostsv4 $DOMAIN

MSG
  exit 1
fi

ok "$DOMAIN → $APEX"
if [ -n "$WWW" ]; then
  ok "www.$DOMAIN → $WWW"
else
  warn "www.$DOMAIN не резолвится — сертификат будет только на основной домен"
fi

if [ -n "$SERVER_IP" ] && [ "$APEX" != "$SERVER_IP" ]; then
  die "Домен указывает на $APEX, а это сервер $SERVER_IP.
  Либо A-запись ведёт не сюда, либо изменения ещё не разошлись.
  Подождите и запустите снова."
fi

# ------------------------------------------------------------------ nginx ---

bold "Проверяю, что nginx отдаёт домен"

if ! systemctl is-active --quiet nginx; then
  die "nginx не запущен. Сначала поднимите его:
      systemctl start nginx
      systemctl status nginx --no-pager
  Если не стартует из-за занятого порта — посмотрите, кто его держит:
      ss -lntp | grep ':80 '"
fi

PORT80=""
if command -v ss >/dev/null 2>&1; then
  PORT80="$(ss -lntpH 2>/dev/null | awk '$4 ~ /:80$/ {print $NF}' | head -1)"
fi
ok "nginx работает${PORT80:+, 80-й порт за ${PORT80}}"

# Если файл из корня сайта не отдаётся по HTTP, то и certbot проверку
# не пройдёт. Лучше узнать это здесь, чем из его лога.
ACME_DIR="$SITE_DIR/.well-known/acme-challenge"
PROBE_REL=".well-known/acme-challenge/hollvpn-probe"
mkdir -p "$ACME_DIR"
trap 'rm -f "$SITE_DIR/$PROBE_REL"' EXIT
printf 'ok\n' > "$SITE_DIR/$PROBE_REL"
PROBE_CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "http://$DOMAIN/$PROBE_REL" || echo 000)"
rm -f "$SITE_DIR/$PROBE_REL"
trap - EXIT

if [ "$PROBE_CODE" != "200" ]; then
  die "Проверочный файл не отдаётся по http://$DOMAIN/ (ответ $PROBE_CODE).
  Let's Encrypt должен его получить, иначе сертификат не выпустить.
  Обычные причины:
    - 80-й порт закрыт файрволом снаружи
    - домен ведёт на другой сервер
    - на 80-м отвечает не наш nginx${PORT80:+ (сейчас там $PORT80)}
  Проверьте:  curl -I http://$DOMAIN/   и   ss -lntp | grep ':80 '"
fi
ok "проверочный файл отдаётся, домен подтверждается"

# ------------------------------------------------------------ сертификат ---

bold "Выпускаю сертификат"

dpkg -s certbot >/dev/null 2>&1 || { apt-get update -qq; apt-get install -y -qq certbot; }

CERT_ARGS=(-d "$DOMAIN")
if [ -n "$WWW" ]; then CERT_ARGS+=(-d "www.$DOMAIN"); fi

# --cert-name фиксирует имя набора: без него повторный запуск с другим
# списком доменов заводит вторую копию вида hollvpn.ru-0001, и пути в
# конфигурации перестают совпадать с реальностью.
certbot certonly --webroot -w "$SITE_DIR" "${CERT_ARGS[@]}" \
  --cert-name "$DOMAIN" \
  --non-interactive --agree-tos --register-unsafely-without-email \
  --keep-until-expiring \
  --deploy-hook 'systemctl reload nginx'

LIVE="/etc/letsencrypt/live/$DOMAIN"
[ -f "$LIVE/fullchain.pem" ] || die "certbot отработал, но $LIVE/fullchain.pem не появился.
  Смотрите: certbot certificates"
ok "сертификат в $LIVE"

# Домены, которые сертификат реально покрывает: только их можно называть
# в server_name у HTTPS-блока, иначе браузер получит чужое имя в сертификате.
TLS_NAMES="$DOMAIN"
if [ -n "$WWW" ]; then TLS_NAMES="$DOMAIN www.$DOMAIN"; fi

# Отдельная директива `http2 on` появилась только в nginx 1.25.1, а до неё
# http2 задавался параметром listen. Написать не ту форму — значит получить
# отказ на `nginx -t` и остаться без HTTPS, поэтому выбираем по версии.
# Если версию разобрать не удалось, берём старую форму: она работает везде,
# в новых версиях лишь помечена устаревшей.
ver_ge() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" = "$2" ]; }
NGINX_VER="$(nginx -v 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"

# На сервере без IPv6 nginx не проходит даже проверку конфигурации:
# "socket() [::]:443 failed (97: Address family not supported by protocol)".
# Поэтому IPv6-строки добавляем только там, где IPv6 действительно поднят.
if [ -s /proc/net/if_inet6 ]; then HAS_IPV6=1; else HAS_IPV6=0; fi

LISTEN_80="listen 80;"
if [ "$HAS_IPV6" = 1 ]; then
  LISTEN_80="$LISTEN_80
    listen [::]:80;"
fi

if [ -n "$NGINX_VER" ] && ver_ge "$NGINX_VER" 1.25.1; then
  LISTEN_443="listen 443 ssl;"
  if [ "$HAS_IPV6" = 1 ]; then
    LISTEN_443="$LISTEN_443
    listen [::]:443 ssl;"
  fi
  LISTEN_443="$LISTEN_443
    http2 on;"
else
  LISTEN_443="listen 443 ssl http2;"
  if [ "$HAS_IPV6" = 1 ]; then
    LISTEN_443="$LISTEN_443
    listen [::]:443 ssl http2;"
  fi
fi

# ------------------------------------------------------------ конфигурация --

bold "Перевожу nginx на HTTPS"

HEADERS="/etc/nginx/snippets/hollvpn-headers.conf"
mkdir -p /etc/nginx/snippets
cat > "$HEADERS" <<'HEADERS_EOF'
# add_header в location отменяет унаследованные от server, поэтому набор
# вынесен в файл и подключается в каждом location, где есть свои заголовки.
add_header Strict-Transport-Security "max-age=31536000" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "SAMEORIGIN" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
HEADERS_EOF

if [ -f "$NGINX_CONF" ]; then
  BACKUP="$NGINX_CONF.bak.$(date +%s)"
  cp "$NGINX_CONF" "$BACKUP"
  ok "прежний конфиг сохранён: $BACKUP"
else
  BACKUP=""
fi

cat > "$NGINX_CONF" <<NGINX
server {
    $LISTEN_80
    server_name $DOMAIN www.$DOMAIN;

    # Проверка Let's Encrypt отдаётся по HTTP напрямую: так продление
    # не зависит от того, как настроен редирект.
    location ^~ /.well-known/acme-challenge/ {
        root $SITE_DIR;
        default_type "text/plain";
        try_files \$uri =404;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    $LISTEN_443
    server_name $TLS_NAMES;

    ssl_certificate     $LIVE/fullchain.pem;
    ssl_certificate_key $LIVE/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    root $SITE_DIR;
    index index.html;

    include snippets/hollvpn-headers.conf;

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
        include snippets/hollvpn-headers.conf;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
    location ~* \.html\$ {
        include snippets/hollvpn-headers.conf;
        add_header Cache-Control "no-cache";
    }

    gzip on;
    gzip_types text/css application/javascript image/svg+xml application/xml text/plain;
    gzip_min_length 512;
}
NGINX

ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/hollvpn

if ! nginx -t >/dev/null 2>&1; then
  NGINX_ERR="$(nginx -t 2>&1 || true)"
  if [ -n "$BACKUP" ]; then
    cp "$BACKUP" "$NGINX_CONF"
    warn "конфигурация не принята, вернул прежнюю"
  else
    rm -f /etc/nginx/sites-enabled/hollvpn "$NGINX_CONF"
    warn "конфигурация не принята, убрал её"
  fi
  die "nginx не принял конфигурацию, ничего не изменилось:
$NGINX_ERR"
fi

# reload, а не restart: слушающие сокеты остаются открытыми, старые
# соединения дорабатывают, бот за тем же nginx ничего не замечает.
systemctl reload nginx
ok "конфигурация применена (reload, без перезапуска)"

# ------------------------------------------------------------------ итог ---

bold "Проверяю снаружи"

HTTPS_CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "https://$DOMAIN/" || echo 000)"
if [ "$HTTPS_CODE" = "200" ]; then
  ok "https://$DOMAIN/ отвечает 200"
else
  warn "https://$DOMAIN/ ответил $HTTPS_CODE — проверьте вручную"
fi

API_CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "https://$DOMAIN/api/payment/test" || echo 000)"
if [ "$API_CODE" = "404" ]; then
  ok "https://$DOMAIN/api/ доходит до чекаута (404 на несуществующий заказ — как и должно)"
else
  warn "https://$DOMAIN/api/payment/test ответил $API_CODE, ожидался 404"
fi

printf '\n\033[1;32mГотово.\033[0m Сайт на https://%s\n\n' "$DOMAIN"
cat <<MSG
Осталось сделать руками:

  1. В личном кабинете ЮKassa указать адрес для уведомлений:
         https://$DOMAIN/api/yookassa/webhook

  2. Проверить, что PUBLIC_URL в /opt/hollvpn/checkout/.env начинается с https://
         grep PUBLIC_URL /opt/hollvpn/checkout/.env
     Если нет — поправьте и перезапустите:
         systemctl restart hollvpn-checkout

Продление сертификата уже настроено: таймер certbot обновит его сам
и перезагрузит nginx. Проверить, что продление пройдёт:
    certbot renew --dry-run

MSG
