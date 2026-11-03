#!/usr/bin/env bash
# Creates the whole K License Center production setup in AWS — run it in AWS CloudShell
# (console top bar, >_ icon), region ap-south-1:
#
#   curl -fsSL https://raw.githubusercontent.com/aadityapa/k-license-center/main/deploy/aws-create.sh | bash
#
# Creates (re-uses what already exists, by name):
#   security groups  klicense-ec2-sg (22/80/443) and klicense-rds-sg (5432 only from the EC2)
#   IAM role         klicense-ec2-role (SSM agent + read of the RDS password secret)
#   RDS PostgreSQL   klicense-db  db.t4g.micro, 20 GB gp3, encrypted, private, 7-day backups,
#                    master password generated and kept in Secrets Manager (nobody types it)
#   EC2              klicense  t3.small Ubuntu 24.04, 30 GB gp3 encrypted
#   Elastic IP       attached to the EC2 → address <ip-with-dashes>.sslip.io (HTTPS)
# then runs deploy/bootstrap-aws.sh on the EC2 through SSM and prints the portal address
# and the generated admin password.
set -euo pipefail
export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION:-ap-south-1}
NAME=klicense
ACME_EMAIL=${ACME_EMAIL:-karan.singh@karnex.in}
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
say() { echo; echo "== $*"; }

say "network"
VPC=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
sg() {  # name description -> id (create if missing)
  local id
  id=$(aws ec2 describe-security-groups --filters Name=group-name,Values="$1" Name=vpc-id,Values="$VPC" --query 'SecurityGroups[0].GroupId' --output text)
  if [ "$id" = "None" ]; then
    id=$(aws ec2 create-security-group --group-name "$1" --description "$2" --vpc-id "$VPC" --query GroupId --output text)
  fi
  echo "$id"
}
SG_EC2=$(sg ${NAME}-ec2-sg "K License Center web server")
SG_RDS=$(sg ${NAME}-rds-sg "K License Center database")
for p in 22 80 443; do
  aws ec2 authorize-security-group-ingress --group-id "$SG_EC2" --protocol tcp --port $p --cidr 0.0.0.0/0 >/dev/null 2>&1 || true
done
aws ec2 authorize-security-group-ingress --group-id "$SG_EC2" --protocol udp --port 443 --cidr 0.0.0.0/0 >/dev/null 2>&1 || true
aws ec2 authorize-security-group-ingress --group-id "$SG_RDS" --protocol tcp --port 5432 --source-group "$SG_EC2" >/dev/null 2>&1 || true
echo "   $SG_EC2 (web)  $SG_RDS (db)"

say "IAM role for the server"
ROLE=${NAME}-ec2-role
if ! aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE" --assume-role-policy-document \
    '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
  aws iam attach-role-policy --role-name "$ROLE" --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
  aws iam put-role-policy --role-name "$ROLE" --policy-name read-rds-secret --policy-document \
    "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"secretsmanager:GetSecretValue\",\"Resource\":\"arn:aws:secretsmanager:${AWS_DEFAULT_REGION}:${ACCOUNT}:secret:rds!*\"}]}"
  aws iam create-instance-profile --instance-profile-name "$ROLE" >/dev/null
  aws iam add-role-to-instance-profile --instance-profile-name "$ROLE" --role-name "$ROLE"
  sleep 15   # let IAM propagate before EC2 uses the profile
fi

say "database (RDS PostgreSQL) — takes 5-10 minutes"
DB=${NAME}-db
if ! aws rds describe-db-instances --db-instance-identifier "$DB" >/dev/null 2>&1; then
  aws rds create-db-instance --db-instance-identifier "$DB" --engine postgres \
    --db-instance-class db.t4g.micro --allocated-storage 20 --storage-type gp3 --storage-encrypted \
    --master-username klicense_admin --manage-master-user-password --db-name klicense \
    --vpc-security-group-ids "$SG_RDS" --no-publicly-accessible \
    --backup-retention-period 7 --deletion-protection --copy-tags-to-snapshot \
    --tags Key=Name,Value=$DB >/dev/null
