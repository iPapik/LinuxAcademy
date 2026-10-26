#!/usr/bin/env bash
set -u
echo '# LinuxAcademy: диагностика'
systemctl is-active linuxacademy nginx 2>&1 || true
ss -lntp | grep -E ':443|:8086' || true
curl -sk --max-time 5 https://127.0.0.1/healthz || true
echo
UID_LAB=$(id -u linuxacademy 2>/dev/null || true)
if [[ -n "$UID_LAB" ]]; then
 runuser -u linuxacademy -- env HOME=/var/lib/linuxacademy XDG_RUNTIME_DIR="/run/user/${UID_LAB}" podman images 2>&1 || true
fi
journalctl -u linuxacademy --no-pager -n 25 || true
