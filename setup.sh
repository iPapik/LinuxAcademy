#!/usr/bin/env bash
set -euo pipefail
if [[ -f app/main.py && -f scripts/install.sh && -f content/curriculum.json ]]; then
  echo 'Исходники LinuxAcademy присутствуют. Продолжите: sudo bash scripts/install.sh'
  exit 0
fi
if [[ -f source/LinuxAcademy.tar.xz.base64 ]]; then
  command -v xz >/dev/null || { echo 'Установите xz-utils' >&2; exit 1; }
  base64 --decode source/LinuxAcademy.tar.xz.base64 > /tmp/linuxacademy-$$.tar.xz
  trap 'rm -f /tmp/linuxacademy-$$.tar.xz' EXIT
  echo 'e4fd4fe524dad95cd0ac5f07d5a719ae5aa839b11a252cb79b5829126ad538ca  /tmp/linuxacademy-'$$'.tar.xz' | sha256sum -c -
  tar -xJf /tmp/linuxacademy-$$.tar.xz --strip-components=1
  echo 'Исходники восстановлены. Продолжите: sudo bash scripts/install.sh'
  exit 0
fi
echo 'Отсутствует исходный код LinuxAcademy. Повторно склонируйте репозиторий.' >&2
exit 1