fi

say "server (EC2)"
IID=$(aws ec2 describe-instances --filters Name=tag:Name,Values=$NAME Name=instance-state-name,Values=pending,running,stopped \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)
if [ "$IID" = "None" ]; then
  AMI=$(aws ssm get-parameter --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id --query Parameter.Value --output text)
  IID=$(aws ec2 run-instances --image-id "$AMI" --instance-type t3.small \
    --security-group-ids "$SG_EC2" --iam-instance-profile Name="$ROLE" \
    --metadata-options HttpTokens=required,HttpEndpoint=enabled \
    --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":30,"VolumeType":"gp3","Encrypted":true}}]' \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME}]" \
    --query 'Instances[0].InstanceId' --output text)
fi
aws ec2 wait instance-running --instance-ids "$IID"
echo "   $IID running"

say "fixed public address (Elastic IP)"
EIP=$(aws ec2 describe-addresses --filters Name=tag:Name,Values=$NAME --query 'Addresses[0].PublicIp' --output text)
if [ "$EIP" = "None" ]; then
  ALLOC=$(aws ec2 allocate-address --domain vpc --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=$NAME}]" --query AllocationId --output text)
  EIP=$(aws ec2 describe-addresses --allocation-ids "$ALLOC" --query 'Addresses[0].PublicIp' --output text)
else
  ALLOC=$(aws ec2 describe-addresses --filters Name=tag:Name,Values=$NAME --query 'Addresses[0].AllocationId' --output text)
fi
aws ec2 associate-address --instance-id "$IID" --allocation-id "$ALLOC" >/dev/null
DOMAIN="$(echo "$EIP" | tr . -).sslip.io"
echo "   $EIP  ->  https://$DOMAIN"

say "waiting for the database"
aws rds wait db-instance-available --db-instance-identifier "$DB"
RDS_HOST=$(aws rds describe-db-instances --db-instance-identifier "$DB" --query 'DBInstances[0].Endpoint.Address' --output text)
SECRET_ARN=$(aws rds describe-db-instances --db-instance-identifier "$DB" --query 'DBInstances[0].MasterUserSecret.SecretArn' --output text)
echo "   $RDS_HOST"

say "waiting for the server's SSM agent"
for i in $(seq 1 60); do
  [ "$(aws ssm describe-instance-information --filters Key=InstanceIds,Values=$IID --query 'InstanceInformationList[0].PingStatus' --output text)" = "Online" ] && break
  sleep 10
done

say "installing the K License Center on the server (10-15 minutes)"
CMD="curl -fsSL https://raw.githubusercontent.com/aadityapa/k-license-center/main/deploy/bootstrap-aws.sh | bash -s -- $DOMAIN $RDS_HOST '$SECRET_ARN' $ACME_EMAIL"
CID=$(aws ssm send-command --instance-ids "$IID" --document-name AWS-RunShellScript --timeout-seconds 3600 \
  --parameters "{\"commands\":[\"$CMD\"],\"executionTimeout\":[\"3600\"]}" --comment "K License Center bootstrap" \
  --query Command.CommandId --output text)
while true; do
  ST=$(aws ssm get-command-invocation --command-id "$CID" --instance-id "$IID" --query Status --output text 2>/dev/null || echo Pending)
  case "$ST" in Success|Failed|Cancelled|TimedOut) break;; esac
  sleep 20; echo -n "."
done
echo
aws ssm get-command-invocation --command-id "$CID" --instance-id "$IID" --query StandardOutputContent --output text | tail -25
[ "$ST" = "Success" ] || { echo "Bootstrap $ST:"; aws ssm get-command-invocation --command-id "$CID" --instance-id "$IID" --query StandardErrorContent --output text | tail -25; }

say "done"
echo "Server: $IID   IP: $EIP   DB: $RDS_HOST"
echo "Portal: https://$DOMAIN    Apps' server address: https://$DOMAIN/api/v1"
