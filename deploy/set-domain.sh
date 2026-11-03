#!/usr/bin/env bash
# Switch the server to a new public address, e.g. a sub-domain whose DNS A record points to
# this server's Elastic IP. Other names keep working via EXTRA_DOMAINS (space-separated).
#
#   sudo bash /opt/klicense/deploy/set-domain.sh license.karnexgroup.com [65-2-197-64.sslip.io]
#
# Checks that the name already resolves to this server, writes DOMAIN / EXTRA_DOMAINS into
# deploy/.env (old file kept as .env.before-domain-<date>), restarts web + api; Caddy gets the
# HTTPS certificate by itself (first request may take ~30 s).
set -euo pipefail
NEW=${1:?new domain}; EXTRA=${2:-}
cd "$(dirname "$0")"
F="docker compose -f docker-compose.rds.yml"; grep -q '^RDS_SECRET_ARN=' .env || F="docker compose -f docker-compose.yml"
MYIP=$(curl -s -H "X-aws-ec2-metadata-token: $(curl -s -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60')" http://169.254.169.254/latest/meta-data/public-ipv4 || true)
DNSIP=$(getent ahostsv4 "$NEW" | awk 'NR==1{print $1}' || true)
echo "server public IP: ${MYIP:-?}   $NEW resolves to: ${DNSIP:-nothing yet}"
if [ -z "$DNSIP" ] || { [ -n "$MYIP" ] && [ "$DNSIP" != "$MYIP" ]; }; then
  echo "DNS for $NEW does not point to this server yet - add an A record $NEW -> ${MYIP:-<Elastic IP>} and try again in a few minutes."
  exit 1
fi
cp -p .env ".env.before-domain-$(date +%Y%m%d-%H%M%S)"
python3 - "$NEW" "$EXTRA" <<'PY'
import re, sys
new, extra = sys.argv[1], sys.argv[2]
s = open('.env').read()
for k, v in (('DOMAIN', new), ('EXTRA_DOMAINS', extra)):
    if re.search(rf'(?m)^{k}=', s): s = re.sub(rf'(?m)^{k}=.*$', lambda m: f'{k}={v}', s)
    else: s = s.rstrip('\n') + f'\n{k}={v}\n'
open('.env', 'w').write(s)
PY
chmod 600 .env
$F up -d --force-recreate web api
sleep 20
for d in $NEW $EXTRA; do printf '%s -> ' "$d"; curl -sS -m 30 "https://$d/health/db" || echo "(certificate may need another minute)"; echo; done
echo "Portal: https://$NEW    Apps' server address: https://$NEW/api/v1"
