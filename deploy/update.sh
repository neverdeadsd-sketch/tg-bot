#!/usr/bin/env bash
#
# Обновление сайта и чекаута после изменений в репозитории.
#
#   sudo bash /opt/hollvpn/deploy/update.sh
#
# Не трогает .env, базу заказов, сертификаты и конфигурацию nginx.
#
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/hollvpn}"
SITE_DIR="${SITE_DIR:-/var/www/hollvpn}"
BRANCH="${BRANCH:-claude/hollvpn-website-3d-k9507m}"

say() { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
ok()  { printf '    \033[0;32m✓\033[0m %s\n' "$*"; }
die() { printf '\n\033[0;31mОстановлено:\033[0m %s\n\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Запускайте через sudo"
[ -d "$APP_DIR/.git" ] || die "$APP_DIR не похож на установку — сначала install.sh"

say "Забираю изменения"
BEFORE="$(git -C "$APP_DIR" rev-parse --short HEAD)"
git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
git -C "$APP_DIR" reset --hard --quiet "origin/$BRANCH"
AFTER="$(git -C "$APP_DIR" rev-parse --short HEAD)"

if [ "$BEFORE" = "$AFTER" ]; then
  ok "изменений нет ($AFTER)"
else
  ok "$BEFORE → $AFTER"
fi

say "Прогоняю тесты чекаута"
if (cd "$APP_DIR/checkout" && npm test >/tmp/hollvpn-test.log 2>&1); then
  ok "тесты прошли"
else
  die "тесты не прошли, обновление остановлено. Лог: /tmp/hollvpn-test.log
  Рабочая версия не тронута — служба продолжает работать на прежнем коде."
fi

say "Обновляю сайт"
cp -r "$APP_DIR/site/." "$SITE_DIR/"
chown -R www-data:www-data "$SITE_DIR"
ok "статика обновлена"

say "Перезапускаю чекаут"
chown -R hollvpn:hollvpn "$APP_DIR/checkout"
chmod 600 "$APP_DIR/checkout/.env" 2>/dev/null || true
systemctl restart hollvpn-checkout
sleep 2
if systemctl is-active --quiet hollvpn-checkout; then
  ok "служба работает"
else
  die "служба не поднялась: journalctl -u hollvpn-checkout -n 30"
fi

printf '\n\033[1;32mОбновлено.\033[0m\n\n'
