# Справочник администратора Linux

В этом справочнике собраны практические процедуры для Debian 13, Ubuntu Server 24.04 LTS и AlmaLinux 9. Каждая операция объясняется вместе с рисками, проверками результата и способом диагностики. Команды с `sudo` выполняйте **только на собственной учебной ВМ**. На производственном сервере сначала проверьте резервную копию, окно работ и способ отката.

## 1. Как устроена система Linux

Ядро Linux управляет планированием CPU, виртуальной памятью, файловыми системами, драйверами и сетевым стеком. Пользовательские процессы обращаются к ядру через системные вызовы. Дистрибутив поставляет пользовательские утилиты, менеджер пакетов, конфигурацию и средства обновления. `bash` — оболочка, `systemd` — система запуска служб, `sshd` — отдельный сервер удалённого доступа. Терминал — способ ввода и отображения текста, не синоним оболочки.

Процесс в контейнере разделяет ядро хоста. Поэтому `uname -r` в контейнере может показать ядро сервера, а `cat /etc/os-release` — гостевой дистрибутив. ВМ запускает собственное ядро, поэтому только на ней воспроизводимо изучать GRUB, initramfs, модуль ядра, работу реального сетевого интерфейса и полный процесс загрузки.

```bash
cat /etc/os-release
uname -a
lscpu
cat /proc/meminfo | head
cat /proc/1/comm
id
hostnamectl
```

**Проверка:** объясните, чем различаются поля `PRETTY_NAME`, `VERSION_ID`, `uname -r` и имя PID 1. Не используйте их взаимозаменяемо.

## 2. Установка ОС и первоначальная настройка

Для отдельного учебного сервера выделите 2–4 vCPU, 4–8 ГБ ОЗУ и динамический либо фиксированный виртуальный диск. Загрузите официальный ISO выбранной ОС, проверьте контрольную сумму, создайте ВМ с подходящими контроллерами и подключите ISO. Для UEFI предпочтительна схема GPT с EFI System Partition; для BIOS допустима MBR/GPT с нужным BIOS boot-разделом. Разметку не выполняйте на диске с нужными данными.

После установки создайте непривилегированного пользователя, установите SSH-сервер, настройте корректные адреса, DNS и время. Перед выключением ВМ убедитесь, что SSH действительно доступен, а вы знаете способ попасть в консоль гипервизора при ошибке сети.

```bash
# Ubuntu / Debian
sudo apt update
sudo apt install openssh-server sudo curl vim git
sudo systemctl enable --now ssh

# AlmaLinux 9
sudo dnf install openssh-server sudo curl vim git
sudo systemctl enable --now sshd

hostnamectl status
ip -br addr
ip route
resolvectl status  # Если используется systemd-resolved
```

**Проверка:** `ss -lntp | grep ':22'` показывает прослушивание порта; `systemctl status ssh` или `sshd` подтверждает запуск. Отдельно проверьте вход **с другого компьютера** и SSH host key.

## 3. Работа с оболочкой и помощь

Общая форма команды — `имя [опции] [аргументы]`. Bash сначала обрабатывает кавычки, переменные и шаблоны, затем запускает внешнюю программу либо встроенную команду. Одинарные кавычки отключают интерполяцию переменных; двойные допускают `$VAR`, но предотвращают разделение аргумента по пробелам. Почти любая ошибка в автоматизации начинается с неверной обработки аргументов.

```bash
pwd
which grep
type cd
help read
man grep
grep --help | head
printf 'HOME=%s\n' "$HOME"
false; echo "code=$?"
set -o pipefail
```

**Диагностика:** `command -v программа` показывает доступность инструмента. Коды `0` обычно означают успех, ненулевые — ошибку. В скрипте проверяйте статус каждого критичного шага.

## 4. Пути, ссылки и метаданные файлов

Абсолютный путь начинается с `/`, относительный зависит от текущего каталога. `.` — текущий каталог, `..` — родительский. Символическая ссылка хранит путь и может ссылаться на несуществующий объект; жёсткая ссылка указывает на тот же inode, обычно только в пределах одной файловой системы. Режим, владелец и группа — атрибуты inode, имя — запись каталога.

