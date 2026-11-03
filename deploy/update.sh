#!/usr/bin/env bash
# Update the Karnex License Center on the server to the latest code from Git.
#   cd ~/klicense/deploy && ./update.sh
# Pulls the code, rebuilds the images and restarts. The database is migrated automatically
# when the API starts; data, certificates and backups are kept (Docker volumes / deploy/backups).
set -euo pipefail
cd "$(dirname "$0")"
git -C .. pull --ff-only
# Database on Amazon RDS (bootstrap-aws.sh) or in a local container (docker-compose.yml)?
if grep -q '^RDS_SECRET_ARN=' .env 2>/dev/null; then F=docker-compose.rds.yml; else F=docker-compose.yml; fi
docker compose -f "$F" build
docker compose -f "$F" up -d
docker compose -f "$F" ps
sleep 5
curl -fsS "https://$(grep -E '^DOMAIN=' .env | cut -d= -f2)/health/db" && echo
