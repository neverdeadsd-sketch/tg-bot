#!/usr/bin/env bash
#
# Проверка сайта перед публикацией.
#
#   bash scripts/check-site.sh
#
# Главное, что здесь проверяется, — сайт не загружает ничего извне.
# Это не стилистическое требование: сайт продаёт приватность, и запрос
# к чужому CDN на странице про отсутствие логов означал бы, что адрес
# каждого посетителя уходит третьей стороне ещё до покупки. Ссылки на
# t.me — это переходы по клику, а не загрузка, они разрешены.
#
set -euo pipefail

SITE="${SITE:-site}"
FAIL=0

fail() { printf '\033[0;31m✗\033[0m %s\n' "$*" >&2; FAIL=1; }
ok()   { printf '\033[0;32m✓\033[0m %s\n' "$*"; }

[ -d "$SITE" ] || { fail "нет каталога $SITE"; exit 1; }

# --- внешние подгружаемые ресурсы ------------------------------------------
# Ищем именно загрузку: src=, <link href=, @import, url() в CSS.
# <link rel="canonical"> и rel="alternate" ничего не загружают — это
# метаданные, и внешний адрес в них нормален. Загружают stylesheet,
# preload, prefetch, preconnect, dns-prefetch, icon и manifest.
EXTERNAL="$(
  { grep -rnoE '\ssrc="https?://[^"]*"' "$SITE" --include='*.html' || true
    grep -rnoE '<link[^>]+rel="(stylesheet|preload|prefetch|preconnect|dns-prefetch|icon|shortcut icon|apple-touch-icon|manifest)"[^>]*>' \
      "$SITE" --include='*.html' | grep -E 'href="https?://' || true
    grep -rnoE '@import[^;]*https?://[^;]*'        "$SITE" --include='*.css'  || true
    grep -rnoE 'url\(\s*["'"'"']?https?://[^)]*\)' "$SITE" --include='*.css'  || true
  } || true
)"
if [ -n "$EXTERNAL" ]; then
  fail "сайт подгружает внешние ресурсы:"
  printf '%s\n' "$EXTERNAL" >&2
else
  ok "внешних подгружаемых ресурсов нет"
fi

# --- синтаксис JS -----------------------------------------------------------
JS_BAD=0
while IFS= read -r f; do
  node --check "$f" 2>/dev/null || { fail "синтаксис: $f"; JS_BAD=1; }
done < <(find "$SITE" -name '*.js')
[ "$JS_BAD" -eq 0 ] && ok "JS разбирается"

# --- локальные ссылки ведут в существующие файлы ---------------------------
MISSING=""
while IFS= read -r f; do
  dir="$(dirname "$f")"
  while IFS= read -r target; do
    target="${target%%#*}"; target="${target%%\?*}"
    [ -n "$target" ] || continue
    case "$target" in http*|//*|mailto:*|tel:*|data:*) continue ;; esac
    [ -e "$dir/$target" ] || MISSING="$MISSING
  $f → $target"
  done < <(grep -ohE '(href|src)="[^"#][^"]*"' "$f" | sed -E 's/^(href|src)="//; s/"$//' | sort -u)
done < <(find "$SITE" -name '*.html')

if [ -n "$MISSING" ]; then
  fail "ссылки в никуда:"; printf '%s\n' "$MISSING" >&2
else
  ok "локальные ссылки ведут в существующие файлы"
fi

# --- обязательные файлы -----------------------------------------------------
for f in index.html guide.html robots.txt sitemap.xml favicon.svg; do
  [ -f "$SITE/$f" ] || fail "нет $SITE/$f"
done
ok "обязательные файлы на месте"

exit "$FAIL"
