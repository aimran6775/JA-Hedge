"""Quick API endpoint test."""
import httpx
import json

BASE = "http://localhost:8000"

endpoints = [
    ("GET", "/", "Root"),
    ("GET", "/health", "Health"),
    ("GET", "/api/markets", "Markets"),
    ("GET", "/api/portfolio/balance", "Balance"),
    ("GET", "/api/portfolio/positions", "Positions"),
    ("GET", "/api/portfolio/pnl", "PnL"),
    ("GET", "/api/strategy/status", "Strategy Status"),
    ("GET", "/api/risk/snapshot", "Risk Snapshot"),
    ("GET", "/api/alerts", "Alerts"),
    ("GET", "/api/alerts/unread", "Unread Alerts"),
    ("GET", "/docs", "API Docs"),
]

with httpx.Client(timeout=10) as client:
    for method, path, name in endpoints:
        try:
            r = client.request(method, f"{BASE}{path}")
            status = r.status_code
            size = len(r.content)
            ok = "✅" if status < 400 else "❌"
            print(f"{ok} {status:3d} {name:20s} {path:35s} ({size:,} bytes)")
        except Exception as e:
            print(f"💥 ERR {name:20s} {path:35s} {e}")
