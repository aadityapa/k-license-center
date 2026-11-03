#!/usr/bin/env bash
# One-time preparation of a fresh Ubuntu 22.04 / 24.04 EC2 server for the K License Center.
#   sudo bash server-setup.sh
# Installs Docker + compose plugin, turns on automatic security updates, a 2 GB swap file
# (small instances), the firewall (22/80/443) and checks the clock sync (the server's clock
# is the licence time reference — D12).
set -euo pipefail

if [ "$(id -u)" != "0" ]; then echo "run with sudo"; exit 1; fi

echo "== packages"
apt-get update -y
apt-get install -y ca-certificates curl gnupg ufw unattended-upgrades chrony awscli || apt-get install -y ca-certificates curl gnupg ufw unattended-upgrades chrony

echo "== docker"
if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker
usermod -aG docker "${SUDO_USER:-ubuntu}" || true

echo "== automatic security updates"
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "== swap (2 GB)"
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "== firewall"
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

echo "== clock (Amazon Time Sync 169.254.169.123)"
if ! grep -q 169.254.169.123 /etc/chrony/chrony.conf; then
  sed -i '1i server 169.254.169.123 prefer iburst minpoll 4 maxpoll 4' /etc/chrony/chrony.conf
  systemctl restart chrony
fi
timedatectl set-timezone Asia/Kolkata || true
chronyc tracking | head -4 || true

echo
echo "Done. Log out and in again (docker group), then follow AWS-DEPLOY.md step 4."
