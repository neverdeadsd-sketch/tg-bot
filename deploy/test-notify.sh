#!/usr/bin/env bash
#
# Проверка канала уведомлений: доходит ли сообщение в Telegram.
#
#   sudo bash /opt/hollvpn/deploy/test-notify.sh
#
set -euo pipefail

ENV_FILE="${ENV_FILE:-/opt/hollvpn/checkout/.env}"
[ -f "$ENV_FILE" ] || { echo "Не найден $ENV_FILE" >&2; exit 1; }

get() { grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2- || true; }
TOKEN="$(get TELEGRAM_BOT_TOKEN)"
CHAT="$(get TELEGRAM_ADMIN_CHAT_ID)"

if [ -z "$TOKEN" ] || [ -z "$CHAT" ]; then
  echo "Уведомления не настроены: задайте TELEGRAM_BOT_TOKEN и TELEGRAM_ADMIN_CHAT_ID"
  echo "  sudo bash /opt/hollvpn/deploy/set-env.sh"
  exit 1
fi

CODE="$(curl -s -o /tmp/tg-check.json -w '%{http_code}' --max-time 15 \
  -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  -H 'Content-Type: application/json' \
  -d "{\"chat_id\":\"${CHAT}\",\"text\":\"🔔 HollVPN: проверка связи. Уведомления об оплатах дойдут.\"}")"

if [ "$CODE" = "200" ]; then
  echo "Отправлено. Проверьте Telegram."
else
  echo "Telegram ответил $CODE:"
  head -c 300 /tmp/tg-check.json; echo
  echo
  echo "401 — неверный токен (проверьте у @BotFather)"
  echo "400 — неверный chat id, или вы не нажали «Старт» в своём боте"
fi
rm -f /tmp/tg-check.json
