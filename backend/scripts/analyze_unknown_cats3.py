"""Check what detect_category returns for the main unknown ticker prefixes."""
import sys
sys.path.insert(0, ".")
from app.frankenstein.categories import detect_category, KALSHI_PREFIX_CATEGORY

test_tickers = [
    "KXQUICKSETTLE-26MAR14H1440-3",
    "KXMVESPORTSMULTIGAMEEXTENDED-S202616FB465B1B3-077200B5AFB",
    "KXNEXTAG-26MAR14-CHGORL",
    "KXHYPE-26MAR14-T5000",
    "KXMVECROSSCATEGORY-S2026F0E00A7E05A-0E8759C587F",
    "KXAAAGASW-26MAR14H1440-3",
    "KXNBATOTAL-26MAR14-CHGORL",
    "KXBTCD-26MAR14-T100K",
    "KXCS-26MAR14-T5",
    "KXLEAVITTSMFMENTION-26MAR14-T5",
]

print("=== detect_category results for unknown tickers ===")
for t in test_tickers:
    cat = detect_category("", category_hint="", ticker=t)
    # Check if any prefix matches
    import re
    m = re.match(r"(KX[A-Z]+)", t.upper())
    prefix = m.group(1) if m else "?"
    matched = prefix in KALSHI_PREFIX_CATEGORY
    print(f"  {t[:50]:50s} -> prefix={prefix:30s} inMap={matched} -> cat={cat}")

print()
print("=== Prefixes NOT in KALSHI_PREFIX_CATEGORY ===")
missing = set()
for prefix in ["KXQUICKSETTLE", "KXMVESPORTSMULTIGAMEEXTENDED", "KXNEXTAG",
               "KXHYPE", "KXMVECROSSCATEGORY", "KXAAAGASW", "KXNBATOTAL",
               "KXBTCD", "KXCS", "KXLEAVITTSMFMENTION"]:
    if prefix not in KALSHI_PREFIX_CATEGORY:
        missing.add(prefix)
        print(f"  MISSING: {prefix}")
    else:
        print(f"  FOUND:   {prefix} -> {KALSHI_PREFIX_CATEGORY[prefix]}")

print()
print("=== Backfill simulation ===")
# The load() backfill only works when detect_category returns != "general"
# Let's see what these unknown tickers get
for prefix in sorted(missing):
    cat = detect_category("", "", ticker=f"{prefix}-test")
    print(f"  {prefix:30s} -> {cat}  (backfill skips if 'general')")