```bash
mkdir -p /workspace/demo/{config,logs}
printf 'port=8080\n' > /workspace/demo/config/app.conf
ln -s config/app.conf /workspace/demo/current.conf
stat /workspace/demo/config/app.conf
readlink -f /workspace/demo/current.conf
namei -l /workspace/demo/current.conf
find /workspace/demo -maxdepth 3 -type f -print
```

**Проверка:** объясните, почему удаление симлинка не удаляет целевой файл и чем отличаются `du -sh` и `df -h`.

## 5. Права доступа, umask, ACL, sudo

Базовый Unix-режим задаёт `rwx` для владельца, группы и остальных. Для файла `x` означает разрешение запуска, для каталога — право прохода по пути. `chmod 640` означает `rw-r-----`, а `chmod 750` — `rwxr-x---`. Сначала проверяйте владельца/группу и каждый родительский каталог, а не назначайте `777`. ACL расширяет классическую модель. `umask` удаляет определённые биты из режима при создании файла.

```bash
id
umask
stat -c '%a %U:%G %n' /workspace/demo/config/app.conf
chmod 640 /workspace/demo/config/app.conf
getfacl /workspace/demo/config/app.conf
sudo visudo -c
sudo -l
```

**Типичный сбой:** доступ на чтение файла разрешён, но один из родительских каталогов лишён `x`; результат — `Permission denied`. Используйте `namei -l /путь/к/файлу`. Не редактируйте `/etc/sudoers` обычным редактором; используйте `visudo` и файлы в `/etc/sudoers.d/`.

## 6. Пользователи, группы, PAM

Учётная запись связана с числовыми UID/GID, домашним каталогом и оболочкой. Файл `/etc/passwd` содержит метаданные; хеши паролей в `/etc/shadow` защищены специальными правами. PAM задаёт цепочки правил аутентификации, а NSS отвечает за поиск пользователей из локальных и внешних источников. При доменной интеграции могут участвовать SSSD/LDAP/AD.

```bash
getent passwd root
getent group sudo
id root
sudo useradd -m -s /bin/bash trainee
sudo passwd trainee
sudo usermod -aG sudo trainee  # Debian/Ubuntu
# В AlmaLinux привилегированная группа обычно wheel
sudo usermod -aG wheel trainee
sudo passwd -S trainee
```

**Проверка:** после изменения групп нужно начать **новую сессию**, старый процесс не получает новую группу автоматически. Если `sudo` пишет «отсутствует в sudoers», проверьте `id`, `groups`, `sudo -l`, `/etc/sudoers`, реальное имя группы и результаты нового входа.

## 7. Процессы, сигналы, ресурсы

Процесс имеет PID, родителя PPID, окружение, дескрипторы файлов и контекст прав. `SIGTERM` позволяет программе завершиться корректно, `SIGKILL` — принудительно прекращает выполнение и не может быть обработан. `nice` управляет приоритетом CPU; cgroups ограничивают ресурсы группы процессов. Большое значение load average само по себе не доказывает загрузку CPU: оно включает задачи в uninterruptible sleep.

```bash
ps aux --sort=-%cpu | head
ps -ef --forest | head
pgrep -af sshd
top
free -h
uptime
cat /proc/loadavg
ls -l /proc/1/fd | head
```

**Диагностика:** различайте высокую нагрузку на CPU, ожидание диска, нехватку памяти и OOM. Используйте `journalctl -k -b | grep -i oom`, `vmstat 1 5`, `iostat` (из sysstat). `kill -9` — последняя мера, а не основное средство администрирования.

## 8. systemd, unit-файлы и journalctl

Для systemd установка пакета и запуск службы — разные операции. Unit описывает команду, пользователя, зависимости, окружение, ограничения и restart policy. `daemon-reload` перечитывает конфигурацию юнитов, но не перезапускает службу. `enable` создаёт зависимости для автозапуска, `start` запускает сейчас.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ssh    # Ubuntu/Debian
sudo systemctl status ssh --no-pager
systemctl cat ssh
systemctl list-unit-files --type=service | head
journalctl -u ssh -b --no-pager -n 50
journalctl -p warning -b --no-pager
```

Пример нового файла `/etc/systemd/system/demo.service` для полной учебной ВМ:

```ini
[Unit]
Description=Demo teaching service
After=network.target

[Service]
Type=simple
User=trainee
ExecStart=/usr/bin/python3 -m http.server 8765 --directory /home/trainee
Restart=on-failure
NoNewPrivileges=yes

