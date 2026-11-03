#!/usr/bin/env bash
# Move the Karnex License Center to a NEW (empty) RDS database, built cleanly from the current code,
# with the data copied from a pg_dump custom-format file.
#
#   sudo bash /opt/klicense/deploy/switch-to-new-rds.sh <NEW_RDS_ENDPOINT> <NEW_RDS_SECRET_ARN> [dump]
#
#   dump  default /root/klicense-import.dump (left there by restore-dump.sh)
#
# 1. reads the new master credentials from Secrets Manager (EC2 role allows rds!* secrets)
# 2. builds all tables/functions with the CURRENT migrations (001…)          → no "changed migration"
# 3. empties the seed rows, copies ONLY the data from the dump (not schema_migrations)
# 4. re-runs the 009 clean-up on the copied data, shows row counts
# 5. points deploy/.env at the new database (old .env kept as .env.before-<date>), production safety
#    (demo API clients revoked, default passwords replaced/locked), restarts the API
# The old RDS database is not touched — to go back: restore the .env.before-* file and `up -d`.
set -euo pipefail
NEW_HOST=${1:?new RDS endpoint}; NEW_ARN=${2:?new RDS secret ARN}; DUMP=${3:-/root/klicense-import.dump}
cd /opt/klicense/deploy
COMPOSE="docker compose -f docker-compose.rds.yml"
val() { grep -E "^$1=" .env | head -1 | cut -d= -f2-; }
REGION=$(echo "$NEW_ARN" | cut -d: -f4)

echo "== 1/5 new database credentials"
SECRET=$(aws secretsmanager get-secret-value --region "$REGION" --secret-id "$NEW_ARN" --query SecretString --output text)
NEW_USER=$(python3 -c 'import json,sys;print(json.loads(sys.argv[1])["username"])' "$SECRET")
NEW_PASS=$(python3 -c 'import json,sys;print(json.loads(sys.argv[1])["password"])' "$SECRET")
export PGPASSWORD="$NEW_PASS" PGSSLMODE=require
pg() { docker run --rm -e PGPASSWORD -e PGSSLMODE -e PGOPTIONS -v /root:/root -v /opt/klicense:/opt/klicense postgres:18 "$@"; }
psqlc() { pg psql -h "$NEW_HOST" -U "$NEW_USER" -d klicense -v ON_ERROR_STOP=1 -At "$@"; }
head -c 5 "$DUMP" | grep -q PGDMP || { echo "$DUMP is not a pg_dump custom-format file"; exit 1; }
if [ "$(psqlc -c "SELECT to_regclass('public.licenses') IS NOT NULL")" = "t" ] && \
   [ "$(psqlc -c "SELECT count(*) FROM licenses")" != "0" ]; then
  echo "The new database already holds licences — stopping (nothing changed)."; exit 1
fi
echo "   $NEW_HOST reachable as $NEW_USER"

echo "== 2/5 tables from the current code"
$COMPOSE run --rm -T -e DB_HOST="$NEW_HOST" -e DB_USER="$NEW_USER" -e DB_PASSWORD="$NEW_PASS" -e DB_NAME=klicense \
  api python -m scripts.db_migrate </dev/null

echo "== 3/5 copy the data"
psqlc -c "DO \$\$ DECLARE t text; BEGIN
  SELECT string_agg(format('%I', tablename), ', ') INTO t FROM pg_tables
   WHERE schemaname = 'public' AND tablename <> 'schema_migrations';
  EXECUTE 'TRUNCATE ' || t || ' RESTART IDENTITY CASCADE'; END \$\$;"
pg pg_restore -l "$DUMP" | grep -E 'TABLE DATA public |SEQUENCE SET public ' | grep -v ' schema_migrations ' > /root/klicense-data.list
PGOPTIONS='-c session_replication_role=replica' \
  pg pg_restore -h "$NEW_HOST" -U "$NEW_USER" -d klicense --data-only --no-owner --no-acl --exit-on-error \
     -L /root/klicense-data.list "$DUMP"
unset PGOPTIONS

echo "== 4/5 clean-up and check"
psqlc -f /opt/klicense/database/postgres/009_no_temp_key_for_signed_products.sql >/dev/null
# identity columns: continue numbering after the copied rows
psqlc -c "DO \$\$ DECLARE r record; m bigint; BEGIN
  FOR r IN SELECT c.table_name, c.column_name FROM information_schema.columns c
            WHERE c.table_schema = 'public' AND c.is_identity = 'YES' LOOP
    EXECUTE format('SELECT max(%I) FROM %I', r.column_name, r.table_name) INTO m;
    IF m IS NOT NULL THEN
      EXECUTE format('SELECT setval(pg_get_serial_sequence(%L, %L), %s)', r.table_name, r.column_name, m);
    END IF;
  END LOOP; END \$\$;"
echo "   rows: $(psqlc -c "SELECT 'products '||(SELECT count(*) FROM products)||', customers '||(SELECT count(*) FROM customers)||', licences '||(SELECT count(*) FROM licenses)||', keys '||(SELECT count(*) FROM license_keys)||', users '||(SELECT count(*) FROM users)||', audit '||(SELECT count(*) FROM audit_logs)")"
echo "   migrations: $(psqlc -c "SELECT string_agg(left(filename,3), ' ' ORDER BY filename) FROM schema_migrations")"

echo "== 5/5 switch the server to the new database"
STAMP=$(date +%Y%m%d-%H%M%S)
cp -p .env ".env.before-$STAMP"
python3 - "$NEW_HOST" "$NEW_USER" "$NEW_PASS" "$NEW_ARN" <<'PY'
import re, sys
host, user, pw, arn = sys.argv[1:5]
p = '.env'; s = open(p).read()
for k, v in (('DB_HOST', host), ('DB_USER', user), ('DB_PASSWORD', pw), ('RDS_SECRET_ARN', arn), ('DB_NAME', 'klicense')):
    if re.search(rf'(?m)^{k}=', s):
        s = re.sub(rf'(?m)^{k}=.*$', lambda m: f'{k}={v}', s)
    else:
        s += f'\n{k}={v}\n'
open(p, 'w').write(s)
PY
chmod 600 .env ".env.before-$STAMP"
$COMPOSE stop api
psqlc -c "UPDATE api_clients SET status = 'REVOKED' WHERE client_key LIKE 'demo-%' AND status = 'ACTIVE' RETURNING client_key;" \
  | sed 's/^/   demo API client revoked: /'
ADMINPW=$(sed -n 's/^Password: //p' /root/klicense-admin.txt 2>/dev/null || true)
$COMPOSE run --rm -T ${ADMINPW:+-e INIT_ADMIN_PASSWORD="$ADMINPW"} api python -m scripts.prod_init </dev/null || true
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
$COMPOSE up -d
sleep 8
curl -fsS "https://$(val DOMAIN)/health/db" && echo
echo "Done. The server now uses $NEW_HOST. Previous settings: deploy/.env.before-$STAMP"
