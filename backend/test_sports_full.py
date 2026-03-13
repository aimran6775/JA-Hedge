"""Full endpoint test — starts server in subprocess, tests, then stops."""
import subprocess, time, sys, os, json
from urllib.request import urlopen, Request
from urllib.error import URLError

os.chdir(os.path.dirname(os.path.abspath(__file__)))

PYTHON = os.path.abspath(".venv/bin/python")
BASE = "http://localhost:8000"

# Start server
print("Starting server...")
proc = subprocess.Popen(
    [PYTHON, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    cwd=os.path.dirname(os.path.abspath(__file__)),
)

# Wait for server
for i in range(30):
    time.sleep(1)
    try:
        urlopen(f"{BASE}/health", timeout=3)
        print(f"Server ready after {i+1}s")
        break
    except:
        pass
else:
    print("❌ Server failed to start in 30s")
    proc.terminate()
    sys.exit(1)

# Test endpoints
passed = 0
failed = 0

def test(name, url, expected=200):
    global passed, failed
    try:
        r = urlopen(f"{BASE}{url}", timeout=10)
        data = json.loads(r.read())
        if r.status == expected:
            print(f"✅ {name}: HTTP {r.status}")
            if isinstance(data, dict):
                keys = list(data.keys())[:6]
                for k in keys:
                    v = data[k]
                    if isinstance(v, (str, int, float, bool)):
                        print(f"   {k}: {v}")
                    elif isinstance(v, list):
                        print(f"   {k}: [{len(v)} items]")
                    elif isinstance(v, dict):
                        print(f"   {k}: {{{len(v)} keys}}")
            passed += 1
        else:
            print(f"❌ {name}: HTTP {r.status}")
            failed += 1
    except URLError as e:
        print(f"❌ {name}: {e}")
        failed += 1
    except Exception as e:
        print(f"❌ {name}: {type(e).__name__}: {e}")
        failed += 1

print("\n" + "="*50)
print("TESTING ENDPOINTS")
print("="*50 + "\n")

test("Health", "/health")
test("Sports Status", "/api/sports/status")
test("Sports Markets", "/api/sports/markets")
test("Sports Odds", "/api/sports/odds")
test("Sports Live", "/api/sports/live")
test("Sports Performance", "/api/sports/performance")
test("Sports Signals", "/api/sports/signals")
test("Dashboard", "/api/dashboard")
test("Frankenstein Status", "/api/frankenstein/status")

print(f"\n{'='*50}")
print(f"Results: {passed}/{passed+failed} endpoints working")
if failed == 0:
    print("🏀 ALL ENDPOINTS HEALTHY")
else:
    print(f"⚠️  {failed} endpoint(s) need attention")

# Shutdown
proc.terminate()
proc.wait(timeout=10)
print("\nServer stopped.")
