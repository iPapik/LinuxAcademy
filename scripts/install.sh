#!/usr/bin/env bash
# On-prem LinuxAcademy installer. For a dedicated Ubuntu 24.04 / Debian 13 VM.
set -euo pipefail
if (( EUID != 0 )); then echo 'Запустите: sudo bash scripts/install.sh' >&2; exit 1; fi
if [[ ! -f ./manage.py || ! -d ./images ]]; then echo 'Запустите из корня распакованной папки LinuxAcademy' >&2; exit 1; fi
if ! grep -qE '^ID=(ubuntu|debian)$' /etc/os-release; then echo 'Поддерживается установщик Ubuntu/Debian. Для других ОС нужны ручные шаги.' >&2; exit 1; fi
if [[ -e /etc/nginx/sites-enabled/linuxacademy && -e /opt/linuxacademy/app/main.py ]]; then
 echo 'Платформа уже установлена. Скрипт сохранит БД, но обновит приложение и образы.'
fi
SOURCE=$(pwd -P)
SERVICE=linuxacademy
INSTALL=/opt/linuxacademy
HOME_DIR=/var/lib/linuxacademy
HOST_IP=$(hostname -I | awk '{print $1}')
HOST_IP=${HOST_IP:-127.0.0.1}
HOST_FQDN=$(hostname -f 2>/dev/null || hostname)
echo "[1/8] Установка Podman, nginx и Python на $(hostname)"
apt-get update
apt-get install -y python3 python3-venv python3-pip podman uidmap slirp4netns \
 fuse-overlayfs nginx openssl rsync ca-certificates dbus-user-session
if ! id "$SERVICE" &>/dev/null; then
 useradd -m -U -d "$HOME_DIR" -s /bin/bash "$SERVICE"
fi
UID_LAB=$(id -u "$SERVICE")
GID_LAB=$(id -g "$SERVICE")
# Rootless Podman needs subordinate UID/GID ranges for useradd/chown practice.
if ! grep -q "^${SERVICE}:" /etc/subuid; then usermod --add-subuids 200000-265535 "$SERVICE"; fi
if ! grep -q "^${SERVICE}:" /etc/subgid; then usermod --add-subgids 200000-265535 "$SERVICE"; fi
loginctl enable-linger "$SERVICE"
systemctl start "user@${UID_LAB}.service" || true
install -d -m 750 -o "$SERVICE" -g "$SERVICE" "$HOME_DIR/data"
echo '[2/8] Копирование приложения (данные пользователей не удаляются)'
mkdir -p "$INSTALL"
rsync -a --delete --exclude '.venv/' --exclude 'data/' --exclude '.git/' \
  "$SOURCE/" "$INSTALL/"
chown -R "$SERVICE:$SERVICE" "$INSTALL"
echo '[3/8] Настройка Python'
python3 -m venv "$INSTALL/.venv"
"$INSTALL/.venv/bin/pip" install --disable-pip-version-check -r "$INSTALL/requirements.txt"
chown -R "$SERVICE:$SERVICE" "$INSTALL"
cat >/etc/linuxacademy.env <<ENV
ACADEMY_DATA_DIR=${HOME_DIR}/data
ACADEMY_SECURE_COOKIE=1
HOME=${HOME_DIR}
XDG_RUNTIME_DIR=/run/user/${UID_LAB}
ENV
chmod 640 /etc/linuxacademy.env
# System service intentionally has no access to a privileged Docker socket.
cat >/etc/systemd/system/linuxacademy.service <<EOF2
[Unit]
Description=LinuxAcademy on-prem learning application
After=network-online.target user@${UID_LAB}.service
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE}
Group=${SERVICE}
WorkingDirectory=${INSTALL}
EnvironmentFile=/etc/linuxacademy.env
ExecStart=${INSTALL}/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8086 --workers 1
Restart=on-failure
RestartSec=4
UMask=0077
LimitNOFILE=4096

[Install]
WantedBy=multi-user.target
EOF2

