"""
JA Hedge — Sports API Routes (Phase S9).

Endpoints for the sports trading dashboard:
  - /api/sports/status       — Overall sports system status
  - /api/sports/markets      — Active sports markets
  - /api/sports/odds         — Current Vegas odds
  - /api/sports/live         — Live game states
  - /api/sports/performance  — Sports P&L tracking
  - /api/sports/signals      — Active trading signals
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from typing import Any

from app.logging_config import get_logger
from app.state import state

log = get_logger("routes.sports")

router = APIRouter(prefix="/sports", tags=["sports"])


@router.get("/status")
async def sports_status() -> dict[str, Any]:
    """Full sports system status."""
    result: dict[str, Any] = {
        "sports_mode": True,
        "components": {},
    }
    
    # Detector stats
    if state.sports_detector:
        result["detector"] = state.sports_detector.stats()
        result["components"]["detector"] = "ready"
    else:
        result["components"]["detector"] = "not_initialized"
    
    # Odds client
    if state.odds_client:
        odds_stats = state.odds_client.stats()
        result["odds"] = odds_stats
        quota_remaining = odds_stats.get("requests_remaining", 1)
        if quota_remaining == 0:
            result["components"]["odds_client"] = "quota_exhausted"
            result["odds_warning"] = (
                "Free tier Odds API quota exhausted (500/month). "
                "Vegas odds unavailable until next billing cycle. "
                "Predictions use Kalshi-only signals with reduced accuracy."
            )
        else:
            result["components"]["odds_client"] = "ready" if state.odds_client.is_available else "no_api_key"
    else:
        result["components"]["odds_client"] = "not_initialized"
    
    # Game tracker
    if state.game_tracker:
        result["games"] = state.game_tracker.stats()
        result["components"]["game_tracker"] = "ready"
    else:
        result["components"]["game_tracker"] = "not_initialized"
    
    # Sports predictor
    if state.sports_predictor:
        result["predictor"] = state.sports_predictor.stats()
        result["components"]["predictor"] = "ready"
    else:
        result["components"]["predictor"] = "not_initialized"
    
    # Sports risk
    if state.sports_risk:
        result["risk"] = state.sports_risk.summary()
        result["components"]["risk"] = "ready"
    else:
        result["components"]["risk"] = "not_initialized"
    
    # Sports monitor
    if state.sports_monitor:
        result["performance"] = state.sports_monitor.summary()
        result["components"]["monitor"] = "ready"
    else:
        result["components"]["monitor"] = "not_initialized"
    
    # Live engine
    if state.live_engine:
        result["live_engine"] = state.live_engine.stats()
        result["components"]["live_engine"] = "ready"
    else:
        result["components"]["live_engine"] = "not_initialized"
    
    # Collector
    if state.sports_collector:
        result["collector"] = state.sports_collector.stats()
        result["components"]["collector"] = "ready"
    else:
        result["components"]["collector"] = "not_initialized"
    
    return result


@router.get("/markets")
async def sports_markets() -> dict[str, Any]:
    """Get all active sports markets grouped by sport."""
    from app.pipeline import market_cache
    
    if not state.sports_detector:
        raise HTTPException(status_code=503, detail="Sports detector not initialized")
    
    markets = market_cache.get_active()
    sports_markets = state.sports_detector.filter_sports(markets)
    
    # Group by sport
    by_sport: dict[str, list] = {}
    for m in sports_markets:
        info = state.sports_detector.detect(m)
        sport = info.sport_id or "unknown"
        
        market_data = {
            "ticker": m.ticker,
            "event_ticker": m.event_ticker,
            "title": m.title,
            "subtitle": m.subtitle,
            "sport": sport,
            "market_type": info.market_type,
            "is_live": info.is_live,
            "home_team": info.home_team,
            "away_team": info.away_team,
            "yes_bid": float(m.yes_bid or 0),
            "yes_ask": float(m.yes_ask or 0),
            "midpoint": float(m.midpoint or 0),
            "volume": float(m.volume or 0),
            "open_interest": float(m.open_interest or 0),
        }
        
        # Add Vegas comparison if available
        if state.odds_client:
            game_odds = state.odds_client.find_game_odds(
                info.home_team, info.away_team
            )
            if game_odds:
                market_data["vegas_home_prob"] = round(game_odds.consensus_home_prob, 3)
                market_data["vegas_away_prob"] = round(game_odds.consensus_away_prob, 3)
                market_data["num_bookmakers"] = len(game_odds.bookmakers)
                
                # Discrepancy
                kalshi_mid = float(m.midpoint or 0)
                if kalshi_mid > 0 and game_odds.consensus_home_prob > 0:
                    market_data["kalshi_vs_vegas"] = round(
                        kalshi_mid - game_odds.consensus_home_prob, 3
                    )
        
        by_sport.setdefault(sport, []).append(market_data)
    
    return {
        "total_sports_markets": len(sports_markets),
        "total_all_markets": len(markets),
        "sports_pct": f"{len(sports_markets) / max(len(markets), 1):.0%}",
        "by_sport": by_sport,
    }


@router.get("/odds")
async def sports_odds() -> dict[str, Any]:
    """Get current Vegas odds from cache."""
    if not state.odds_client:
        raise HTTPException(status_code=503, detail="Odds client not initialized")
    
    all_odds = state.odds_client.cache.get_all_odds()
    
    games = []
    for odds in all_odds:
        games.append({
            "game_id": odds.game_id,
            "sport": odds.sport_key,
            "home_team": odds.home_team,
            "away_team": odds.away_team,
            "commence_time": odds.commence_time,
            "consensus_home_prob": round(odds.consensus_home_prob, 3),
            "consensus_away_prob": round(odds.consensus_away_prob, 3),
            "consensus_spread": odds.consensus_spread,
            "consensus_total": odds.consensus_total,
            "num_bookmakers": len(odds.bookmakers),
        })
    
    return {
        "total_games": len(games),
        "games": games,
        "api_stats": state.odds_client.stats(),
        "api_quota_exhausted": state.odds_client.stats().get("requests_remaining", 1) == 0,
        "quota_warning": (
            "Free tier Odds API quota exhausted (500/month). "
            "Vegas odds comparisons unavailable until quota resets. "
            "Sports predictions will use Kalshi-only signals with reduced edge detection."
            if state.odds_client.stats().get("requests_remaining", 1) == 0
            else None
        ),
    }


@router.get("/live")
async def live_games() -> dict[str, Any]:
    """Get all live game states."""
    if not state.game_tracker:
        raise HTTPException(status_code=503, detail="Game tracker not initialized")
    
    live = state.game_tracker.get_live_games()
    
    return {
        "live_games": len(live),
        "games": [g.to_dict() for g in live],
        "tracker_stats": state.game_tracker.stats(),
    }


@router.get("/performance")
async def sports_performance() -> dict[str, Any]:
    """Get sports trading performance."""
    if not state.sports_monitor:
        raise HTTPException(status_code=503, detail="Sports monitor not initialized")
    
    return state.sports_monitor.summary()


@router.get("/signals")
async def sports_signals() -> dict[str, Any]:
    """Get active live trading signals."""
    if not state.live_engine:
        raise HTTPException(status_code=503, detail="Live engine not initialized")
    
    signals = state.live_engine.get_pending_signals()
    
    return {
        "pending_signals": len(signals),
        "signals": [
            {
                "type": s.signal_type,
                "ticker": s.ticker,
                "side": s.side,
                "strength": round(s.strength, 3),
                "urgency": round(s.urgency, 3),
                "reason": s.reason,
                "age_seconds": round(time.time() - s.timestamp, 1),
            }
            for s in signals
        ],
        "engine_stats": state.live_engine.stats(),
    }


@router.post("/odds/refresh")
async def refresh_odds() -> dict[str, Any]:
    """Force refresh Vegas odds for all sports."""
    if not state.odds_client or not state.odds_client.is_available:
        raise HTTPException(status_code=503, detail="Odds client not available")
    
    from app.sports.detector import SPORT_REGISTRY
    
    results = {}
    for sport_id, config in SPORT_REGISTRY.items():
        for key in config.odds_api_keys:
            try:
                games = await state.odds_client.fetch_odds(key, force=True)
                results[key] = len(games)
            except Exception as e:
                results[key] = f"error: {str(e)}"
    
    return {
        "refreshed": results,
        "remaining_requests": state.odds_client._requests_remaining,
    }


import time  # noqa: E402
