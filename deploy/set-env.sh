#!/usr/bin/env bash
#
# Заполнение .env вопросами, без редактора.
#
#   sudo bash /opt/hollvpn/deploy/set-env.sh
#
# Секреты вводятся скрыто и не попадают в историю оболочки — в отличие от
# варианта, где их передают аргументом команды.
#
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/hollvpn}"
ENV_FILE="$APP_DIR/checkout/.env"
SERVICE_USER="${SERVICE_USER:-hollvpn}"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[0;32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[0;33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[0;31mОстановлено:\033[0m %s\n\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Запускайте через sudo"
[ -f "$ENV_FILE" ] || die "$ENV_FILE не найден. Сначала: sudo bash $APP_DIR/deploy/install.sh"

current() { grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2- || true; }

# Замена строки без sed: значение приходит от пользователя и может содержать
# что угодно, включая символы, которые sed истолкует по-своему.
set_value() {
  local key="$1" value="$2" tmp
  tmp="$(mktemp)"
  KEY="$key" VALUE="$value" awk '
    BEGIN { key = ENVIRON["KEY"]; value = ENVIRON["VALUE"]; done = 0 }
    index($0, key "=") == 1 { print key "=" value; done = 1; next }
    { print }
    END { if (!done) print key "=" value }
  ' "$ENV_FILE" > "$tmp"
  mv "$tmp" "$ENV_FILE"
}

mask() {
  local v="$1"
  if [ ${#v} -le 8 ]; then printf '%s' '••••'; else printf '%s…%s' "${v:0:4}" "${v: -4}"; fi
}

ask() {
  local key="$1" prompt="$2" secret="$3" hint="$4" now value
  now="$(current "$key")"

  printf '\n'
  bold "$prompt"
  if [ -n "$hint" ]; then
    printf '%s\n' "$hint" | while IFS= read -r line; do
      printf '  %s\n' "$(printf '%s' "$line" | sed 's/^[[:space:]]*//')"
    done
  fi
  if [ -n "$now" ]; then
    printf '  сейчас: %s\n' "$(mask "$now")"
    printf '  Enter — оставить как есть\n'
  fi

  if [ "$secret" = "yes" ]; then
    printf '  Введите значение (не отображается): '
    read -rs value; printf '\n'
  else
    printf '  Введите значение: '
    read -r value
  fi

  if [ -z "$value" ]; then
    if [ -n "$now" ]; then ok "оставлено без изменений"; else warn "пропущено"; fi
    return
  fi
  set_value "$key" "$value"
  ok "записано: $(mask "$value")"
}

bold "Настройка оплаты HollVPN"
printf 'Файл: %s\n' "$ENV_FILE"

ask YOOKASSA_SECRET_KEY \
  "Секретный ключ ЮKassa" yes \
  "Кабинет ЮKassa → Интеграция → Ключи API. Начинается с live_ или test_."

printf '\n'
bold "Как сообщать об оплате — нужен хотя бы один способ"
printf 'Можно настроить оба: тогда бот выдаёт сам, а Telegram остаётся тревогой.\n'

ask TELEGRAM_BOT_TOKEN \
  "Токен бота для уведомлений" yes \
  "У @BotFather. Вид: 123456789:AAH... Пусто — уведомлений не будет."

ask TELEGRAM_ADMIN_CHAT_ID \
  "Ваш числовой id в Telegram" no \
  "Напишите @userinfobot — он ответит числом вида 123456789."

ask FULFILMENT_URL \
  "Адрес в боте для автовыдачи — если не знаете, жмите Enter" no \
  "Нужен, только если бот умеет принимать HTTP-запрос и сам выдавать подписку.
  Тогда чекаут скажет ему «оплачено, выдай такому-то», и вы не участвуете.
  Нет такого — пропустите: будете получать уведомление в Telegram и выдавать
  вручную. Добавить можно потом, запустив этот скрипт снова."

# ------------------------------------------------- проверка уведомлений --

# Канал уведомлений проверяем сейчас, а не при первой продаже: неверный
# токен или id обнаружатся тогда, когда деньги уже пришли, а сообщения нет.
send_test_message() {
  local token="$1" chat="$2" code
  code="$(curl -s -o /tmp/tg-test.json -w '%{http_code}' --max-time 15 \
    -X POST "https://api.telegram.org/bot${token}/sendMessage" \
    -H 'Content-Type: application/json' \
    -d "{\"chat_id\":\"${chat}\",\"text\":\"✅ HollVPN: уведомления настроены. Сюда будут приходить оплаты.\"}" \
    2>/dev/null || echo 000)"
  printf '%s' "$code"
}

TG_TOKEN_NOW="$(current TELEGRAM_BOT_TOKEN)"
TG_CHAT_NOW="$(current TELEGRAM_ADMIN_CHAT_ID)"

if [ -n "$TG_TOKEN_NOW" ] && [ -n "$TG_CHAT_NOW" ]; then
  printf '\n'
  bold "Отправляю пробное сообщение в Telegram"
  CODE="$(send_test_message "$TG_TOKEN_NOW" "$TG_CHAT_NOW")"
  case "$CODE" in
    200)
      ok "доставлено — проверьте, пришло ли сообщение в Telegram" ;;
    401)
      warn "Telegram не принял токен (401). Проверьте TELEGRAM_BOT_TOKEN у @BotFather" ;;
    400)
      warn "Telegram отклонил запрос (400) — обычно это неверный chat id"
      warn "или вы ещё не написали боту: откройте его и нажмите «Старт»"
      [ -f /tmp/tg-test.json ] && warn "ответ: $(head -c 200 /tmp/tg-test.json)" ;;
    000)
      warn "не удалось связаться с api.telegram.org — проверьте сеть сервера" ;;
    *)
      warn "Telegram ответил $CODE"
      [ -f /tmp/tg-test.json ] && warn "ответ: $(head -c 200 /tmp/tg-test.json)" ;;
  esac
  rm -f /tmp/tg-test.json
