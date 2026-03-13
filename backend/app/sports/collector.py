"""
JA Hedge — Sports Data Collector (Phase S8).

Background task that continuously collects and stores:
  - Kalshi sports market snapshots
  - Vegas odds snapshots
  - Game outcomes
  - Feature snapshots for training data

This data feeds the 24/7 learning system.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.logging_config import get_logger

log = get_logger("sports.collector")


class SportsDataCollector:
    """
    Background data collector for sports markets.
    
    Runs 24/7 to build a dataset for:
      - Model training (features → outcomes)
      - Backtesting (historical snapshots)
      - Performance analysis (what worked, what didn't)
    """
    
    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task | None = None
        self._snapshot_interval = 60.0  # every 60 seconds
        self._odds_fetch_interval = 300.0  # every 5 minutes
        self._scores_fetch_interval = 30.0  # every 30 seconds during live games
        
        # Dependencies (set by main.py)
        self._detector = None
        self._odds_client = None
        self._game_tracker = None
        self._feature_engine = None  # base FeatureEngine
        self._sports_feature_engine = None
        self._sqlite = None
        
        # Stats
        self._stats = {
            "snapshots_taken": 0,
            "odds_fetches": 0,
            "scores_fetches": 0,
            "training_samples_collected": 0,
        }
    
    def set_dependencies(self, **kwargs) -> None:
        """Inject dependencies."""
        for k, v in kwargs.items():
            setattr(self, f"_{k}", v)
    
    async def start(self) -> None:
        """Start the collector background tasks."""
        self._running = True
        self._task = asyncio.create_task(
            self._collect_loop(),
            name="sports_collector",
        )
        log.info("sports_collector_started")
    
    async def stop(self) -> None:
        """Stop the collector."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("sports_collector_stopped")
    
    async def _collect_loop(self) -> None:
        """Main collection loop."""
        last_odds_fetch = 0.0
        last_scores_fetch = 0.0
        last_snapshot = 0.0
        
        try:
            while self._running:
                now = time.time()
                
                try:
                    # Fetch odds periodically
                    if self._odds_client and (now - last_odds_fetch) > self._odds_fetch_interval:
                        await self._fetch_all_odds()
                        last_odds_fetch = now
                        self._stats["odds_fetches"] += 1
                    
                    # Fetch scores more frequently (for live games)
                    if self._odds_client and (now - last_scores_fetch) > self._scores_fetch_interval:
                        await self._fetch_all_scores()
                        last_scores_fetch = now
                        self._stats["scores_fetches"] += 1
                    
                    # Take snapshots
                    if (now - last_snapshot) > self._snapshot_interval:
                        await self._take_snapshots()
                        last_snapshot = now
                        self._stats["snapshots_taken"] += 1
                
                except Exception as e:
                    log.error("collector_error", error=str(e))
                
                await asyncio.sleep(10)  # base loop interval
        
        except asyncio.CancelledError:
            return
    
    # Sports with active seasons (skip off-season to save API calls)
    _ACTIVE_SPORTS_KEYS = {
        "basketball_nba", "basketball_ncaab", "icehockey_nhl",
        "soccer_epl", "soccer_uefa_champs_league", "soccer_usa_mls",
    }
    
    async def _fetch_all_odds(self) -> None:
        """Fetch odds for all active sports."""
        if not self._odds_client or not self._odds_client.is_available:
            return
        
        # FIX #8: Skip if rate budget is low
        if not self._odds_client.rate_budget_ok:
            log.info("odds_fetch_skipped_rate_limit",
                     remaining=self._odds_client._requests_remaining)
            return
        
        from app.sports.detector import SPORT_REGISTRY
        
        for sport_id, config in SPORT_REGISTRY.items():
            for odds_key in config.odds_api_keys:
                # FIX #8: Only fetch for active/in-season sports
                if odds_key not in self._ACTIVE_SPORTS_KEYS:
                    continue
                try:
                    await self._odds_client.fetch_odds(odds_key)
                except Exception as e:
                    log.debug("odds_fetch_error", sport=odds_key, error=str(e))
                
                # Small delay between fetches to avoid rate limits
                await asyncio.sleep(1)
    
    async def _fetch_all_scores(self) -> None:
        """Fetch scores for sports with active games."""
        if not self._odds_client or not self._game_tracker:
            return
        
        # FIX #8: Skip if rate budget is low
        if not self._odds_client.rate_budget_ok:
            return
        
        # FIX #8: Only fetch for sports that have cached odds (active seasons)
        tracked_sports = set(self._odds_client._last_fetch.keys())
        
        from app.sports.detector import SPORT_REGISTRY
        
        for sport_id, config in SPORT_REGISTRY.items():
            for odds_key in config.odds_api_keys:
                # Skip sport keys we haven't fetched odds for
                if tracked_sports and odds_key not in tracked_sports:
                    continue
                try:
                    scores = await self._odds_client.fetch_scores(odds_key)
                    
                    # Update game tracker (FIX #6: pass commence_time)
                    for score in scores:
                        self._game_tracker.update_score(
                            game_id=score.game_id,
                            home_team=score.home_team,
                            away_team=score.away_team,
                            home_score=score.home_score,
                            away_score=score.away_score,
                            sport_id=sport_id,
                            is_completed=score.is_completed,
                            commence_time=score.commence_time,
                        )
                except Exception as e:
                    log.debug("scores_fetch_error", sport=odds_key, error=str(e))
                
                await asyncio.sleep(0.5)
    
    async def _take_snapshots(self) -> None:
        """Snapshot all sports markets with their features."""
        if not self._detector:
            return
        
        from app.pipeline import market_cache
        
        markets = market_cache.get_active()
        sports_markets = self._detector.filter_sports(markets)
        
        if not sports_markets:
            return
        
        snapshots = []
        for m in sports_markets:
            info = self._detector.detect(m)
            
            snapshot = {
                "timestamp": time.time(),
                "ticker": m.ticker,
                "event_ticker": m.event_ticker,
                "sport_id": info.sport_id,
                "market_type": info.market_type,
                "is_live": info.is_live,
                "yes_bid": float(m.yes_bid or 0),
                "yes_ask": float(m.yes_ask or 0),
                "midpoint": float(m.midpoint or 0),
                "volume": float(m.volume or 0),
                "open_interest": float(m.open_interest or 0),
            }
            
            # Add Vegas data if available
            if self._odds_client:
                game_odds = self._odds_client.find_game_odds(
                    info.home_team, info.away_team
                )
                if game_odds:
                    snapshot["vegas_home_prob"] = game_odds.consensus_home_prob
                    snapshot["vegas_away_prob"] = game_odds.consensus_away_prob
                    snapshot["num_bookmakers"] = len(game_odds.bookmakers)
            
            snapshots.append(snapshot)
        
        # Store to SQLite if available
        if self._sqlite and snapshots:
            try:
                self._sqlite.save_sports_snapshots(snapshots)
            except Exception as e:
                log.debug("snapshot_store_error", error=str(e))
        
        self._stats["training_samples_collected"] += len(snapshots)
        
        if len(sports_markets) > 0:
            log.debug(
                "sports_snapshots",
                markets=len(sports_markets),
                stored=len(snapshots),
            )
    
    def stats(self) -> dict[str, Any]:
        return dict(self._stats)


# Singleton
sports_collector = SportsDataCollector()
