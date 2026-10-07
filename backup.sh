#!/bin/bash
set -euo pipefail

PROJECT_DIR="/root/airdrop-hunter"
BACKUP_DIR="/root/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
ARCHIVE="$BACKUP_DIR/backup_$TIMESTAMP.tar.gz"

mkdir -p "$BACKUP_DIR"
cd "$PROJECT_DIR"

tar -czf "$ARCHIVE" data/airdrop.db .env ecosystem.config.js 2>/dev/null
chmod 600 "$ARCHIVE"

# Keep only last 7 backups
ls -t "$BACKUP_DIR"/backup_*.tar.gz 2>/dev/null | tail -n +8 | xargs -r rm

/root/airdrop-hunter/venv/bin/python -m src.core.backup_telegram || true
echo "OK: $ARCHIVE"
