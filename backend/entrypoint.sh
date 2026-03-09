#!/bin/sh
set -e

# Write Kalshi private key from base64 env var (if provided)
if [ -n "$KALSHI_PRIVATE_KEY_BASE64" ]; then
    echo "$KALSHI_PRIVATE_KEY_BASE64" | base64 -d > /app/keys/kalshi.pem
    chmod 600 /app/keys/kalshi.pem
    echo "✅ Kalshi private key written to /app/keys/kalshi.pem"
fi

# Use PORT env var from Railway (defaults to 8000)
PORT="${PORT:-8000}"

exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --workers 1