[Install]
WantedBy=multi-user.target
```

Создайте пользователя и каталог заранее. **Проверка:** `systemd-analyze verify /etc/systemd/system/demo.service`, затем `daemon-reload`, `start`, `status`, `journalctl -u demo.service`. Не открывайте такой тестовый порт в производственную сеть.

## 9. Пакеты APT, DPKG, DNF и RPM

APT работает с метаданными репозиториев и решает зависимости для deb-пакетов. `dpkg` — низкоуровневый инструмент управления установленными пакетами. В RHEL-совместимой системе `dnf` решает зависимости RPM, а `rpm` проверяет конкретные пакеты. Своевременное обновление безопасности отличается от необдуманного массового обновления в рабочий день.

```bash
# Ubuntu / Debian
sudo apt update
apt list --upgradable
apt-cache policy openssh-server
dpkg -l | grep openssh
apt-file search /usr/bin/команда  # Нужна отдельная установка apt-file

# AlmaLinux
sudo dnf check-update
sudo dnf info openssh-server
rpm -q openssh-server
rpm -ql openssh-server | head
sudo dnf history
```

**Диагностика:** ошибка «Unable to locate package» требует проверить имя, репозитории и индекс (`apt update`), а не скачивать случайный deb. Несовпадение версий пакетов может быть нормальным из-за backport исправлений в LTS-дистрибутивах.

## 10. Диски, разделы, LVM и файловые системы

Физический/виртуальный диск содержит таблицу разделов (GPT или MBR). Раздел может содержать ext4/xfs, swap, LUKS или физический том LVM. В LVM: PV → VG → LV → файловая система. Увеличение блочного устройства и расширение файловой системы — **два разных шага**. `fstab` задаёт монтирование при загрузке; ошибки там могут сорвать старт ОС.

```bash
lsblk -f
sudo blkid
findmnt -a
df -hT
du -sh /var/log
sudo pvs
sudo vgs
sudo lvs
cat /etc/fstab
```

На **отдельном тестовом диске без данных** можно отработать `pvcreate /dev/vdb`, `vgcreate labvg /dev/vdb`, `lvcreate -L 2G -n data labvg`, `mkfs.ext4 /dev/labvg/data`, монтирование по UUID. На некоторых ВМ имена устройств отличаются, поэтому никогда не копируйте `/dev/vdb` вслепую. Для расширения ext4 применяется `resize2fs`, для XFS `xfs_growfs` на точке монтирования. Сверьте руководство вашей файловой системы и сначала сделайте snapshot/backup.

## 11. Сеть: IP, маршруты, DNS, TCP и UDP

Для диагностики двигайтесь по уровням: интерфейс → IP/маска → маршрут → DNS → TCP/UDP → TLS → приложение. `ping` проверяет ICMP и может блокироваться политикой; удачный ping не доказывает работу веб-сервиса. `ip route get` показывает выбранный маршрут, `ss` локальные сокеты, `dig` DNS-ответ, `curl -v` HTTP/TLS.

```bash
ip -br link
ip -br addr
ip route
ip route get 1.1.1.1
ss -lntup
getent hosts example.org
resolvectl query example.org
curl -I --connect-timeout 3 https://example.org
```

**Различайте:** тайм-аут подключения, отказ TCP (`connection refused`), сбой DNS (`NXDOMAIN`/timeout), ошибку TLS-сертификата и HTTP 500/503. Это разные слои и требуют разных проверок. В учебном OCI-контейнере намеренно отключена сеть; эти действия запускайте в полноценной изолированной VM.

## 12. Конфигурация сети в разных семействах

Ubuntu Server часто использует Netplan, который формирует настройки для systemd-networkd или NetworkManager. Debian может применять ifupdown, NetworkManager либо systemd-networkd в зависимости от выбранного образа. AlmaLinux обычно использует NetworkManager и `nmcli`. Нельзя без проверки применять одну инструкцию к любому дистрибутиву.

```bash
# Ubuntu: изучите текущий YAML перед изменением
ls -l /etc/netplan/
sudo netplan generate
sudo netplan try

# Debian: определите фактический менеджер
systemctl is-active NetworkManager systemd-networkd
ls /etc/network/interfaces.d/

