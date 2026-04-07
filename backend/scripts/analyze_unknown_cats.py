"""Analyze the local frankenstein_memory.json for unknown/empty categories."""
import json
from pathlib import Path

for p in ["data/frankenstein_memory.json"]:
    fp = Path(p)
    if not fp.exists():
        print(f"{p} not found")
        continue

    data = json.load(open(fp))
    trades = data.get("trades", [])
    cats: dict = {}
    unknown_examples: list = []

    for t in trades:
        cat = t.get("category", "")
        outcome = t.get("outcome", "")
        if not cat:
            cat = "<empty>"
        cats.setdefault(cat, {"total": 0, "outcomes": {}})
        cats[cat]["total"] += 1
        cats[cat]["outcomes"][outcome] = cats[cat]["outcomes"].get(outcome, 0) + 1

        if cat in ("unknown", "<empty>") and len(unknown_examples) < 10:
            unknown_examples.append({
                "ticker": t.get("ticker", ""),
                "title": t.get("market_title", "")[:80],
                "category": t.get("category", ""),
                "outcome": outcome,
                "pnl_cents": t.get("pnl_cents", 0),
                "source": t.get("source", ""),
            })

    print("=== Category Distribution ===")
    for cat, info in sorted(cats.items(), key=lambda x: -x[1]["total"]):
        print(f"  {cat:20s}: {info['total']:5d} trades | outcomes: {info['outcomes']}")

    print()
    print("=== Unknown/Empty Category Examples ===")
    for ex in unknown_examples:
        print(json.dumps(ex, indent=2))

    # Also check: what does detect_category return for these?
    print()
    print("=== Re-detecting categories for unknown/empty trades ===")
    try:
        import sys
        sys.path.insert(0, ".")
        from app.frankenstein.categories import detect_category
        redetect = {}
        for t in trades:
            cat = t.get("category", "")
            if cat in ("unknown", ""):
                new_cat = detect_category(
                    t.get("market_title", ""),
                    category_hint="",
                    ticker=t.get("ticker", ""),
                )
                redetect.setdefault(new_cat, 0)
                redetect[new_cat] += 1
        for cat, count in sorted(redetect.items(), key=lambda x: -x[1]):
            print(f"  {cat:20s}: {count}")
    except Exception as e:
        print(f"  Error: {e}")
