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
ACADEMY_GUEST_MODE=1
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
# runuser inherits the calling shell's working directory. If installation was
# launched from /home/<admin>/LinuxAcademy (often mode 0700), linuxacademy
# cannot chdir there and Podman fails before reading its own configuration.
# The deployed directory is owned by the dedicated service account.
cd "$INSTALL"
RUN_AS=(runuser -u "$SERVICE" -- env "HOME=$HOME_DIR" "XDG_RUNTIME_DIR=/run/user/${UID_LAB}")
"${RUN_AS[@]}" podman info >/dev/null || {
 echo 'Rootless Podman не запустился. Проверьте /etc/subuid, /etc/subgid, loginctl и user@UID.service.' >&2; exit 1;
}
echo '[5/8] Сборка семи Linux-образов (при первом запуске требуются репозитории и сеть)'
for item in ubuntu debian alma fedora arch opensuse alpine; do
 case "$item" in
  ubuntu) tag='localhost/linuxacademy-ubuntu:24.04';;
  debian) tag='localhost/linuxacademy-debian:13';;
  alma) tag='localhost/linuxacademy-alma:9';;
  fedora) tag='localhost/linuxacademy-fedora:43';;
  arch) tag='localhost/linuxacademy-arch:latest';;
  opensuse) tag='localhost/linuxacademy-opensuse:latest';;
  alpine) tag='localhost/linuxacademy-alpine:3.24';;
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

echo '[7/8] Инициализация учебной платформы без администратора'
cd "$INSTALL"
runuser -u "$SERVICE" -- env ACADEMY_DATA_DIR="$HOME_DIR/data" \
  "$INSTALL/.venv/bin/python" -c 'from app import storage; storage.init_db()'

echo '[8/8] Перезапуск приложения и проверка страниц'
systemctl daemon-reload
# enable --now does NOT restart an already active unit. This used to serve old
# Python routes against new Jinja templates after an update (500/404 errors).
systemctl enable linuxacademy.service nginx.service
systemctl restart linuxacademy.service
systemctl restart nginx.service
if ! systemctl is-active --quiet linuxacademy.service; then
  journalctl -u linuxacademy -n 60 --no-pager >&2
  echo 'Ошибка: служба linuxacademy не запустилась.' >&2
  exit 1
fi
# Verify *actual running app* and endpoints, not just systemd's state.
healthy=0
for attempt in $(seq 1 15); do
  if "$INSTALL/.venv/bin/python" -c 'import http.client
for path in ("/healthz", "/profile", "/register"):
    c=http.client.HTTPConnection("127.0.0.1", 8086, timeout=4)
    c.request("GET",path)
    r=c.getresponse()
    assert (r.status==200 and b"status" in r.read()) if path=="/healthz" else r.status in (200,303)
    c.close()
' >/dev/null 2>&1; then healthy=1; break; fi
  sleep 1
done
if [[ "$healthy" != 1 ]]; then
  echo 'Ошибка: приложение не отвечает на /healthz, /profile или /register' >&2
  journalctl -u linuxacademy -n 80 --no-pager >&2
  exit 1
fi
nginx -t
bash "$INSTALL/scripts/site-url.sh"
echo 'Для повторного вывода адреса: sudo bash /opt/linuxacademy/scripts/site-url.sh'
echo 'Сертификат при первой установке самоподписанный; замените корпоративным TLS.'