# AlmaLinux
nmcli con show
nmcli dev status
nmcli -f GENERAL,IP4 dev show
```

**Осторожно:** смена IP на сервере, к которому подключились только по SSH, может лишить доступа. Используйте виртуальную консоль гипервизора, снапшот и механизм автоматического отката (`netplan try` или собственную процедуру).

## 13. SSH: ключи, сервер и диагностика

SSH проверяет подлинность сервера с помощью host key, а пользователя — паролем или клиентским ключом. Приватный ключ никогда не копируйте на целевую машину. Правильные права каталога `.ssh` и файла `authorized_keys` существенны. В Ansible используйте отдельный ключ автоматизации и понятную политику `become`.

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_training -C training
ssh-copy-id -i ~/.ssh/id_ed25519_training.pub trainee@192.0.2.10
ssh -i ~/.ssh/id_ed25519_training -o IdentitiesOnly=yes trainee@192.0.2.10
ssh -vvv -i ~/.ssh/id_ed25519_training trainee@192.0.2.10
sudo sshd -t
```

**Разбор ошибок:** `Host key verification failed` означает конфликт доверия к серверному ключу, а `Permission denied (publickey)` — отказ в аутентификации пользователя. При изменении адреса/переустановке сначала проверьте **отпечаток нового серверного ключа через доверенный канал**, затем очищайте старую запись в `known_hosts` по известной причине; не отключайте проверку глобально.

## 14. Firewall, SELinux и AppArmor

В Ubuntu нередко применяется UFW как интерфейс к netfilter; в AlmaLinux — firewalld. SELinux управляет обязательным доступом через контексты и политики, AppArmor — через профили приложений. «Порт открыт» не гарантирует доступ: препятствием могут быть маршрут, ACL гипервизора, сервис, bind-address и локальная политика.

```bash
# Только в собственной полной VM!
sudo ufw status verbose
sudo firewall-cmd --state  # Для AlmaLinux с firewalld
sudo firewall-cmd --list-all
getenforce                 # Если установлен SELinux
sestatus
sudo aa-status             # Если установлен AppArmor
ss -lntp
```

**Не отключайте** SELinux, AppArmor и firewall целиком ради устранения непонятной ошибки. В AlmaLinux при отказе SELinux исследуйте `ausearch -m AVC -ts recent` и правильность контекста (`ls -Z`, `restorecon`) перед созданием новой политики. Для временного правила фиксируйте источник, назначение и срок действия.

## 15. Bash: безопасные скрипты

Скрипт должен быть воспроизводимым: валидировать входные аргументы, не распаковывать произвольные пути, разделять stdout/stderr, прерываться на ошибке и возвращать правильный код. `set -e` не заменяет явную проверку на сложных условных выражениях; `pipefail` помогает увидеть ошибки внутри pipe. С `trap` можно гарантировать удаление временного файла.

```bash
#!/usr/bin/env bash
set -Eeuo pipefail
if (( $# != 1 )); then
  printf 'Usage: %s OUTPUT_FILE\n' "$0" >&2
  exit 2
fi
out=$1
tmp=$(mktemp)
trap 'rm -f -- "$tmp"' EXIT
{
  printf 'host=%s\n' "$(hostname)"
  printf 'date=%s\n' "$(date -Is)"
  printf 'users=%s\n' "$(who | wc -l)"
} > "$tmp"
install -m 640 "$tmp" "$out"
```

**Проверка:** прогоните скрипт с отсутствующим аргументом, с путём содержащим пробелы, с недоступным каталогом назначения. Изучите `bash -n file.sh` и `shellcheck`, если он установлен.

## 16. Планировщики cron и systemd timers

`cron` выполняет задания по выражению расписания и обычно предоставляет ограниченное окружение. Переменная `PATH`, рабочая директория, часовой пояс и перенаправление ошибок могут отличаться от интерактивного терминала. Systemd timer дополняет расписание зависимостями и системными журналами. `OnCalendar` применяется для календарных событий, `Persistent=true` позволяет запускать пропущенную задачу после простоя при соответствующих условиях.

```bash
crontab -l
systemctl list-timers --all
systemd-analyze calendar 'Mon..Fri *-*-* 02:30:00'
journalctl -u cron -b  # Debian/Ubuntu, если установлен cron
```

**Проверка:** при отладке явно задавайте путь к исполняемым файлам, сохраняйте stdout/stderr и не считайте отсутствие письма с ошибкой признаком успешного выполнения.

