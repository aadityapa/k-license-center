#!/usr/bin/env bash
# Replace the production database (Amazon RDS) with the data from a pg_dump custom-format file,
# e.g. a dump of the local `klicense` database made with pgAdmin (Backup → Format: Custom).
#
#   sudo bash /opt/klicense/deploy/restore-dump.sh <https-download-link | /path/to/file.dump>
#
# Steps: download + check the file → back up the CURRENT database to /root/klicense-before-import-*.dump
# → stop the API → empty the database → pg_restore → make it production-safe (demo API clients
# revoked; accounts on the published default password get a new password / are locked; the admin
# password stays the one in /root/klicense-admin.txt if the dump's admin used the default) → start.
# Undo: run this script again with the /root/klicense-before-import-*.dump file.
set -euo pipefail
SRC=${1:?usage: restore-dump.sh <download link or file>}
cd /opt/klicense/deploy
COMPOSE="docker compose -f docker-compose.rds.yml"
val() { grep -E "^$1=" .env | head -1 | cut -d= -f2-; }
DB_HOST=$(val DB_HOST); DB_USER=$(val DB_USER); DB_NAME=$(val DB_NAME); DB_NAME=${DB_NAME:-klicense}
export PGPASSWORD="$(val DB_PASSWORD)" PGSSLMODE=require
pg() { docker run --rm -e PGPASSWORD -e PGSSLMODE -v /root:/root postgres:18 "$@"; }
psqlc() { pg psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -At "$@"; }

echo "== 1/6 dump file"
DUMP=/root/klicense-import.dump
case "$SRC" in
  http://*|https://*) curl -fsSL -o "$DUMP" "$SRC" ;;
  *) [ "$SRC" = "$DUMP" ] || cp "$SRC" "$DUMP" ;;
esac
head -c 5 "$DUMP" | grep -q PGDMP || { echo "Not a pg_dump custom-format file."; exit 1; }
pg pg_restore -l "$DUMP" >/dev/null
echo "   $(stat -c %s "$DUMP") bytes, readable"

echo "== 2/6 backup of the current database"
STAMP=$(date +%Y%m%d-%H%M%S)
pg pg_dump -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -Fc -f "/root/klicense-before-import-$STAMP.dump"
chmod 600 /root/klicense-*.dump
echo "   /root/klicense-before-import-$STAMP.dump"

echo "== 3/6 stop the API, empty the database"
$COMPOSE stop api
psqlc -c "DROP SCHEMA IF EXISTS pkg_audit, pkg_license_key, pkg_license, pkg_authorization, pkg_renewal CASCADE;
          DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;"

echo "== 4/6 restore"
set +e
pg pg_restore -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" --no-owner --no-acl "$DUMP" 2>&1 \
  | grep -v -E 'schema "public" already exists|errors ignored on restore' | tail -20
set -e
echo "   rows: $(psqlc -c "SELECT 'products '||(SELECT count(*) FROM products)||', customers '||(SELECT count(*) FROM customers)||', licences '||(SELECT count(*) FROM licenses)||', keys '||(SELECT count(*) FROM license_keys)||', users '||(SELECT count(*) FROM users)")"

echo "== 5/6 production safety"
psqlc -c "UPDATE api_clients SET status = 'REVOKED' WHERE client_key LIKE 'demo-%' AND status = 'ACTIVE' RETURNING client_key;" \
  | sed 's/^/   demo API client revoked: /'
ADMINPW=$(sed -n 's/^Password: //p' /root/klicense-admin.txt 2>/dev/null || true)
$COMPOSE run --rm -T ${ADMINPW:+-e INIT_ADMIN_PASSWORD="$ADMINPW"} api python -m scripts.prod_init </dev/null || true
# other (non-starter) accounts still on a published default password: lock them
$COMPOSE run --rm -T api python - </dev/null <<'PY' || true
from app.db import connect_raw
from app.services.prod_guard import accounts_on_default_password
c = connect_raw()
left = [u for u in accounts_on_default_password(c) if u != "admin"]
with c.cursor() as cur:
    for u in left:
        cur.execute("UPDATE users SET status = 'LOCKED', updated_at = now() WHERE username = %s", (u,))
        print(f"   '{u}' was on the default password: locked (unlock in Users → Edit)")
c.commit()
PY

echo "== 6/6 start"
$COMPOSE up -d
sleep 8
curl -fsS "https://$(val DOMAIN)/health/db" && echo
echo "Done. Previous data: /root/klicense-before-import-$STAMP.dump"
