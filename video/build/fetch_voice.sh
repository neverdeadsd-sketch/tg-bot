#!/usr/bin/env bash
# Скачивает нейросетевой русский голос Piper (ru-irinia-medium) в /tmp/piper.
set -e
DIR="${PIPER_VOICE_DIR:-/tmp/piper}"
URL="https://github.com/rhasspy/piper/releases/download/v0.0.2/voice-ru-irinia-medium.tar.gz"
mkdir -p "$DIR"
[ -s "$DIR/ru-irinia-medium.onnx" ] && { echo "голос уже на месте: $DIR"; exit 0; }
curl -sSL --retry 3 -o "$DIR/voice.tar.gz" "$URL"
tar xzf "$DIR/voice.tar.gz" -C "$DIR"
rm -f "$DIR/voice.tar.gz"
echo "голос загружен в $DIR"