fi

# --------------------------------------------------------------- проверка --

chown "$SERVICE_USER:$SERVICE_USER" "$ENV_FILE" 2>/dev/null || true
chmod 600 "$ENV_FILE"

printf '\n'
bold "Проверяю"

READY=1
[ -n "$(current YOOKASSA_SECRET_KEY)" ] || { warn "нет секретного ключа ЮKassa"; READY=0; }

HAS_TG=0
if [ -n "$(current TELEGRAM_BOT_TOKEN)" ] && [ -n "$(current TELEGRAM_ADMIN_CHAT_ID)" ]; then
  HAS_TG=1
elif [ -n "$(current TELEGRAM_BOT_TOKEN)" ] || [ -n "$(current TELEGRAM_ADMIN_CHAT_ID)" ]; then
  warn "токен и id задаются только вместе"
fi

HAS_FULFIL=0
case "$(current FULFILMENT_URL)" in http://*|https://*) HAS_FULFIL=1 ;; esac

if [ "$HAS_TG" -eq 0 ] && [ "$HAS_FULFIL" -eq 0 ]; then
  warn "не настроен ни один способ сообщить об оплате"
  READY=0
fi

if [ "$READY" -eq 0 ]; then
  printf '\n\033[0;33mСлужба не запущена — не хватает данных выше.\033[0m\n'
  printf 'Запустите этот скрипт снова, когда они будут.\n\n'
  exit 0
fi

if [ "$HAS_FULFIL" -eq 1 ]; then
  ok "выдача автоматическая, Telegram $([ "$HAS_TG" -eq 1 ] && echo 'как тревога' || echo 'НЕ настроен — о срыве узнаете только из /health')"
else
  ok "выдача вручную: уведомление в Telegram"
fi

printf '\n'
bold "Запускаю службу"
systemctl enable hollvpn-checkout >/dev/null 2>&1 || true
systemctl restart hollvpn-checkout
sleep 2

if systemctl is-active --quiet hollvpn-checkout; then
  ok "служба работает"
  printf '\n\033[1;32mОплата на сайте включена.\033[0m\n'
  printf 'Проверить:  curl localhost:%s/health\n\n' "$(current PORT)"
else
  printf '\n\033[0;31mСлужба не поднялась.\033[0m Смотрите:\n'
  printf '  journalctl -u hollvpn-checkout -n 30\n\n'
  exit 1
fi
