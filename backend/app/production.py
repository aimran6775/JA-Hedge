"""
JA Hedge — Production Hardening (Phase 10).

Robust persistence, monitoring, and graceful degradation:

  1. SQLite persistence for trade memory (no external DB needed)
  2. Health monitoring with structured metrics
  3. Exchange schedule awareness (Kalshi operating hours)
  4. Graceful degradation when components fail
  5. State recovery after crashes/restarts
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Generator

from app.logging_config import get_logger

log = get_logger("production")


# ── SQLite Persistence ────────────────────────────────────────────────────


class SQLiteStore:
    """
    Lightweight SQLite persistence for Frankenstein state.

    No external database required — works on Railway ephemeral
    storage with periodic backups.
    """

    def __init__(self, db_path: str = "data/frankenstein.db"):
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    ticker TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    predicted_side TEXT,
                    confidence REAL,
                    predicted_prob REAL,
                    edge REAL,
                    action TEXT,
                    count INTEGER,
                    price_cents INTEGER,
                    total_cost_cents INTEGER,
                    order_id TEXT,
                    outcome TEXT DEFAULT 'pending',
                    pnl_cents INTEGER DEFAULT 0,
                    market_result TEXT,
                    model_version TEXT,
                    features_json TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS performance_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    total_pnl REAL,
                    win_rate REAL,
                    sharpe_ratio REAL,
                    max_drawdown REAL,
                    total_trades INTEGER,
                    model_version TEXT,
                    snapshot_json TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS model_checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version TEXT NOT NULL,
                    generation INTEGER,
                    val_auc REAL,
                    val_logloss REAL,
                    train_samples INTEGER,
                    is_champion INTEGER DEFAULT 0,
                    checkpoint_path TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS brain_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);
                CREATE INDEX IF NOT EXISTS idx_trades_outcome ON trades(outcome);
                CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);

                CREATE TABLE IF NOT EXISTS sports_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    ticker TEXT NOT NULL,
                    event_ticker TEXT,
                    sport_id TEXT,
                    market_type TEXT,
                    is_live INTEGER DEFAULT 0,
                    yes_bid REAL,
                    yes_ask REAL,
                    midpoint REAL,
                    volume REAL,
                    open_interest REAL,
                    vegas_home_prob REAL,
                    vegas_away_prob REAL,
                    num_bookmakers INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_sports_snap_ticker ON sports_snapshots(ticker);
                CREATE INDEX IF NOT EXISTS idx_sports_snap_sport ON sports_snapshots(sport_id);
                CREATE INDEX IF NOT EXISTS idx_sports_snap_ts ON sports_snapshots(timestamp);
            """)
            log.info("sqlite_initialized", path=self._db_path)

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for database connections."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Trade Persistence ─────────────────────────────────────────────

    def save_trade(self, trade: dict[str, Any]) -> None:
        """Persist a trade record."""
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO trades
                (trade_id, ticker, timestamp, predicted_side, confidence,
                 predicted_prob, edge, action, count, price_cents,
                 total_cost_cents, order_id, outcome, pnl_cents,
                 market_result, model_version, features_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.get("trade_id", ""),
                trade.get("ticker", ""),
                trade.get("timestamp", time.time()),
                trade.get("predicted_side", ""),
                trade.get("confidence", 0),
                trade.get("predicted_prob", 0),
                trade.get("edge", 0),
                trade.get("action", ""),
                trade.get("count", 0),
                trade.get("price_cents", 0),
                trade.get("total_cost_cents", 0),
                trade.get("order_id", ""),
                trade.get("outcome", "pending"),
                trade.get("pnl_cents", 0),
                trade.get("market_result", ""),
                trade.get("model_version", ""),
                json.dumps(trade.get("features", [])),
            ))

    def update_trade_outcome(
        self,
        trade_id: str,
        outcome: str,
        pnl_cents: int = 0,
        market_result: str = "",
    ) -> None:
        """Update a trade's outcome."""
        with self._conn() as conn:
            conn.execute("""
                UPDATE trades SET outcome=?, pnl_cents=?, market_result=?
                WHERE trade_id=?
            """, (outcome, pnl_cents, market_result, trade_id))

    def get_recent_trades(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent trades."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_trade_stats(self) -> dict[str, Any]:
        """Get aggregate trade statistics."""
        with self._conn() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN outcome='win' THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN outcome='loss' THEN 1 ELSE 0 END) as losses,
                    SUM(pnl_cents) as total_pnl,
                    AVG(pnl_cents) as avg_pnl,
                    COUNT(DISTINCT ticker) as unique_tickers
                FROM trades WHERE outcome != 'pending'
            """).fetchone()
            return dict(row) if row else {}

    # ── Brain State ───────────────────────────────────────────────────

    def save_state(self, key: str, value: Any) -> None:
        """Save a key-value state pair."""
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO brain_state (key, value, updated_at) VALUES (?, ?, ?)",
                (key, json.dumps(value, default=str), datetime.now(timezone.utc).isoformat()),
            )

    def load_state(self, key: str, default: Any = None) -> Any:
        """Load a state value."""
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM brain_state WHERE key=?", (key,)).fetchone()
            if row:
                try:
                    return json.loads(row["value"])
                except Exception:
                    return default
            return default

    # ── Performance Snapshots ─────────────────────────────────────────

    def save_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Save a performance snapshot."""
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO performance_snapshots
                (timestamp, total_pnl, win_rate, sharpe_ratio, max_drawdown,
                 total_trades, model_version, snapshot_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot.get("timestamp", time.time()),
                snapshot.get("total_pnl", 0),
                snapshot.get("win_rate", 0),
                snapshot.get("sharpe_ratio", 0),
                snapshot.get("max_drawdown", 0),
                snapshot.get("total_trades", 0),
                snapshot.get("model_version", ""),
                json.dumps(snapshot),
            ))

    def save_sports_snapshots(self, snapshots: list[dict[str, Any]]) -> None:
        """Save sports market snapshots for training data."""
        with self._conn() as conn:
            for s in snapshots:
                conn.execute("""
                    INSERT INTO sports_snapshots
                    (timestamp, ticker, event_ticker, sport_id, market_type,
                     is_live, yes_bid, yes_ask, midpoint, volume,
                     open_interest, vegas_home_prob, vegas_away_prob, num_bookmakers)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    s.get("timestamp", time.time()),
                    s.get("ticker", ""),
                    s.get("event_ticker", ""),
                    s.get("sport_id", ""),
                    s.get("market_type", ""),
                    int(s.get("is_live", False)),
                    s.get("yes_bid", 0),
                    s.get("yes_ask", 0),
                    s.get("midpoint", 0),
                    s.get("volume", 0),
                    s.get("open_interest", 0),
                    s.get("vegas_home_prob", 0),
                    s.get("vegas_away_prob", 0),
                    s.get("num_bookmakers", 0),
                ))


# ── Exchange Schedule ─────────────────────────────────────────────────────


class ExchangeSchedule:
    """
    Kalshi exchange operating hours awareness.

    Kalshi markets trade 24/7 but liquidity varies dramatically.

    FIX #9: Properly computes ET offset (auto-detect EDT/EST),
    and NEVER blocks trading entirely — sports games run at night.
    """

    @classmethod
    def _et_hour(cls) -> tuple[int, int]:
        """Return (et_hour, weekday) using proper US/Eastern offset."""
        now_utc = datetime.now(timezone.utc)
        month = now_utc.month
        if 3 < month < 11:
            et_offset = -4  # EDT
        elif month == 3:
            second_sun = 14 - (datetime(now_utc.year, 3, 1).weekday() + 1) % 7
            et_offset = -4 if now_utc.day >= second_sun else -5
        elif month == 11:
            first_sun = 7 - (datetime(now_utc.year, 11, 1).weekday() + 1) % 7
            et_offset = -5 if now_utc.day >= first_sun else -4
        else:
            et_offset = -5  # EST
        et_hour = (now_utc.hour + et_offset) % 24
        return et_hour, now_utc.weekday()

    @classmethod
    def current_session(cls) -> str:
        """Get current trading session type."""
        et_hour, weekday = cls._et_hour()

        if weekday >= 5:
            return "weekend"
        elif 9 <= et_hour < 17:
            return "peak"
        elif 17 <= et_hour < 22:
            return "evening"
        elif 6 <= et_hour < 9:
            return "pre_market"
        else:
            return "overnight"

    @classmethod
    def liquidity_factor(cls) -> float:
        session = cls.current_session()
        return {
            "peak": 1.0,
            "evening": 0.7,
            "pre_market": 0.5,
            "overnight": 0.4,
            "weekend": 0.5,
        }.get(session, 0.5)

    @classmethod
    def should_trade(cls) -> tuple[bool, str]:
        """
        Should we be trading right now?

        FIX #9: ALWAYS returns True. Sports games happen 24/7.
        The liquidity_factor scales position sizes instead of blocking.
        """
        session = cls.current_session()
        return True, session


# ── Health Monitor ────────────────────────────────────────────────────────


class HealthMonitor:
    """
    Tracks system health metrics for monitoring and alerting.

    Collects:
    - Component status (alive/dead)
    - Latency metrics
    - Error rates
    - Resource usage
    """

    def __init__(self) -> None:
        self._checks: dict[str, dict[str, Any]] = {}
        self._error_counts: dict[str, int] = {}
        self._last_errors: dict[str, str] = {}
        self._start_time = time.time()

    def record_check(self, component: str, healthy: bool, details: str = "") -> None:
        """Record a health check result."""
        self._checks[component] = {
            "healthy": healthy,
            "details": details,
            "last_check": time.time(),
        }
        if not healthy:
            self._error_counts[component] = self._error_counts.get(component, 0) + 1
            self._last_errors[component] = details

    def record_error(self, component: str, error: str) -> None:
        """Record an error occurrence."""
        self._error_counts[component] = self._error_counts.get(component, 0) + 1
        self._last_errors[component] = error

    @property
    def is_healthy(self) -> bool:
        """Overall system health."""
        if not self._checks:
            return True
        return all(c["healthy"] for c in self._checks.values())

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self._start_time

    def summary(self) -> dict[str, Any]:
        """Full health summary."""
        return {
            "healthy": self.is_healthy,
            "uptime": f"{self.uptime_seconds:.0f}s",
            "components": {
                name: {
                    "healthy": check["healthy"],
                    "details": check.get("details", ""),
                    "errors": self._error_counts.get(name, 0),
                    "last_error": self._last_errors.get(name, ""),
                }
                for name, check in self._checks.items()
            },
            "total_errors": sum(self._error_counts.values()),
        }


# ── Graceful Degradation ─────────────────────────────────────────────────


class DegradationManager:
    """
    Manages graceful degradation when components fail.

    Priority order (what to keep running):
    1. Risk management (always on — safety first)
    2. Position management (exit capability)
    3. Market data pipeline
    4. Trading (can be paused)
    5. Retraining (can be skipped)
    6. WebSocket (fall back to REST)
    """

    def __init__(self) -> None:
        self._degraded_components: set[str] = set()
        self._fallback_active: dict[str, str] = {}

    def mark_degraded(self, component: str, fallback: str = "") -> None:
        """Mark a component as degraded with optional fallback."""
        self._degraded_components.add(component)
        if fallback:
            self._fallback_active[component] = fallback
        log.warning("component_degraded", component=component, fallback=fallback)

    def mark_recovered(self, component: str) -> None:
        """Mark a component as recovered."""
        self._degraded_components.discard(component)
        self._fallback_active.pop(component, None)
        log.info("component_recovered", component=component)

    def is_degraded(self, component: str) -> bool:
        return component in self._degraded_components

    def should_pause_trading(self) -> tuple[bool, str]:
        """Should we pause trading due to degradation?"""
        critical = {"risk_manager", "execution_engine", "market_data"}
        degraded_critical = self._degraded_components & critical

        if degraded_critical:
            return True, f"critical_components_degraded: {degraded_critical}"

        return False, ""

    def status(self) -> dict[str, Any]:
        return {
            "degraded_components": list(self._degraded_components),
            "fallbacks_active": dict(self._fallback_active),
            "trading_safe": not bool(
                self._degraded_components & {"risk_manager", "execution_engine"}
            ),
        }
