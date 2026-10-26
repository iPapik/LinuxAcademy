# LinuxAcademy — установка и обновление через GitHub

Репозиторий: https://github.com/iPapik/LinuxAcademy

## 0. Перед установкой: убедитесь, что исходный код опубликован

На странице репозитория должны находиться `app/`, `content/`, `images/`, `templates/`, `static/`, `manage.py`, `requirements.txt`, `scripts/install.sh` и `README.md`. Одна только инструкция или `setup.sh` **не означает, что приложение загружено**. Если в репозитории исходников нет, см. раздел «Первичная публикация исходников» ниже.

## 1. Требования

- Отдельная виртуальная машина: Ubuntu Server 24.04 LTS или Debian 13, 64-bit.
- Начальный пилотный стенд: 4 vCPU, 8 ГБ оперативной памяти, 40 ГБ диска.
- Доступ пользователя к `sudo`; сеть только из учебного сегмента; DNS в порядке.
- Для первой установки — доступ к репозиториям apt, PyPI, Docker Hub и Quay.io (либо корпоративные зеркала).
- На этапе запуска скрипт устанавливает nginx, Python, Podman и прочие зависимости; подготовьте окно обслуживания и снапшот виртуальной машины.
- Не устанавливайте в продакшн на DC, Hyper-V host, WSUS или сервер мониторинга.

## 2. Скачивание из GitHub и установка

Сначала подключитесь к серверу по SSH.

```bash
sudo apt update
sudo apt install -y git ca-certificates
cd /opt
sudo git clone https://github.com/iPapik/LinuxAcademy.git
cd /opt/LinuxAcademy
ls -la scripts/install.sh app/main.py content/curriculum.json static/vendor/xterm.js
sudo bash scripts/install.sh
```

Если команда `ls` показывает ошибку «No such file or directory», значит исходники ещё не загружены в репозиторий: не запускайте установку, пока не опубликуете полный проект. Если `git clone` не работает, проверьте DNS, прокси предприятия и разрешения HTTPS к GitHub. У публичного репозитория чтение по HTTPS не требует токена.

Установщик интерактивный: при первом запуске задаётся администратор. Перед публикацией на предприятии разверните и проверьте учебные контейнеры на изолированной VM.

После успешной установки откройте:

```
https://IP-адрес-сервера/
```

Самоподписанный сертификат замените корпоративным, совпадающим с DNS-именем сайта.

## 3. Проверка работоспособности

```bash
sudo systemctl status linuxacademy nginx --no-pager
curl -k https://127.0.0.1/healthz
sudo journalctl -u linuxacademy -n 100 --no-pager
sudo bash /opt/linuxacademy/scripts/diagnose.sh
```

Проверьте в браузере вход администратором, создание пользователя, тест, запуск терминала Ubuntu/Debian/AlmaLinux, выполнение и сброс задания, раздельность пользовательских файлов.

## 4. Обновление из GitHub

Сначала создайте резервную копию БД и, если возможно, снапшот учебной VM.

```bash
sudo bash /opt/linuxacademy/scripts/backup.sh
cd /opt/LinuxAcademy
sudo git pull --ff-only origin main
sudo bash scripts/install.sh
sudo systemctl status linuxacademy nginx --no-pager
curl -k https://127.0.0.1/healthz
```

Не обновляйте через `git reset --hard`: это сотрёт ваши изменения исходников. Не храните пароли или ключи в Git, а пользовательские данные — в рабочем каталоге приложения. Установщик сохраняет базу `/var/lib/linuxacademy/data/academy.sqlite3`, однако новая версия может потребовать миграций — их пока нет.

## 5. Резервное копирование

```bash
sudo bash /opt/linuxacademy/scripts/backup.sh
sudo ls -lh /var/backups/linuxacademy/
```

Резервируются пользователи и прогресс, но **не** содержимое учебных контейнеров. Прогресс учеников и база находятся вне Git-репозитория.

## 6. Первичная публикация исходников (делается один раз)

Если репозиторий пока содержит только документацию, возьмите `LinuxAcademy.zip` из первоначальной сборки и скопируйте его на административную Linux VM/ПК, имеющий доступ на запись к GitHub. Выполните:

```bash
sudo apt install -y git unzip rsync
# Файл LinuxAcademy.zip должен находиться в текущем каталоге
bash /path/to/scripts/publish-repository.sh "$(pwd)/LinuxAcademy.zip"
```

Сам сценарий `scripts/publish-repository.sh` можно скачать из этого репозитория. Он клонирует репозиторий во временный каталог, проверяет ZIP, копирует исходники, фиксирует их одним коммитом и выполняет обычный `git push` **без force**. Для записи нужен настроенный GitHub SSH-ключ с доступом к репозиторию или HTTPS-аутентификация (например, через `gh auth login`). Не вводите токены в код проекта.

Для ручной публикации без сценария:

```bash
git clone https://github.com/iPapik/LinuxAcademy.git
unzip LinuxAcademy.zip
rsync -av --exclude .git LinuxAcademy/ LinuxAcademy-repo/
cd LinuxAcademy-repo
git add -A
git commit -m "Import LinuxAcademy 1.0 sources"
git push origin main
```

В ручном примере расположите ZIP и папку `LinuxAcademy-repo` в соответствии с вашей файловой системой; **не клонируйте репозиторий в ту же папку, куда распакован архив**.

## 7. Частые ошибки

- `fatal: could not read Username`: для отправки изменений на GitHub нужна аутентификация; простой пароль аккаунта для HTTPS Git больше не подходит.
- `remote: Permission to ... denied`: проверьте права на `iPapik/LinuxAcademy` и SSH-ключ/токен.
- `fatal: not possible to fast-forward`: в репозитории появились чужие изменения; не выполняйте `--force`, сначала согласуйте их.
- `cannot chdir to /home/<пользователь>/LinuxAcademy: Permission denied` на `[4/8]`: старый установщик запускал rootless Podman из домашнего каталога администратора, недоступного служебному пользователю. Исправление уже в `scripts/install.sh`: он переходит в `/opt/linuxacademy` перед переключением пользователя. Выполните `cd ~/LinuxAcademy && git pull --ff-only && sudo bash scripts/install.sh`. **Не меняйте** права домашнего каталога на `777` и не запускайте учебные контейнеры от root.
- `Error: building at STEP "RUN dnf install -y ..."` на `[5/8]` для AlmaLinux 9: старый `Containerfile.alma` запрашивал `coreutils`, несовместимый с предустановленным `coreutils-single`. В новой версии используется `coreutils-single`, как в базовом образе. Запустите `cd ~/LinuxAcademy && git pull --ff-only origin main && sudo bash scripts/install.sh`; уже собранные Ubuntu/Debian образы переиспользуются Podman. Не используйте `--skip-broken` или `--nobest` для обхода ошибки. При повторном сбое сохраните **весь** блок `Problem:` из `dnf`, а не только последнюю строку.
- `podman info: permission denied`: проверьте `/etc/subuid`, `/etc/subgid`, службу пользователя `linuxacademy`, AppArmor; не отключайте механизмы защиты вслепую.
- Не работает терминал: проверьте WebSocket `/ws/ubuntu`, обратный прокси nginx, журнал приложения и доверие TLS сертификату.

Подробнее об архитектуре и практикумах на настоящих виртуальных машинах: `docs/PLATFORM_README.md` и `docs/VIRTUAL_MACHINES.md`.