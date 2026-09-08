#!/usr/bin/env bash
#
# Выпуск сертификата, когда DNS готов.
#
#   sudo bash /opt/hollvpn/deploy/enable-https.sh
#
# Сначала проверяет, что домен действительно указывает на этот сервер:
# certbot в этом случае падает с невнятной ошибкой, а причина всегда одна.
#
set -euo pipefail

DOMAIN="${DOMAIN:-hollvpn.online}"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[0;32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[0;33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[0;31mОстановлено:\033[0m %s\n\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Запускайте через sudo"

bold "Проверяю DNS для $DOMAIN"

SERVER_IP="$(curl -fsS4 --max-time 10 https://api.ipify.org 2>/dev/null || echo '')"
[ -n "$SERVER_IP" ] || warn "не удалось определить внешний IP сервера"
[ -n "$SERVER_IP" ] && ok "IP этого сервера: $SERVER_IP"

resolve() { getent ahostsv4 "$1" 2>/dev/null | awk 'NR==1{print $1}'; }

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
if [ -n "$WWW" ]; then ok "www.$DOMAIN → $WWW"; else warn "www.$DOMAIN не резолвится — сертификат будет только на основной домен"; fi

if [ -n "$SERVER_IP" ] && [ "$APEX" != "$SERVER_IP" ]; then
  die "Домен указывает на $APEX, а это сервер $SERVER_IP.
  Либо A-запись ведёт не сюда, либо изменения ещё не разошлись.
  Подождите и запустите снова."
fi

printf '\n'
bold "Выпускаю сертификат"
dpkg -s certbot >/dev/null 2>&1 || { apt-get update -qq; apt-get install -y -qq certbot python3-certbot-nginx; }

if certbot certificates 2>/dev/null | grep -q "Domains:.*\b$DOMAIN\b"; then
  ok "сертификат уже есть, обновляю конфигурацию"
  certbot --nginx -d "$DOMAIN" ${WWW:+-d "www.$DOMAIN"} --non-interactive --agree-tos \
    --register-unsafely-without-email --redirect --keep-until-expiring
else
  certbot --nginx -d "$DOMAIN" ${WWW:+-d "www.$DOMAIN"} --non-interactive --agree-tos \
    --register-unsafely-without-email --redirect
fi

systemctl reload nginx
printf '\n'
ok "готово"
printf '\n\033[1;32mПроверьте: https://%s\033[0m\n' "$DOMAIN"
printf 'И снаружи:  curl -i https://%s/api/payment/test   (ждём 404)\n\n' "$DOMAIN"
