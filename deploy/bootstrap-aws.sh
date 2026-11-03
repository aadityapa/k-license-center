#!/usr/bin/env bash
# One-shot setup of the K License Center on a fresh Ubuntu EC2 with the database on Amazon RDS.
#
#   curl -fsSL https://raw.githubusercontent.com/aadityapa/k-license-center/main/deploy/bootstrap-aws.sh \
#     | sudo bash -s -- <DOMAIN> <RDS_ENDPOINT> <RDS_SECRET_ARN> [ACME_EMAIL]
#
#   DOMAIN          e.g. 13-233-10-20.sslip.io (or your own domain pointing to the Elastic IP)
#   RDS_ENDPOINT    e.g. klicense-db.abc123.ap-south-1.rds.amazonaws.com
#   RDS_SECRET_ARN  the RDS master-credentials secret in AWS Secrets Manager
#                   (the EC2 instance role must allow secretsmanager:GetSecretValue on it)
#
# It installs Docker, clones the code, writes deploy/.env (random JWT secret, new signing keys,
# DB credentials read from Secrets Manager — no password is typed anywhere), prepares the
# database (tables + a generated admin password; maker/checker/viewer locked) and starts
# the portal + API with automatic HTTPS. Safe to re-run: existing .env / keys are kept.
set -euo pipefail
DOMAIN=${1:?DOMAIN}; RDS_HOST=${2:?RDS endpoint}; SECRET_ARN=${3:?RDS secret ARN}; ACME_EMAIL=${4:-}
REPO=https://github.com/aadityapa/k-license-center.git
DIR=/opt/klicense
REGION=$(curl -s -H "X-aws-ec2-metadata-token: $(curl -s -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60')" http://169.254.169.254/latest/meta-data/placement/region || echo ap-south-1)

echo "== 1/6 base setup (Docker, firewall, swap, clock)"
export DEBIAN_FRONTEND=noninteractive
command -v cloud-init >/dev/null && cloud-init status --wait >/dev/null 2>&1 || true
# first boot: wait until unattended-upgrades releases the package lock
for i in $(seq 1 60); do fuser /var/lib/dpkg/lock-frontend /var/lib/apt/lists/lock >/dev/null 2>&1 || break; sleep 10; done
if ! command -v docker >/dev/null; then
  curl -fsSL "https://raw.githubusercontent.com/aadityapa/k-license-center/main/deploy/server-setup.sh" | bash
fi
command -v aws >/dev/null || snap install aws-cli --classic

echo "== 2/6 code"
if [ -d "$DIR/.git" ]; then git -C "$DIR" pull --ff-only; else git clone "$REPO" "$DIR"; fi
cd "$DIR/deploy"
COMPOSE="docker compose -f docker-compose.rds.yml"

echo "== 3/6 database credentials (Secrets Manager)"
SECRET=$(aws secretsmanager get-secret-value --region "$REGION" --secret-id "$SECRET_ARN" --query SecretString --output text)
DB_USER=$(python3 -c 'import json,sys;print(json.loads(sys.argv[1])["username"])' "$SECRET")
DB_PASS=$(python3 -c 'import json,sys;print(json.loads(sys.argv[1])["password"])' "$SECRET")

echo "== 4/6 settings (deploy/.env)"
if [ ! -f .env ]; then
  JWT=$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')
  umask 077
  cat > .env <<EOF
DOMAIN=$DOMAIN
ACME_EMAIL=$ACME_EMAIL
ADMIN_ALLOW_CIDRS=0.0.0.0/0 ::/0
TZ=Asia/Kolkata
DB_HOST=$RDS_HOST
DB_PORT=5432
DB_NAME=klicense
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASS
DB_SSL=true
DB_SSL_REJECT_UNAUTHORIZED=false
DB_TIMEZONE=Asia/Kolkata
JWT_SECRET=$JWT
JWT_EXPIRES_IN=8h
LOG_LEVEL=info
AUTH_DISABLED=false
RDS_SECRET_ARN=$SECRET_ARN
EOF
else
  # keep keys / JWT; refresh address and DB password (Secrets Manager may rotate it)
  sed -i "s|^DOMAIN=.*|DOMAIN=$DOMAIN|; s|^DB_HOST=.*|DB_HOST=$RDS_HOST|; s|^DB_USER=.*|DB_USER=$DB_USER|" .env
  python3 - "$DB_PASS" <<'PY'
import sys,re
p='.env'; s=open(p).read(); s=re.sub(r'(?m)^DB_PASSWORD=.*$', lambda m: 'DB_PASSWORD='+sys.argv[1], s); open(p,'w').write(s)
PY
fi
chmod 600 .env

echo "== 5/6 build images, signing keys"
$COMPOSE build
if ! grep -q '^VBS_SIGNING_KEY=.\+' .env; then
  $COMPOSE run --rm --no-deps -e NODE_ENV=development api python -m scripts.keygen \
    | grep -E '^(LICENCE|VBS)_SIGNING_KEY=' >> .env
  echo "   new signing keys written to deploy/.env (back this file up!)"
fi

echo "== 6/6 database tables + admin account, start"
CRED=/root/klicense-admin.txt
if [ ! -f "$CRED" ]; then
  ADMINPW="Kl$(python3 -c 'import secrets;print(secrets.token_urlsafe(12))')#7"
  if $COMPOSE run --rm -e INIT_ADMIN_PASSWORD="$ADMINPW" api python -m scripts.prod_init </dev/null; then
    umask 077; printf 'Portal: https://%s\nUser:   admin\nPassword: %s\n' "$DOMAIN" "$ADMINPW" > "$CRED"
  fi
else
  $COMPOSE run --rm api python -m scripts.prod_init </dev/null || true
fi
$COMPOSE up -d
# RDS rotates the DB password in Secrets Manager: pick up a new one every hour
printf '#!/bin/sh\n%s/deploy/refresh-db-secret.sh\n' "$DIR" > /etc/cron.hourly/klicense-db-secret
chmod +x /etc/cron.hourly/klicense-db-secret "$DIR/deploy/refresh-db-secret.sh"
sleep 20
curl -fsS "https://$DOMAIN/health/db" && echo || echo "(HTTPS certificate may need another minute: curl https://$DOMAIN/health/db)"
echo
echo "================ K License Center is running ================"
cat "$CRED" 2>/dev/null || true
echo "Change the admin password after the first sign-in. Credentials file: $CRED (root only)."
