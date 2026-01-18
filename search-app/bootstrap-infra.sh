#!/usr/bin/env bash
set -euo pipefail

# Bootstrap SpacesAI dependencies on Oracle Linux 10 (or compatible)
# This script mirrors the Terraform cloud-init steps with sudo prefixes.
# Usage:
#   APP_PORT=8000 REPO_URL=https://github.com/shadabshaukat/spaces-ai.git TARGET_USER=opc ./bootstrap-infra.sh

APP_PORT=${APP_PORT:-8000}
REPO_URL=${REPO_URL:-https://github.com/shadabshaukat/spaces-ai.git}
TARGET_USER=${TARGET_USER:-opc}

# OS packages
sudo dnf install -y curl git unzip firewalld oraclelinux-developer-release-el10 python3-oci-cli postgresql16 tesseract || true

# AWS CLI v2 (no credentials)
sudo bash -lc 'tmpdir=$(mktemp -d) && cd "$tmpdir" && curl -s https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -o awscliv2.zip && unzip -q awscliv2.zip && ./aws/install --update && cd / && rm -rf "$tmpdir"'

# uv (user-local). Prefer installing for TARGET_USER when present, else root.
if id -u "$TARGET_USER" >/dev/null 2>&1; then
  sudo -u "$TARGET_USER" bash -lc 'curl -LsSf https://astral.sh/uv/install.sh | sh'
  sudo -u "$TARGET_USER" bash -lc 'echo "export PATH=\$HOME/.local/bin:\$PATH" >> ~/.bashrc'
else
  sudo bash -lc 'curl -LsSf https://astral.sh/uv/install.sh | sh'
  sudo bash -lc 'echo "export PATH=\$HOME/.local/bin:\$PATH" >> /root/.bashrc'
fi

# Docker & Docker Compose
#sudo curl -fsSL https://get.docker.com | sh
#sudo dnf install -y docker-compose-plugin || true
#if [ ! -x /usr/local/bin/docker-compose ]; then
#  sudo curl -L "https://github.com/docker/compose/releases/download/v2.24.6/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose && sudo chmod +x /usr/local/bin/docker-compose || true
# sudo ln -sf /usr/local/bin/docker-compose /usr/bin/docker-compose || true
#fi
#sudo systemctl enable --now docker || true
#if id -u "$TARGET_USER" >/dev/null 2>&1; then
# sudo usermod -aG docker "$TARGET_USER" || true
#fi

# Firewall
sudo systemctl enable --now firewalld || true
sudo firewall-cmd --permanent --add-port="${APP_PORT}"/tcp || true
sudo firewall-cmd --reload || true

# Clone code
if id -u "$TARGET_USER" >/dev/null 2>&1; then
  sudo -u "$TARGET_USER" bash -lc "mkdir -p ~/src && cd ~/src && git clone ${REPO_URL} || true"
else
  sudo bash -lc "mkdir -p ~/src && cd ~/src && git clone ${REPO_URL} || true"
fi

echo "Bootstrap complete. You may need to log out/in for docker group membership to take effect."
