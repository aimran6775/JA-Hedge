#!/bin/bash
# Restart the JA Hedge backend server with Phase 23 changes.
set -e

echo "=== Killing existing server ==="
pkill -f "run_server.py" 2>/dev/null || true
sleep 2

echo "=== Clearing __pycache__ ==="
find /Users/abdullahimran/Documents/JA\ Hedge/backend -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

echo "=== Starting server ==="
cd /Users/abdullahimran/Documents/JA\ Hedge/backend
nohup ~/.jahedge-venv/bin/python run_server.py > /tmp/jahedge-server.log 2>&1 &
echo "Server PID: $!"

echo "=== Waiting for startup ==="
sleep 8

echo "=== Health check ==="
curl -s http://localhost:8000/health | python3 -m json.tool 2>/dev/null || echo "Health check pending..."

echo ""
echo "=== Intelligence Hub status ==="
curl -s http://localhost:8000/api/intelligence/status | python3 -m json.tool 2>/dev/null || echo "Intelligence pending..."