echo '[4/8] Проверка rootless Podman'
RUN_AS=(runuser -u "$SERVICE" -- env "HOME=$HOME_DIR" "XDG_RUNTIME_DIR=/run/user/${UID_LAB}")
"${RUN_AS[@]}" podman info >/dev/null || {
 echo 'Rootless Podman не запустился. Проверьте /etc/subuid, /etc/subgid, loginctl и user@UID.service.' >&2; exit 1;
}
echo '[5/8] Сборка трёх Linux-образов (загрузка пакетов и образов нужна при первой установке)'
for item in ubuntu debian alma; do
 case "$item" in
  ubuntu) tag='localhost/linuxacademy-ubuntu:24.04';;
  debian) tag='localhost/linuxacademy-debian:13';;
  alma) tag='localhost/linuxacademy-alma:9';;
 esac
 echo "      $item → $tag"
 "${RUN_AS[@]}" podman build --pull=missing -t "$tag" \
   -f "$INSTALL/images/Containerfile.$item" "$INSTALL/images"
done

echo '[6/8] HTTPS: внутренний сертификат (в дальнейшем замените на сертификат корпоративного CA)'
install -d -m 700 /etc/linuxacademy/tls
if [[ ! -e /etc/linuxacademy/tls/server.crt ]]; then
 openssl req -x509 -nodes -newkey rsa:3072 -sha256 -days 365 \
  -keyout /etc/linuxacademy/tls/server.key \
  -out /etc/linuxacademy/tls/server.crt \
  -subj "/CN=${HOST_FQDN}" \
  -addext "subjectAltName=DNS:${HOST_FQDN},IP:${HOST_IP}"
 chmod 600 /etc/linuxacademy/tls/server.key
fi
cat >/etc/nginx/sites-available/linuxacademy <<'NGINX'
server {
    listen 443 ssl;
    server_name _;
    ssl_certificate /etc/linuxacademy/tls/server.crt;
    ssl_certificate_key /etc/linuxacademy/tls/server.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_tickets off;
    client_max_body_size 1m;
    add_header X-Content-Type-Options nosniff always;
    location / {
        proxy_pass http://127.0.0.1:8086;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;
    }
}
NGINX
ln -sfn /etc/nginx/sites-available/linuxacademy /etc/nginx/sites-enabled/linuxacademy
rm -f /etc/nginx/sites-enabled/default
nginx -t

echo '[7/8] Создание первого администратора'
cd "$INSTALL"
if [[ ! -f "$HOME_DIR/data/academy.sqlite3" ]] || \
   [[ "$(runuser -u "$SERVICE" -- env ACADEMY_DATA_DIR="$HOME_DIR/data" "$INSTALL/.venv/bin/python" manage.py stats | grep -o 'Пользователей: [0-9]*' | awk '{print $2}')" == 0 ]]; then
 echo 'Введите логин администратора (латинские строчные буквы); по умолчанию admin'
 read -r -p 'Логин: ' ADMIN_LOGIN
 ADMIN_LOGIN=${ADMIN_LOGIN:-admin}
 runuser -u "$SERVICE" -- env ACADEMY_DATA_DIR="$HOME_DIR/data" \
    "$INSTALL/.venv/bin/python" manage.py create-admin "$ADMIN_LOGIN"
else
 echo 'Пользователи уже существуют, администратор не создаётся повторно.'
fi

echo '[8/8] Запуск службы и nginx'
systemctl daemon-reload
systemctl enable --now linuxacademy.service
systemctl enable --now nginx.service
systemctl restart nginx.service
systemctl --no-pager --full status linuxacademy.service | head -n 14 || true
echo
printf 'LinuxAcademy: https://%s/\n' "$HOST_IP"
echo 'Сертификат самоподписанный. Для доверенного доступа установите корпоративный TLS-сертификат.'
echo 'Проверка: curl -k https://127.0.0.1/healthz'
echo 'Журнал: journalctl -u linuxacademy -f'
