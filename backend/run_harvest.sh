#!/bin/bash
# Focused candle harvester — runs detached, won't die on terminal close
cd "$(dirname "$0")"
echo "Starting candle harvest at $(date)..."
echo "Log: /tmp/candle_harvest.log"
echo "Check progress: python3 -c \"import sqlite3; c=sqlite3.connect('data/historical.db'); print(c.execute('SELECT COUNT(*) FROM candles').fetchone()[0],'candles'); c.close()\""

~/.jahedge-venv/bin/python harvest_candles.py >> /tmp/candle_harvest.log 2>&1

echo "Harvest complete at $(date)"
echo "Check /tmp/candle_harvest.log for details"
