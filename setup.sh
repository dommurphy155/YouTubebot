#!/bin/bash
set -e

# Update and install Docker if missing
if ! command -v docker &> /dev/null; then
  echo "Installing Docker..."
  apt-get update
  apt-get install -y ca-certificates curl gnupg lsb-release

  mkdir -p /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg

  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
    $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
else
  echo "Docker already installed."
fi

# Start Docker service if not running
if ! systemctl is-active --quiet docker; then
  echo "Starting Docker service..."
  systemctl start docker
fi

# Clone or pull latest repo
REPO_URL="https://github.com/dommurphy155/Very-last-try.git"
TARGET_DIR="/opt/video_bot"

if [ ! -d "$TARGET_DIR" ]; then
  echo "Cloning repository..."
  git clone "$REPO_URL" "$TARGET_DIR"
else
  echo "Updating repository..."
  cd "$TARGET_DIR"
  git pull origin main
fi

cd "$TARGET_DIR"

# Build and start Docker container
docker compose up -d --build

echo "Setup complete. Bot container is running."
