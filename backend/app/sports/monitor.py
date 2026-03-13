"""
JA Hedge — 24/7 Sports Monitoring & Auto-Learning (Phase S10).

Runs continuously to:
  - Monitor edge drift (are our signals degrading?)
  - Auto-retrain sports model when new data arrives
  - Track P&L by sport / strategy / time period
  - Alert on anomalies
  - Clean up stale data
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from app.logging_config import get_logger

log = get_logger("sports.monitor")


@dataclass
class SportsPerformance:
    """Performance tracking by sport and strategy."""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl_cents: int = 0
    peak_pnl_cents: int = 0
    max_drawdown_cents: int = 0
    
    # By strategy
    vegas_trades: int = 0
    vegas_pnl_cents: int = 0
    ml_trades: int = 0
    ml_pnl_cents: int = 0
    live_trades: int = 0
    live_pnl_cents: int = 0
    
    @property
    def win_rate(self) -> float:
        return self.wins / max(self.total_trades, 1)
    
    @property
    def avg_pnl(self) -> float:
        return self.total_pnl_cents / max(self.total_trades, 1)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": f"{self.win_rate:.1%}",
            "total_pnl": f"${self.total_pnl_cents / 100:.2f}",
            "avg_pnl": f"${self.avg_pnl / 100:.2f}",
            "peak_pnl": f"${self.peak_pnl_cents / 100:.2f}",
            "max_drawdown": f"${self.max_drawdown_cents / 100:.2f}",
            "by_strategy": {
                "vegas": {"trades": self.vegas_trades, "pnl": f"${self.vegas_pnl_cents / 100:.2f}"},
                "ml": {"trades": self.ml_trades, "pnl": f"${self.ml_pnl_cents / 100:.2f}"},
                "live": {"trades": self.live_trades, "pnl": f"${self.live_pnl_cents / 100:.2f}"},
            },
        }


class SportsMonitor:
    """
    24/7 monitoring, learning, and health system.
    
    Runs alongside the collector to provide continuous oversight
    and automatic model improvement.
    """
    
    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task | None = None
        
        # Performance tracking per sport
        self._performance: dict[str, SportsPerformance] = {}
        self._overall = SportsPerformance()
        
        # Edge tracking
        self._recent_edges: list[float] = []
        self._max_edge_history = 100
        
        # Auto-retrain tracking
        self._last_retrain: float = 0.0
        self._retrain_interval: float = 7200.0  # retrain every 2 hours
        self._min_new_samples: int = 50
        self._new_samples_since_retrain: int = 0
        
        # Dependencies
        self._sports_predictor = None
        self._game_tracker = None
        
        # Alerts
        self._alerts: list[dict] = []
    
    def set_dependencies(self, **kwargs) -> None:
        for k, v in kwargs.items():
            setattr(self, f"_{k}", v)
    
    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(
            self._monitor_loop(),
            name="sports_monitor",
        )
        log.info("sports_monitor_started")
    
    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
    
    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        try:
            while self._running:
                try:
                    # Check for auto-retrain
                    await self._check_retrain()
                    
                    # Check for edge drift
                    self._check_edge_drift()
                    
                    # Clean up old game data
                    if self._game_tracker:
                        self._game_tracker.cleanup_old(max_age_hours=48)
                    
                except Exception as e:
                    log.error("monitor_error", error=str(e))
                
                await asyncio.sleep(300)  # check every 5 minutes
        except asyncio.CancelledError:
            return
    
    async def _check_retrain(self) -> None:
        """Auto-retrain sports model if enough new data."""
        if not self._sports_predictor:
            return
        
        now = time.time()
        should_retrain = (
            (now - self._last_retrain) > self._retrain_interval
            and self._new_samples_since_retrain >= self._min_new_samples
        )
        
        if should_retrain:
            log.info("auto_retrain_triggered",
                     new_samples=self._new_samples_since_retrain)
            
            success = await self._sports_predictor.train()
            if success:
                self._last_retrain = now
                self._new_samples_since_retrain = 0
                log.info("auto_retrain_complete")
                self._add_alert("info", "Sports model auto-retrained successfully")
            else:
                log.info("auto_retrain_skipped")
    
    def _check_edge_drift(self) -> None:
        """Monitor if our edge is degrading."""
        if len(self._recent_edges) < 20:
            return
        
        # Compare recent 10 to previous 10
        recent = self._recent_edges[-10:]
        previous = self._recent_edges[-20:-10]
        
        avg_recent = sum(recent) / len(recent)
        avg_previous = sum(previous) / len(previous)
        
        # If average edge dropped significantly
        if avg_recent < avg_previous * 0.5 and avg_previous > 0:
            self._add_alert(
                "warning",
                f"Edge drift detected: avg edge dropped from {avg_previous:.3f} to {avg_recent:.3f}"
            )
    
    def record_trade_outcome(
        self,
        sport_id: str,
        strategy: str,
        pnl_cents: int,
        edge: float,
        is_live: bool = False,
    ) -> None:
        """Record a completed trade for performance tracking."""
        # Overall
        self._overall.total_trades += 1
        self._overall.total_pnl_cents += pnl_cents
        if pnl_cents > 0:
            self._overall.wins += 1
        else:
            self._overall.losses += 1
        
        self._overall.peak_pnl_cents = max(
            self._overall.peak_pnl_cents,
            self._overall.total_pnl_cents
        )
        drawdown = self._overall.peak_pnl_cents - self._overall.total_pnl_cents
        self._overall.max_drawdown_cents = max(
            self._overall.max_drawdown_cents,
            drawdown
        )
        
        # By strategy
        if strategy == "vegas_baseline":
            self._overall.vegas_trades += 1
            self._overall.vegas_pnl_cents += pnl_cents
        elif strategy == "sports_xgb":
            self._overall.ml_trades += 1
            self._overall.ml_pnl_cents += pnl_cents
        
        if is_live:
            self._overall.live_trades += 1
            self._overall.live_pnl_cents += pnl_cents
        
        # By sport
        if sport_id not in self._performance:
            self._performance[sport_id] = SportsPerformance()
        sp = self._performance[sport_id]
        sp.total_trades += 1
        sp.total_pnl_cents += pnl_cents
        if pnl_cents > 0:
            sp.wins += 1
        else:
            sp.losses += 1
        
        # Edge tracking
        self._recent_edges.append(edge)
        if len(self._recent_edges) > self._max_edge_history:
            self._recent_edges = self._recent_edges[-self._max_edge_history:]
        
        # Count for auto-retrain
        self._new_samples_since_retrain += 1
    
    def _add_alert(self, level: str, message: str) -> None:
        self._alerts.append({
            "level": level,
            "message": message,
            "timestamp": time.time(),
        })
        # Keep last 50 alerts
        if len(self._alerts) > 50:
            self._alerts = self._alerts[-50:]
        
        if level == "warning":
            log.warning(f"sports_alert: {message}")
        else:
            log.info(f"sports_alert: {message}")
    
    def summary(self) -> dict[str, Any]:
        return {
            "overall": self._overall.to_dict(),
            "by_sport": {
                sport: perf.to_dict()
                for sport, perf in self._performance.items()
            },
            "edge_tracking": {
                "recent_edges": len(self._recent_edges),
                "avg_recent_edge": (
                    sum(self._recent_edges[-10:]) / max(len(self._recent_edges[-10:]), 1)
                    if self._recent_edges else 0
                ),
            },
            "auto_retrain": {
                "last_retrain": self._last_retrain,
                "new_samples": self._new_samples_since_retrain,
                "next_retrain_in": max(0, self._retrain_interval - (time.time() - self._last_retrain)),
            },
            "alerts": self._alerts[-10:],
        }


# Singleton
sports_monitor = SportsMonitor()
