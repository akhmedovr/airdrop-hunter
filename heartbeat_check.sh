#!/bin/bash
# Heartbeat checker for Airdrop Hunter
# Runs every 5 min. If scheduler stale — restart via PM2.

cd /root/airdrop-hunter

if /root/airdrop-hunter/venv/bin/python -m src.core.heartbeat --check; then
    exit 0
fi

echo "$(date): heartbeat stale — restarting scheduler"
pm2 restart airdrop-hunter-scheduler
