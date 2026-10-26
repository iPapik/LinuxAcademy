#!/usr/bin/env bash
# Необязательная проверка исходников перед установкой.
set -euo pipefail
if [[ -f app/main.py && -f scripts/install.sh && -f content/curriculum.json && -f static/vendor/xterm.js ]]; then
  echo 'Исходники LinuxAcademy присутствуют. Можно запускать: sudo bash scripts/install.sh'
  exit 0
fi
if [[ ! -f source/LinuxAcademy.tar.xz.base64 ]]; then
  echo 'Исходники отсутствуют. Выполните повторное клонирование GitHub-репозитория.' >&2
  exit 1
fi
command -v xz >/dev/null || { echo 'Установите xz-utils' >&2; exit 1; }
TMP_ARCHIVE="$(mktemp /tmp/linuxacademy.XXXXXXXX.tar.xz)"
trap 'rm -f "$TMP_ARCHIVE"' EXIT
base64 --decode source/LinuxAcademy.tar.xz.base64 > "$TMP_ARCHIVE"
printf '%s  %s\n' e4fd4fe524dad95cd0ac5f07d5a719ae5aa839b11a252cb79b5829126ad538ca "$TMP_ARCHIVE" | sha256sum -c -
tar -xJf "$TMP_ARCHIVE" --strip-components=1
echo 'Исходники восстановлены. Можно запускать: sudo bash scripts/install.sh'
