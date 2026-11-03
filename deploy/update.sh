#!/usr/bin/env bash
# Update the K License Center on the server to the latest code from Git.
#   cd ~/klicense/deploy && ./update.sh
# Pulls the code, rebuilds the images and restarts. The database is migrated automatically
# when the API starts; data, certificates and backups are kept (Docker volumes / deploy/backups).
set -euo pipefail
cd "$(dirname "$0")"
git -C .. pull --ff-only
docker compose build
docker compose up -d
docker compose ps
sleep 5
curl -fsS "https://$(grep -E '^DOMAIN=' .env | cut -d= -f2)/health/db" && echo
