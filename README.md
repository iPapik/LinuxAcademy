# LinuxAcademy

Внутренняя учебная платформа по Linux: теория, тестирование, терминалы Ubuntu/Debian/AlmaLinux и практические задания с автоматической проверкой.

## Установка через Git

ОС сервера: **Ubuntu Server 24.04 LTS** или **Debian 13**, отдельная VM (от 4 vCPU, 8 ГБ RAM, 40 ГБ диска). Первоначально требуются подключение к репозиториям ОС, PyPI, Docker Hub и Quay.io и права sudo.

```bash
sudo apt-get update
sudo apt-get install -y git xz-utils ca-certificates
git clone https://github.com/iPapik/LinuxAcademy.git
cd LinuxAcademy
bash setup.sh
sudo bash scripts/install.sh
```

Команда `bash setup.sh` распаковывает исходный проект из переносимого архива в папке `.dist/` и проверяет его SHA-256. Это временный формат доставки первоначальной сборки; исходный код после распаковки доступен обычными файлами и может храниться в Git.

После установки: **https://IP-сервера/**. Установщик запросит логин и пароль администратора, создаст systemd-сервис `linuxacademy`, nginx и rootless Podman.

Проверка:
```bash
sudo systemctl status linuxacademy nginx --no-pager
curl -k https://127.0.0.1/healthz
sudo journalctl -u linuxacademy -n 100 --no-pager
```

Подробности — в `INSTALL_GIT.md`; после распаковки — также в `README.md` (основной мануал приложения) и `VIRTUAL_MACHINES.md`.

### Безопасность
Размещайте систему на отдельной Linux VM в учебном сегменте сети. Учебные контейнеры не эквивалентны полноценным виртуальным машинам. Версия 1.0 требует локального пилотного тестирования перед предоставлением доступа сотрудникам.
