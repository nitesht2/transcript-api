#!/bin/bash
# Deploy Transcript API to Hostinger VPS
# Run this on your VPS after SSH-ing in
#
# Usage:
#   ssh user@your-vps-ip
#   bash deploy.sh

set -e

echo "Installing system deps..."
apt-get update -qq && apt-get install -y -qq ffmpeg python3-pip

echo "Installing Python deps..."
pip3 install -q fastapi uvicorn faster-whisper yt-dlp

echo "Creating systemd service..."
cat > /etc/systemd/system/transcript-api.service << SERVICE
[Unit]
Description=Transcript API
After=network.target

[Service]
User=root
WorkingDirectory=/opt/transcript-api
ExecStart=uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
Environment=API_KEY=${API_KEY:-changeme}
Environment=WHISPER_MODEL=base.en

[Install]
WantedBy=multi-user.target
SERVICE

echo "Copying app files..."
mkdir -p /opt/transcript-api
cp main.py /opt/transcript-api/

echo "Starting service..."
systemctl daemon-reload
systemctl enable transcript-api
systemctl restart transcript-api
systemctl status transcript-api --no-pager

echo ""
echo "Done. API running on http://$(hostname -I | awk '{print $1}'):8000"
echo "Test: curl -X POST http://localhost:8000/transcribe -H 'X-API-Key: changeme' -H 'Content-Type: application/json' -d '{\"url\":\"https://tiktok.com/...\"}'  "
