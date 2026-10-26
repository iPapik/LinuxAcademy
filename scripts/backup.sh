#!/usr/bin/env bash
set -euo pipefail
if (( EUID != 0 )); then echo 'sudo bash scripts/backup.sh'; exit 1; fi
OUT="${1:-/var/backups/linuxacademy}"
install -d -m 700 "$OUT"
STAMP=$(date +%F-%H%M%S)
DB="/var/lib/linuxacademy/data/academy.sqlite3"
if [[ ! -f "$DB" ]]; then echo "Нет базы $DB" >&2; exit 1; fi
python3 - "$DB" "$OUT/academy-$STAMP.sqlite3" <<'PY'
import sqlite3,sys
source=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True)
target=sqlite3.connect(sys.argv[2])
source.backup(target)
target.close();source.close()
PY
chmod 600 "$OUT/academy-$STAMP.sqlite3"
sha256sum "$OUT/academy-$STAMP.sqlite3" > "$OUT/academy-$STAMP.sha256"
chmod 600 "$OUT/academy-$STAMP.sha256"
echo "Бэкап SQLite: $OUT/academy-$STAMP.sqlite3"
echo 'Важно: содержимое учебных контейнеров в этот бэкап не входит.'
