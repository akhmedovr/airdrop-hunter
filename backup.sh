#!/bin/bash
set -euo pipefail

PROJECT_DIR="/root/airdrop-hunter"
BACKUP_DIR="/root/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
ARCHIVE_RAW="$BACKUP_DIR/backup_$TIMESTAMP.tar.gz"
ARCHIVE_ENC="$BACKUP_DIR/backup_$TIMESTAMP.tar.gz.enc"

mkdir -p "$BACKUP_DIR"
cd "$PROJECT_DIR"

tar -czf "$ARCHIVE_RAW" data/airdrop.db .env ecosystem.config.js 2>/dev/null
chmod 600 "$ARCHIVE_RAW"

# Encrypt
/root/airdrop-hunter/venv/bin/python -m src.core.backup_encrypt enc "$ARCHIVE_RAW" "$ARCHIVE_ENC"

# Remove unencrypted archive
rm -f "$ARCHIVE_RAW"
chmod 600 "$ARCHIVE_ENC"

# Keep only last 7 backups
ls -t "$BACKUP_DIR"/backup_*.tar.gz.enc 2>/dev/null | tail -n +8 | xargs -r rm

# Send to Telegram
/root/airdrop-hunter/venv/bin/python -m src.core.backup_telegram || true
echo "OK: $ARCHIVE_ENC"
