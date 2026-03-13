"""Test all sports API endpoints."""
import requests
import json
import sys

BASE = "http://localhost:8000"

def test(name, url, expected_status=200):
    try:
        r = requests.get(f"{BASE}{url}", timeout=10)
        status = "✅" if r.status_code == expected_status else "❌"
        print(f"{status} {name}: HTTP {r.status_code}")
        if r.status_code == expected_status:
            data = r.json()
            # Print compact summary
            if isinstance(data, dict):
                for k, v in list(data.items())[:8]:
                    if isinstance(v, (str, int, float, bool)):
                        print(f"   {k}: {v}")
                    elif isinstance(v, list):
                        print(f"   {k}: [{len(v)} items]")
                    elif isinstance(v, dict):
                        print(f"   {k}: {{{len(v)} keys}}")
            elif isinstance(data, list):
                print(f"   [{len(data)} items]")
        else:
            print(f"   Body: {r.text[:200]}")
        print()
        return r.status_code == expected_status
    except Exception as e:
        print(f"❌ {name}: {e}")
        print()
        return False

results = []

# Health
results.append(test("Health", "/health"))

# Sports endpoints
results.append(test("Sports Status", "/api/sports/status"))
results.append(test("Sports Markets", "/api/sports/markets"))
results.append(test("Sports Odds", "/api/sports/odds"))
results.append(test("Sports Live", "/api/sports/live"))
results.append(test("Sports Performance", "/api/sports/performance"))
results.append(test("Sports Signals", "/api/sports/signals"))

# Existing endpoints still work
results.append(test("Dashboard", "/api/dashboard"))
results.append(test("Frankenstein Status", "/api/frankenstein/status"))

passed = sum(results)
total = len(results)
print(f"{'='*50}")
print(f"Results: {passed}/{total} endpoints working")
if passed == total:
    print("🏀 ALL ENDPOINTS HEALTHY")
else:
    print(f"⚠️  {total - passed} endpoint(s) failing")