## 17. Python и управление окружениями

Не устанавливайте прикладные Python-пакеты системным `pip` с `sudo` в управляемый пакетным менеджером Python. `venv` создаёт локальное окружение и отделяет зависимости. Фиксируйте версии, отслеживайте обновления безопасности и проверяйте, откуда устанавливаются пакеты.

```bash
python3 --version
python3 -m venv /workspace/pyenv
/workspace/pyenv/bin/python -m pip --version
/workspace/pyenv/bin/python -c 'import sys; print(sys.executable)'
python3 -m json.tool /workspace/report.json
```

**Диагностика:** `ModuleNotFoundError` часто означает, что запущен другой интерпретатор, чем тот, куда устанавливали пакет. Проверяйте точное расположение `python` и `pip`, а не повторяйте установку в разные каталоги.

## 18. Ansible от первого inventory до playbook

Ansible по SSH подключается к управляемым хостам, копирует/исполняет модули и возвращает структурированный результат. Управляющий узел требует Python/Ansible, на управляемых Linux-хостах обычно нужен Python и SSH. **Идемпотентность** означает, что повторный запуск не должен делать лишние изменения, если целевое состояние достигнуто.

```ini
# inventory.ini
[ubuntu]
testubuntu ansible_host=192.0.2.10 ansible_user=ansible

[debian]
testdebian ansible_host=192.0.2.11 ansible_user=ansible

[linux:children]
ubuntu
debian
```

```yaml
---
- name: Базовое состояние учебных серверов
  hosts: linux
  become: true
  gather_facts: true
  tasks:
    - name: Установить базовые пакеты
      ansible.builtin.apt:
        name:
          - curl
          - git
        state: present
        update_cache: true
      when: ansible_facts.os_family == 'Debian'

    - name: Создать каталог приложения
      ansible.builtin.file:
        path: /opt/training
        state: directory
        owner: root
        group: root
        mode: '0755'
```

```bash
ansible-inventory -i inventory.ini --graph
ansible -i inventory.ini linux -m ping
ansible-playbook -i inventory.ini base.yml --syntax-check
ansible-playbook -i inventory.ini base.yml --check --diff --ask-become-pass
ansible-playbook -i inventory.ini base.yml --ask-become-pass
```

**Диагностика ошибок:** `UNREACHABLE` обычно означает сеть/SSH/ключ/host key; `Missing sudo password` — права `become`; `Failed to parse module output as JSON` может означать мусор в stdout, повреждённый Python или неподдерживаемый интерпретатор; `No inventory parsed` — формат/путь inventory. Не назначайте всем хостам один пароль для удобства: используйте отдельные SSH-ключи, Ansible Vault или управляемое хранилище секретов. Не отключайте host key checking глобально.

## 19. Резервное копирование и восстановление

Определите RPO (допустимая потеря данных) и RTO (допустимое время восстановления), источники, retention, шифрование и владельца процедуры. `tar` удобен для файловых деревьев, `rsync` синхронизирует изменения, но простое копирование работающей базы данных может дать неконсистентный результат. Для PostgreSQL/MySQL/SQLite применяйте поддерживаемый механизм backup, а для целой ВМ — снапшот с учётом состояния приложений.

```bash
tar -czf /workspace/etc-backup.tar.gz -C /workspace demo
tar -tzf /workspace/etc-backup.tar.gz
sha256sum /workspace/etc-backup.tar.gz
mkdir -p /workspace/restore-test
tar -xzf /workspace/etc-backup.tar.gz -C /workspace/restore-test
diff -qr /workspace/demo /workspace/restore-test/demo
```

**Проверка:** автоматизируйте пробное восстановление в отдельной среде. Успешное создание архива не доказывает, что из него можно восстановить сервис с пользователями, правами и базой данных.

## 20. Диагностика инцидентов по шагам

Рабочая схема: **симптом → область отказа → воспроизведение → гипотеза → одна проверка → точечное исправление → подтверждение → журнал изменений**. Не перезапускайте всё подряд — это скрывает доказательства. До изменений сохраните журнал ошибок и время события.

```bash
date -Is
uptime
free -h
df -hT
systemctl --failed
journalctl -p err -b -n 100 --no-pager
ss -lntup
ip route
```

