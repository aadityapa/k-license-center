#!/usr/bin/env bash
# Restores a database dump made by the backup service (OVERWRITES the current data).
#   ./restore.sh backups/klicense-20261029-0300.dump
set -euo pipefail
cd "$(dirname "$0")"
DUMP=${1:?usage: restore.sh backups/klicense-YYYYMMDD-HHMM.dump}
[ -f "$DUMP" ] || { echo "not found: $DUMP"; exit 1; }
read -r -p "This replaces ALL licence data with $DUMP. Type RESTORE to continue: " ok
[ "$ok" = "RESTORE" ] || { echo "cancelled"; exit 1; }
docker compose stop api
docker compose exec -T db pg_restore -U klicense -d klicense --clean --if-exists --no-owner < "$DUMP"
docker compose start api
echo "Restored. Check: curl -s https://\$DOMAIN/health/db"
