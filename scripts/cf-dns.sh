#!/usr/bin/env bash
#
# Записи домена в Cloudflare.
#
#   CLOUDFLARE_API_TOKEN=... bash scripts/cf-dns.sh          # только показать
#   CLOUDFLARE_API_TOKEN=... APPLY=1 bash scripts/cf-dns.sh  # применить
#
# Зачем скрипт, если записи можно завести мышью в панели: панель
# показывает состояние только тому, кто в неё смотрит, а ошибка в одной
# записи здесь стоит рабочего VPN у живых клиентов. Скрипт печатает
# план целиком и делает ровно то, что напечатал.
#
# Правило, ради которого всё это писалось: узловые поддомены (fi и
# прочие) переносятся из действующей зоны как есть и всегда без
# оранжевого облака. Проксирование Cloudflare ломает VLESS/Reality —
# клиент попадёт не на узел, а на прокси Cloudflare, и подключение
# перестанет работать.
#
set -euo pipefail

DOMAIN="${DOMAIN:-hollvpn.ru}"
PAGES_HOST="${PAGES_HOST:-neverdeadsd-sketch.github.io}"
APPLY="${APPLY:-0}"

# Откуда действующая зона отдаётся сегодня. Нужен, чтобы переносить
# реальные значения, а не те, что мы помним.
LIVE_NS="${LIVE_NS:-ns1.reg.ru}"

# Адреса GitHub Pages. Постоянные, задокументированы GitHub.
PAGES_IPS='185.199.108.153 185.199.109.153 185.199.110.153 185.199.111.153'

# Имена, которые проверяем в действующей зоне. Всё, что отвечает, должно
# оказаться в Cloudflare без изменений. Список пополняется руками —
# перечислить содержимое чужой зоны иначе нельзя (AXFR закрыт).
PROBE='fi nl de se us uk sub panel api mail vpn node1 node2 s1 s2'

red()  { printf '\033[0;31m%s\033[0m\n' "$*" >&2; }
grn()  { printf '\033[0;32m%s\033[0m\n' "$*"; }
ylw()  { printf '\033[0;33m%s\033[0m\n' "$*"; }
die()  { red "✗ $*"; exit 1; }

command -v jq  >/dev/null || die 'нужен jq'
command -v dig >/dev/null || die 'нужен dig (пакет dnsutils)'
[ -n "${CLOUDFLARE_API_TOKEN:-}" ] || die 'не задан CLOUDFLARE_API_TOKEN'

# Токен уходит в файл, а не в аргументы curl: аргументы видны в списке
# процессов любому, кто оказался на той же машине.
umask 077
CFG="$(mktemp)"
WORK="$(mktemp -d)"
trap 'rm -rf "$CFG" "$WORK"' EXIT
printf 'header = "Authorization: Bearer %s"\nheader = "Content-Type: application/json"\nsilent\nshow-error\n' \
  "$CLOUDFLARE_API_TOKEN" > "$CFG"