При `Permission denied` проверяйте `id`, `namei -l`, `stat`, `getfacl`, SELinux/AppArmor. При нехватке места сравните `df` и `du`: удалённый, но открытый процессом файл может занимать блоки, пока не закрыт файловый дескриптор (`lsof +L1`, если установлен). При `503` выясняйте, кто сформировал ответ — обратный прокси или backend. При зависании выключения смотрите `systemd-analyze blame`, `journalctl -b -1`, цепочки зависимостей и timeout; сохраните возможность восстановления VM из снапшота.

## 21. Минимальный аудит безопасности Linux

Регулярно проверяйте обновления, открытые TCP/UDP-порты, права привилегированных пользователей, устаревшие SSH-ключи, подозрительные unit-файлы и журналы отказов. Минимизируйте доступы, используйте индивидуальные учётные записи и отзывайте доступы при увольнении. Для систем с внешним доступом полезны централизованные логи и регулярное обновление уязвимых компонентов.

```bash
getent group sudo   # Debian/Ubuntu
getent group wheel  # AlmaLinux
sudo ss -lntup
sudo systemctl list-unit-files --state=enabled
sudo find /etc -type f -perm -0002 -print
sudo journalctl -u ssh -S '1 day ago' --no-pager
```

Команды аудита не должны менять конфигурацию. По результатам составьте отчёт: обнаружение, источник, степень риска, план точечного исправления, команда проверки после изменений и возможность отката.

## 22. Шпаргалка: какую команду выбрать

| Задача | Команда | Комментарий |
|---|---|---|
| Узнать систему | `cat /etc/os-release` | Версия user space |
| Узнать ядро | `uname -r` | В контейнере это ядро хоста |
| Справка | `man`, `--help`, `type` | `type` распознаёт shell builtins |
| Найти файл | `find /путь -type f -name '*.log'` | Маску заключайте в кавычки |
| Найти текст | `grep -R -n 'ERROR' /var/log` | Учитывайте большие и бинарные файлы |
| Доступ к файлу | `stat`, `namei -l`, `getfacl` | Проверяйте родительские каталоги |
| Список процессов | `ps aux`, `top`, `pgrep -af` | Проверяйте PID и пользователя |
| Диагностика службы | `systemctl status`, `journalctl -u` | Нужна полноценная ВМ |
| Диски | `lsblk -f`, `df -hT`, `du -sh` | Разные задачи |
| Сеть | `ip -br addr`, `ip route`, `ss -lntup` | Сетевые настройки — на ВМ |
| Проверка DNS | `getent hosts`, `resolvectl query` | Зависит от DNS-стека |
| Проверить HTTP | `curl -I`, `curl -v` | HTTP-код отличается от ошибки TCP |
| Debian/Ubuntu пакеты | `apt policy`, `dpkg -l` | Сверяйте репозитории |
| AlmaLinux пакеты | `dnf info`, `rpm -q` | RPM и DNF выполняют разные роли |
| Синтаксис Bash | `bash -n script.sh` | Не выполняет скрипт |
| Ansible inventory | `ansible-inventory --graph` | Запускайте с `-i` |
| Ansible playbook | `ansible-playbook --check --diff` | Check-mode зависит от модуля |

## 23. План самостоятельной практики

**Уровень 1 — новичок.** Вручную установите каждую из трёх ОС на отдельную ВМ, настройте SSH, создайте пользователя без root-login, разберитесь с каталогами, файлами, правами, процессами, пакетами и логами. Выполните разделы 1–5 в портале.

**Уровень 2 — системный администратор.** Настройте systemd unit, таймер, журналирование, HTTPS-демонстрацию, LVM на добавочном учебном диске и резервное копирование. Устройте учебную поломку разрешений и восстановите службу без переустановки ОС.

**Уровень 3 — автоматизация.** Сформируйте inventory из нескольких ВМ и поднимите SSH-доступ по ключам, напишите идемпотентный Ansible playbook, выполните `--check --diff`, разверните тестовый сервис и проверьте восстановление из резервной копии. Затем повторите сценарий на чистой VM без ручных изменений.

**Уровень 4 — эксплуатация.** Смоделируйте переполненный раздел, сломанные права, неправильный DNS, упавшую службу и задержку приложения. Составьте runbook, добавьте наблюдаемость и ограничьте привилегии. Сдавайте лаборатории только после объяснения **почему** выбранная команда устраняет причину.
