"""Integration test — starts server, runs API tests, stops server."""
import subprocess
import sys
import time
import httpx
import os
import signal

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = os.path.join(BACKEND_DIR, ".venv", "bin", "python")
BASE = "http://localhost:8000"

def main():
    # Start server
    print("Starting server...")
    proc = subprocess.Popen(
        [PYTHON, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
        cwd=BACKEND_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    # Wait for server to be ready
    ready = False
    for i in range(30):
        time.sleep(1)
        try:
            r = httpx.get(f"{BASE}/health", timeout=3)
            if r.status_code == 200:
                ready = True
                break
        except Exception:
            pass

    if not ready:
        print("❌ Server failed to start in 30 seconds")
        proc.terminate()
        out = proc.stdout.read().decode() if proc.stdout else ""
        print("Server output:\n", out[-2000:])
        sys.exit(1)

    print("✅ Server is ready!\n")

    # Run tests
    endpoints = [
        ("GET", "/", "Root"),
        ("GET", "/health", "Health"),
        ("GET", "/api/markets", "Markets (cache)"),
        ("GET", "/api/portfolio/balance", "Portfolio Balance"),
        ("GET", "/api/portfolio/positions", "Positions"),
        ("GET", "/api/portfolio/pnl", "PnL"),
        ("GET", "/api/strategy/status", "Strategy Status"),
        ("GET", "/api/risk/snapshot", "Risk Snapshot"),
        ("GET", "/api/alerts", "Alerts"),
        ("GET", "/api/alerts/unread", "Unread Alerts"),
        ("GET", "/docs", "API Docs"),
    ]

    passed = 0
    failed = 0

    with httpx.Client(timeout=30) as client:
        for method, path, name in endpoints:
            try:
                t0 = time.time()
                r = client.request(method, f"{BASE}{path}")
                dt = (time.time() - t0) * 1000
                status = r.status_code
                size = len(r.content)
                ok = status < 400
                icon = "✅" if ok else "❌"
                print(f"{icon} {status:3d} {name:25s} {path:35s} {dt:7.0f}ms  ({size:,} bytes)")
                if ok:
                    passed += 1
                else:
                    failed += 1
                    print(f"      Response: {r.text[:200]}")
            except Exception as e:
                failed += 1
                print(f"💥 ERR {name:25s} {path:35s} {e}")

    # Test POST endpoints
    print("\n--- Write Endpoints ---")
    with httpx.Client(timeout=30) as client:
        # Test alert read
        try:
            r = client.post(f"{BASE}/api/alerts/read", json={"alert_ids": []})
            icon = "✅" if r.status_code < 400 else "❌"
            print(f"{icon} {r.status_code:3d} Mark Alerts Read        POST /api/alerts/read")
            if r.status_code < 400:
                passed += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            print(f"💥 ERR Mark Alerts Read        {e}")

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed, {passed+failed} total")
    print(f"{'='*60}")

    # Stop server
    proc.terminate()
    proc.wait(timeout=10)
    print("\nServer stopped.")

    sys.exit(0 if failed == 0 else 1)

if __name__ == "__main__":
    main()