api() { # МЕТОД ПУТЬ [ТЕЛО]
  if [ $# -ge 3 ]; then
    curl -K "$CFG" -X "$1" "https://api.cloudflare.com/client/v4$2" --data "$3"
  else
    curl -K "$CFG" -X "$1" "https://api.cloudflare.com/client/v4$2"
  fi
}

ok_or_die() { # ФАЙЛ ЧТО-ДЕЛАЛИ
  jq -e '.success' "$1" >/dev/null 2>&1 && return 0
  red "✗ $2 — Cloudflare отказал:"
  jq -r '.errors[]? | "    \(.code): \(.message)"' "$1" >&2 2>/dev/null || cat "$1" >&2
  exit 1
}

# --- зона ------------------------------------------------------------------
api GET "/zones?name=$DOMAIN" > "$WORK/zone.json"
ok_or_die "$WORK/zone.json" "поиск зоны $DOMAIN"

ZONE_ID="$(jq -r '.result[0].id // empty' "$WORK/zone.json")"
if [ -z "$ZONE_ID" ]; then
  red "✗ Токен не видит зону $DOMAIN."
  cat >&2 <<MSG

  Так бывает в двух случаях: домен не заведён в Cloudflare, либо у токена
  нет прав на него. Токену нужно: Zone → DNS → Edit и Zone → Zone → Read,
  в Zone Resources — этот домен.
  Создать: Cloudflare → My Profile → API Tokens → Create Token.
  Положить в GitHub: Settings → Secrets and variables → Actions →
  CLOUDFLARE_API_TOKEN.
MSG
  exit 1
fi

ZONE_STATUS="$(jq -r '.result[0].status' "$WORK/zone.json")"
printf 'Зона %s: %s\n' "$DOMAIN" "$ZONE_STATUS"
printf 'Cloudflare ждёт делегирование на:\n'
jq -r '.result[0].name_servers[] | "  " + .' "$WORK/zone.json"
printf 'Реестр .ru отдаёт сейчас:\n'
dig +short NS "$DOMAIN" @a.dns.ripn.net 2>/dev/null | sed 's/^/  /' || echo '  (не удалось спросить реестр)'
echo

# --- чего хотим ------------------------------------------------------------
# Формат: тип \t имя \t значение \t режим
#   manage   — имя наше целиком, лишние записи на нём удаляем
#   preserve — запись должна быть; лишнее на этом имени только показываем
DESIRED="$WORK/desired.tsv"
: > "$DESIRED"
for ip in $PAGES_IPS; do
  printf 'A\t%s\t%s\tmanage\n' "$DOMAIN" "$ip" >> "$DESIRED"
done
printf 'CNAME\twww.%s\t%s\tmanage\n' "$DOMAIN" "$PAGES_HOST" >> "$DESIRED"

# Узловые поддомены — из действующей зоны, как они отдаются сегодня.
FOUND=''
for n in $PROBE; do
  host="$n.$DOMAIN"
  a="$(dig +short A "$host" @"$LIVE_NS" 2>/dev/null | grep -E '^[0-9.]+$' || true)"
  c="$(dig +short CNAME "$host" @"$LIVE_NS" 2>/dev/null | head -1)"
  if [ -n "$a" ]; then
    for ip in $a; do printf 'A\t%s\t%s\tpreserve\n' "$host" "$ip" >> "$DESIRED"; done
    FOUND="$FOUND $host"
  elif [ -n "$c" ]; then
    printf 'CNAME\t%s\t%s\tpreserve\n' "$host" "${c%.}" >> "$DESIRED"
    FOUND="$FOUND $host"
  fi
done
if [ -n "$FOUND" ]; then
  printf 'В действующей зоне (%s) найдены узлы:%s\n' "$LIVE_NS" "$FOUND"
else
  ylw "⚠ В действующей зоне не нашлось ни одного узла из списка: $PROBE"
  ylw "  Если узлы называются иначе — допишите их в PROBE, иначе они не переедут."
fi
echo

# --- что есть --------------------------------------------------------------
api GET "/zones/$ZONE_ID/dns_records?per_page=200" > "$WORK/have.json"
ok_or_die "$WORK/have.json" 'чтение записей'
jq -r '.result[] | [.type,.name,.content,(.proxied|tostring),.id] | @tsv' \
  "$WORK/have.json" > "$WORK/have.tsv"

echo 'Сейчас в Cloudflare:'
if [ -s "$WORK/have.tsv" ]; then
  while IFS=$'\t' read -r t n c p _; do
    printf '  %-6s %-24s %-32s %s\n' "$t" "$n" "$c" \
      "$([ "$p" = true ] && echo 'оранжевое облако' || echo '')"
  done < "$WORK/have.tsv"
else
  echo '  (пусто)'
fi
echo

# --- план ------------------------------------------------------------------
PLAN="$WORK/plan.tsv"
: > "$PLAN"

# Что должно быть, но нет — или есть, но с оранжевым облаком.
while IFS=$'\t' read -r t n c mode; do
  line="$(awk -F'\t' -v t="$t" -v n="$n" -v c="$c" \
          '$1==t && $2==n && $3==c {print; exit}' "$WORK/have.tsv" || true)"
  if [ -z "$line" ]; then
    printf 'create\t%s\t%s\t%s\t\n' "$t" "$n" "$c" >> "$PLAN"
  else
    proxied="$(printf '%s' "$line" | cut -f4)"
    rid="$(printf '%s' "$line" | cut -f5)"
    [ "$proxied" = true ] && printf 'unproxy\t%s\t%s\t%s\t%s\n' "$t" "$n" "$c" "$rid" >> "$PLAN"
  fi
done < "$DESIRED"

# Лишнее на именах, которые ведём целиком.
while IFS=$'\t' read -r t n c p rid; do
  case "$t" in A|AAAA|CNAME) ;; *) continue ;; esac
  mode="$(awk -F'\t' -v n="$n" '$2==n {print $4; exit}' "$DESIRED")"
  # Запись уже есть в списке нужных — не трогаем.
  awk -F'\t' -v t="$t" -v n="$n" -v c="$c" \
      '$1==t && $2==n && $3==c {found=1} END {exit !found}' "$DESIRED" && continue
  if [ "$mode" = manage ]; then
    printf 'delete\t%s\t%s\t%s\t%s\n' "$t" "$n" "$c" "$rid" >> "$PLAN"
  else
    # Имя не наше: удалять вслепую нельзя — вдруг это узел, которого нет
    # в списке PROBE. Показываем и оставляем как есть.
    printf '%s\t%s\t%s\n' "$t" "$n" "$c" >> "$WORK/extra.tsv"
  fi
