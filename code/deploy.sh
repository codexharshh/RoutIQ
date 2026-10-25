#!/bin/bash

# Deploy script for RoutIQ
# Copies built frontend to staticfiles and restarts services

set -euo pipefail  # Exit on errors and unset variables

echo "ðŸš€ Starting deployment..."
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
SERVICE_NAME="${ROUTIQ_SYSTEMD_SERVICE:-routiq}"

 echo "ðŸ“‚ Using RoutIQ project directory: $PROJECT_DIR"
cd "$PROJECT_DIR"

# Copy dist files to staticfiles
echo "ðŸ“ Copying frontend build to staticfiles (optionally, remove old files manually)..."
if [ ! -d "dist" ]; then
  echo "âŒ Frontend build directory not found: $PROJECT_DIR/dist"
  echo "Run the frontend production build before deployment."
  exit 1
fi
mkdir -p ./backend/staticfiles
cp -r dist/. ./backend/staticfiles/

# Reload systemd daemon
echo "ðŸ”„ Reloading systemd daemon..."
sudo systemctl daemon-reload

# Test nginx configuration
echo "ðŸ” Testing nginx configuration..."
sudo nginx -t

# Reload nginx
echo "ðŸŒ Reloading nginx..."
sudo nginx -s reload

# Restart RoutIQ service
echo "ðŸ”„ Restarting RoutIQ service ($SERVICE_NAME)..."
sudo systemctl restart "$SERVICE_NAME"

# Restart nginx
echo "ðŸ”„ Restarting nginx..."
sudo systemctl restart nginx

echo "âœ… Deployment complete!"
