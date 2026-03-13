"""Test that the full FastAPI app can be constructed (import check)."""
import sys, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ".")

try:
    from app.main import app
    print(f"✅ FastAPI app created: {app.title}")
    
    routes = [r.path for r in app.routes]
    sports_routes = [r for r in routes if "sport" in r]
    print(f"✅ Total routes: {len(routes)}")
    print(f"✅ Sports routes: {sports_routes}")
    print(f"✅ /health route exists: {'/health' in routes}")
    
    print("\n🏀 APP IMPORT SUCCESS — ready to boot")
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"\n❌ App import failed: {e}")
    sys.exit(1)
