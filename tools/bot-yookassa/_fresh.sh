# Обновление копии перед запуском. Подключается через source.
#
# Скрипты живут в репозитории и запускаются с сервера, а значит легко
# запустить вчерашнюю копию и получить вчерашнее поведение. Один раз это
# уже стоило двух заходов: в набранной строке склеились две команды,
# git pull не выполнился, и установщик отработал старый — с тем же
# сообщением, которое к тому моменту было уже исправлено.
#
# Поэтому копия обновляет себя сама и перезапускается. Ровно один раз:
# HOLLVPN_FRESH закрывает путь к бесконечному кругу.
_freshen() {
  [ -z "${HOLLVPN_FRESH:-}" ] || return 0
  command -v git >/dev/null || return 0

  local root
  root=$(git -C "$HERE" rev-parse --show-toplevel 2>/dev/null) || return 0

  # Правки на сервере бывают осмысленными, и затирать их обновлением
  # нельзя: если рабочее дерево грязное, только предупреждаем.
  if [ -n "$(git -C "$root" status --porcelain 2>/dev/null)" ]; then
    printf '\033[0;33mВ %s есть несохранённые правки — не обновляю копию.\033[0m\n' "$root"
    return 0
  fi

  git -C "$root" fetch --quiet origin 2>/dev/null || return 0

  local upstream local_sha remote_sha
  upstream=$(git -C "$root" rev-parse --abbrev-ref '@{upstream}' 2>/dev/null) || return 0
  local_sha=$(git -C "$root" rev-parse HEAD 2>/dev/null)
  remote_sha=$(git -C "$root" rev-parse "$upstream" 2>/dev/null)
  [ "$local_sha" = "$remote_sha" ] && return 0

  printf '\033[0;33mКопия в %s устарела — обновляю и перезапускаюсь.\033[0m\n' "$root"
  if ! git -C "$root" merge --ff-only "$upstream" --quiet 2>/dev/null; then
    printf '\033[0;31m✗ Обновить не вышло. Обновите вручную:\033[0m\n'
    printf '    cd %s && sudo git pull\n' "$root"
    return 0
  fi
  printf '\033[0;32m✓\033[0m обновлено до %s\n\n' "$(git -C "$root" rev-parse --short HEAD)"
  HOLLVPN_FRESH=1 exec bash "$0" "$@"
}