done < "$WORK/have.tsv"

if [ -s "$WORK/extra.tsv" ]; then
  ylw 'Записи, которых нет в нужном списке — оставляю как есть:'
  while IFS=$'\t' read -r t n c; do
    printf '  %-6s %-24s %s\n' "$t" "$n" "$c"
  done < "$WORK/extra.tsv"
  ylw '  Если это мусор от автоматического сканирования Cloudflare — удалите'
  ylw '  их в панели. Если это действующий узел — допишите имя в PROBE.'
  echo
fi

if [ ! -s "$PLAN" ]; then
  grn '✓ Всё уже так, как нужно — менять нечего.'
  exit 0
fi

echo 'План:'
while IFS=$'\t' read -r act t n c _; do
  case "$act" in
    create)  printf '  \033[0;32m+\033[0m %-6s %-24s %s\n' "$t" "$n" "$c" ;;
    delete)  printf '  \033[0;31m−\033[0m %-6s %-24s %s\n' "$t" "$n" "$c" ;;
    unproxy) printf '  \033[0;33m~\033[0m %-6s %-24s %s — выключить оранжевое облако\n' "$t" "$n" "$c" ;;
  esac
done < "$PLAN"
echo

if [ "$APPLY" != 1 ]; then
  ylw 'Ничего не меняю: это показ. Запустить с APPLY=1, чтобы применить.'
  exit 0
fi

# --- применение ------------------------------------------------------------
# Сначала создаём, потом удаляем: если что-то пойдёт не так на середине,
# домен останется с лишними записями, а не без единой.
while IFS=$'\t' read -r act t n c rid; do
  case "$act" in
    create)
      body="$(jq -nc --arg t "$t" --arg n "$n" --arg c "$c" \
              '{type:$t,name:$n,content:$c,ttl:1,proxied:false}')"
      api POST "/zones/$ZONE_ID/dns_records" "$body" > "$WORK/r.json"
      ok_or_die "$WORK/r.json" "создание $t $n → $c"
      grn "  + $t $n → $c"
      ;;
    unproxy)
      api PATCH "/zones/$ZONE_ID/dns_records/$rid" '{"proxied":false}' > "$WORK/r.json"
      ok_or_die "$WORK/r.json" "снятие проксирования с $t $n"
      grn "  ~ $t $n → $c (серое облако)"
      ;;
  esac
done < "$PLAN"

while IFS=$'\t' read -r act t n c rid; do
  [ "$act" = delete ] || continue
  api DELETE "/zones/$ZONE_ID/dns_records/$rid" > "$WORK/r.json"
  ok_or_die "$WORK/r.json" "удаление $t $n → $c"
  grn "  − $t $n → $c"
done < "$PLAN"

echo
api GET "/zones/$ZONE_ID/dns_records?per_page=200" > "$WORK/after.json"
ok_or_die "$WORK/after.json" 'перечитывание записей'
echo 'Стало:'
jq -r '.result[] | [.type,.name,.content,(if .proxied then "оранжевое облако" else "" end)] | @tsv' \
  "$WORK/after.json" |
  while IFS=$'\t' read -r t n c p; do printf '  %-6s %-24s %-32s %s\n' "$t" "$n" "$c" "$p"; done
echo
grn '✓ Готово. Записи вступят в силу, когда реестр .ru опубликует делегирование.'
