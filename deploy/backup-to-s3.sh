#!/usr/bin/env bash
# Copies the daily database dumps (deploy/backups) to S3. Run from cron on the server:
#   crontab -e   ->   30 3 * * * /home/ubuntu/klicense/deploy/backup-to-s3.sh s3://karnex-klicense-backups >> /home/ubuntu/backup-s3.log 2>&1
# The EC2 instance needs an IAM role allowing s3:PutObject / s3:ListBucket on that bucket.
set -euo pipefail
BUCKET=${1:?usage: backup-to-s3.sh s3://bucket-name}
cd "$(dirname "$0")"
aws s3 sync ./backups "$BUCKET/klicense/" --exclude "*.part" --only-show-errors
echo "$(date -Is) synced to $BUCKET"
