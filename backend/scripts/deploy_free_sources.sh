#!/usr/bin/env bash
# Deploy: Replace Odds API with free multi-source system
set -e
cd "$(dirname "$0")/.."

echo "=== Verifying import chain ==="
source .venv/bin/activate
python -c "from app.main import app; print('✅ Import chain OK')"

echo ""
echo "=== Committing changes ==="
cd ..
git add -A
git commit -m "feat: replace The Odds API with free multi-source system

- NEW: RealtimeFeedClient (realtime_feed.py) — drop-in OddsClient replacement
  - Reads from intelligence hub (ESPN, Twitter, RSS, Reddit)
  - ESPN direct score fetching (free, no key)
  - Multi-source consensus probability
  - Same interface as OddsClient for zero code breakage

- NEW: TwitterLiveSource (social_twitter.py rewrite)
  - Bluesky public API (no auth needed)
  - Google News RSS (always works)
  - RSSHub Twitter bridges (best effort)
  - Replaces dead Nitter-based approach

- NEW: SportsRSSSource (sports_rss.py)
  - 15+ sports RSS feeds (ESPN, Yahoo, CBS, Bleacher Report, BBC)
  - Impact scoring for injuries/trades
  - Team name extraction

- FIX: Feature completeness gate relaxed (0.85 cold start)
  - Root cause of zero trades: >70% features are zero during cold start
  - Thresholds: 0.85 cold start, 0.75 untrained, 0.50 normal

- Updated: main.py, state.py, config.py, collector.py, routes/sports.py
- Removed: the_odds_api_key from config (no longer needed)
- Renamed: vegas -> consensus terminology throughout"

echo ""
echo "=== Pushing to Railway ==="
git push origin main

echo ""
echo "✅ Deployed. Wait ~90s then check https://frankensteintrading.com/health"
