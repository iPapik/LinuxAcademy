# Основные источники и методика LinuxAcademy

Это список официальных и профильных руководств, сверенных при подготовке новых учебных тем. Контент LinuxAcademy написан самостоятельно по-русски. Книги и онлайн-справочники не копируются целиком и не являются частью поставки: на них могут распространяться отдельные условия использования.

## Базовые понятия
- Filesystem Hierarchy Standard 3.0 — https://specifications.freedesktop.org/fhs/latest/
- Debian Reference (включая GNU/Linux tutorials, packages и system administration) — https://www.debian.org/doc/manuals/debian-reference/
- Linux man-pages — https://man7.org/linux/man-pages/
- GNU Coreutils Manual — https://www.gnu.org/software/coreutils/manual/

## Debian / Ubuntu
- Debian Administrator's Handbook — https://debian-handbook.info/
- Debian Reference — https://www.debian.org/doc/manuals/debian-reference/
- Ubuntu Server documentation — https://documentation.ubuntu.com/server/

## RHEL / AlmaLinux / Fedora
- Red Hat Enterprise Linux: Configuring basic system settings — https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/configuring_basic_system_settings/
- Red Hat Enterprise Linux: Managing file systems — https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/managing_file_systems/
- Fedora documentation — https://docs.fedoraproject.org/

## Arch / openSUSE / Alpine / Gentoo / NixOS
- ArchWiki, pacman — https://wiki.archlinux.org/title/Pacman
- Arch Linux official images — https://archlinux.org/download/
- openSUSE Zypper reference — https://doc.opensuse.org/documentation/tumbleweed/zypper/
- Alpine Linux documentation — https://wiki.alpinelinux.org/
- Gentoo Handbook — https://wiki.gentoo.org/wiki/Handbook:Main_Page
- NixOS Manual — https://nixos.org/manual/nixos/stable/

## Порядок изучения
1. Нулевой курс: ОС, файлы, файловая система, пути, каталоги, права, ссылки, переменные, процессы.
2. Исходный фундаментальный курс: работа с пакетами, пользователями, службами, сетью, журналами, Bash.
3. Сравнение систем: менеджеры пакетов и особенности семейств Linux.
4. Работа с хранилищем и восстановлением: ext4, XFS, Btrfs, mount, fstab, LVM, ACL, резервные копии.
5. Углублённые старые модули: автоматизация, Ansible, диагностика инцидентов.

## Ограничения лаборатории
Контейнеры разделяют ядро с сервером. Практика systemd как PID 1, GRUB, реальных файловых систем, блочных устройств, прошивки, SELinux в полном режиме и сетевого firewall выполняется в отдельных полноценных VM. Материалы по Gentoo, NixOS, Mint, Rocky и другим ОС доступны как теория; наличие теории не означает автоматической установки соответствующей VM.
