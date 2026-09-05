#!/usr/bin/env sh
# Same convenience on Linux/macOS: ./tgnames.sh ui
cd "$(dirname "$0")" || exit 1
if [ -x .venv/bin/python ]; then
  exec .venv/bin/python run.py "$@"
fi
exec python3 run.py "$@"
