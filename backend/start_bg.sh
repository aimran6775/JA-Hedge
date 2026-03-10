#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
python run_server.py > /tmp/jahedge.log 2>&1 &
echo "PID=$!"
