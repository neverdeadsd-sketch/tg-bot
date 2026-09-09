#!/usr/bin/env bash
#
# Переносит адреса подписок из старого merge_sub.sh в /root/.merge_sub.env.
#
#   sudo bash /opt/hollvpn/tools/merge-sub/init-env.sh
#
# Значения не печатаются и никуда не отправляются: они лишь перекладываются
# из одного файла на этом же сервере в другой. В выводе — только маска.
#
set -euo pipefail

SRC="${SRC:-/root/merge_sub.sh}"
DST="${DST:-/root/.merge_sub.env}"

die() { printf '\n\033[0;31mОстановлено:\033[0m %s\n\n' "$*" >&2; exit 1; }
ok()  { printf '  \033[0;32m✓\033[0m %s\n' "$*"; }

[ "$(id -u)" -eq 0 ] || die "Запускайте через sudo"
[ -f "$SRC" ] || die "Нет $SRC — откуда брать адреса, неизвестно.
  Если старый скрипт называется иначе:  sudo SRC=/путь/к/нему bash $0"

# Адреса подписок — это те самые два curl в начале скрипта.
mapfile -t URLS < <(grep -oE 'https://[^"'"'"' ]+' "$SRC" | head -2)
[ "${#URLS[@]}" -eq 2 ] || die "В $SRC нашлось ${#URLS[@]} адресов вместо двух.
  Посмотрите глазами:  sudo grep -n curl $SRC"

NL="${URLS[0]}"
FI="${URLS[1]}"

# Порядок в старом скрипте: сначала Нидерланды, потом Финляндия.
# Проверяем, что не перепутано, — по имени финского узла.
case "$FI" in
  *fi.*) ;;
  *) die "Второй адрес не похож на финский узел.
  Порядок в $SRC мог измениться — проверьте:  sudo grep -n curl $SRC" ;;
esac

mask() { printf '%s' "$1" | sed -E 's#(https://[^/]+/)[^/]+/[^/]+/#\1***/***/#'; }

if [ -f "$DST" ]; then
  cp "$DST" "$DST.bak.$(date +%s)"
  ok "прежний $DST сохранён рядом"
fi

umask 077
cat > "$DST" <<ENV
# Заполнено из $SRC — $(date '+%d.%m.%Y %H:%M')
# После смены UUID в панели Hiddify адреса нужно обновить здесь.

NL_URL=$NL
FI_URL=$FI

NL_NAME=🇳🇱 Нидерланды
FI_NAME=🇫🇮 Финляндия

# Голландская панель отвечает по IP, сертификат на него не выписан.
INSECURE=1
ENV
chmod 600 "$DST"

ok "записано в $DST (права 600)"
printf '    NL_URL=%s\n' "$(mask "$NL")"
printf '    FI_URL=%s\n' "$(mask "$FI")"
printf '\nТеперь:  sudo python3 /root/merge_sub.py\n\n'
