#!/bin/bash
# Commit and push Phase 23 changes.
set -e
cd /Users/abdullahimran/Documents/JA\ Hedge

# Remove stale test/debug scripts
rm -f backend/test_reddit_debug.py backend/test_reddit_rss.py
rm -f backend/test_news_debug.py backend/test_news_feeds.py
rm -f backend/test_rss_parse.py backend/test_rss_trace.py

git add -A
git commit -m "Phase 23: Wire intelligence data into ML model — 15 new features, TickerMapper, Reddit RSS, News fix

Changes:
- Created TickerMapper (ticker_mapper.py): Maps Kalshi tickers to intelligence signal keys
  via regex patterns for crypto, sports, weather, finance, politics categories
- Created Reddit social source (social_reddit.py): Replaces dead Nitter/Twitter
  with RSS/Atom feeds from 20+ subreddits (no API key, fully free)
- Fixed News sentiment (news_sentiment.py): ElementTree boolean evaluation bug
  caused 0 articles parsed despite successful fetches. Replaced 2 broken feeds,
  added 7 new feeds (CoinDesk, Guardian, WSJ, CNN, Yahoo Finance, etc.)
- Added Open-Meteo to weather source: Free unlimited weather API, no key needed
- Expanded MarketFeatures from 68 to 83 features (15 new alt-data features):
  vegas_prob, polymarket_prob, cross_platform_edge, crypto_strike_dist,
  crypto_momentum, econ_value, econ_strike_dist, econ_vix, yield_spread,
  news_sentiment, news_volume, social_sentiment, weather_temp, weather_extreme,
  source_count
- Rewrote scanner._intelligence_enrich: Uses TickerMapper to bridge Kalshi
  tickers to intelligence signal keys, populates all 15 alt features per market
- Added backward-compat in XGBoost predict: Trims 83-feature vectors to match
  old 68-feature model until retrain

Signal status after Phase 23:
  Polymarket: 1,840 | Weather: 15 | FRED: 14 | Crypto: 12 | Political: 10
  News: 6 (was 0) | Reddit: 1 (was 0) | Sports: 0 (no games) | Trends: 0"
git push origin main
