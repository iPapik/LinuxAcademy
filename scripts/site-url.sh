#!/usr/bin/env bash
# Print reachable addresses for an installed LinuxAcademy portal.
set -euo pipefail
if ! systemctl is-active --quiet linuxacademy.service; then
  echo 'LinuxAcademy: служба не запущена (systemctl status linuxacademy)' >&2
  exit 1
fi
if ! systemctl is-active --quiet nginx.service; then
  echo 'LinuxAcademy: nginx не запущен' >&2
  exit 1
fi
printf '\n=== LinuxAcademy — адреса сайта ===\n'
ips=$(hostname -I 2>/dev/null || true)
if [[ -z "${ips// /}" ]]; then
  ips=$(ip -4 -o addr show scope global | awk '{split($4,a,"/");print a[1]}' | tr '\n' ' ')
fi
count=0
for ip in $ips; do
  case "$ip" in
    127.*|169.254.*) continue;;
  esac
  printf '  https://%s/\n' "$ip"
  count=$((count+1))
done
if [[ "$count" == 0 ]]; then
  printf '  https://<IP_сервера>/\n'
fi
printf '  Локальная проверка: curl -k https://127.0.0.1/healthz\n'
printf '  Регистрация: https://<IP_сервера>/register\n'
printf '  Профиль: https://<IP_сервера>/profile\n'
printf '  Внимание: браузер может предупредить о самоподписанном сертификате.\n\n'
