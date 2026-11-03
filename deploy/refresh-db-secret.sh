#!/usr/bin/env bash
# RDS keeps the database password in AWS Secrets Manager and rotates it (every 7 days by default).
# Run hourly by cron (installed by bootstrap-aws.sh): when the password changed, write it to
# deploy/.env and restart the API so it reconnects with the new one.
set -euo pipefail
cd "$(dirname "$0")"
ARN=$(grep -E '^RDS_SECRET_ARN=' .env | cut -d= -f2-)
[ -n "$ARN" ] || exit 0
REGION=$(echo "$ARN" | cut -d: -f4)
NEW=$(aws secretsmanager get-secret-value --region "$REGION" --secret-id "$ARN" --query SecretString --output text \
      | python3 -c 'import json,sys;print(json.load(sys.stdin)["password"])')
OLD=$(grep -E '^DB_PASSWORD=' .env | cut -d= -f2-)
if [ "$NEW" != "$OLD" ]; then
  python3 - "$NEW" <<'PY'
import sys,re
p='.env'; s=open(p).read(); s=re.sub(r'(?m)^DB_PASSWORD=.*$', lambda m: 'DB_PASSWORD='+sys.argv[1], s); open(p,'w').write(s)
PY
  docker compose -f docker-compose.rds.yml up -d --force-recreate api
  logger -t klicense "database password rotated - API restarted"
fi
