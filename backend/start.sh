#!/bin/bash
cd "$(dirname "$0")"

# Use the non-iCloud venv directly
PYTHON=~/.jahedge-venv/bin/python

# Kill any existing server
pkill -9 -f "run_server|uvicorn" 2>/dev/null
sleep 1

# Start server, log to file
echo "=== Server starting at $(date) ===" > server.log
$PYTHON run_server.py >> server.log 2>&1 &
SERVER_PID=$!
echo "Server PID: $SERVER_PID"

# Wait for it to come up (max 30s)
for i in $(seq 1 30); do
    sleep 1
    CODE=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/health 2>/dev/null)
    if [ "$CODE" = "200" ]; then
        echo "Server UP after ${i}s!"
        curl -s http://localhost:8000/health | python3 -m json.tool
        exit 0
    fi
    echo "  waiting... (${i}s, HTTP $CODE)"
done

echo "Server failed to start in 30s. Log tail:"
tail -30 server.log
