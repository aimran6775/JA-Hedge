"""
Frankenstein — Trade Memory & Experience Replay Buffer.

Stores every prediction, trade, and outcome in memory so
Frankenstein can learn from its own history. Supports:

- Rolling experience buffer (configurable size)
- Feature/label extraction for retraining
- Trade outcome tracking (win/loss/pending)
- Market regime detection data
- Serialization to/from disk for persistence
"""

from __future__ import annotations

import json
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

from app.ai.features import MarketFeatures
from app.ai.models import Prediction
from app.logging_config import get_logger

log = get_logger("frankenstein.memory")


class TradeOutcome(str, Enum):
    """Outcome of a trade."""
    PENDING = "pending"
    WIN = "win"
    LOSS = "loss"
    BREAKEVEN = "breakeven"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass
class TradeRecord:
    """A single trade in Frankenstein's memory."""

    # Identity
    trade_id: str = field(default_factory=lambda: f"fk-{uuid.uuid4().hex[:10]}")
    timestamp: float = field(default_factory=time.time)

    # Market context
    ticker: str = ""
    market_title: str = ""
    category: str = ""

    # Prediction that led to this trade
    predicted_side: str = ""       # "yes" or "no"
    confidence: float = 0.0
    predicted_prob: float = 0.0
    raw_predicted_prob: float = 0.0  # pre-calibration prob (for calibration tracking)
    edge: float = 0.0
    model_version: str = ""

    # Features at time of prediction (numpy array as list for serialization)
    features: list[float] = field(default_factory=list)
    feature_names: list[str] = field(default_factory=list)

    # Execution details
    action: str = ""               # "buy" or "sell"
    side_executed: str = ""        # "yes" or "no"
    count: int = 0
    price_cents: int = 0
    total_cost_cents: int = 0
    fees_cents: int = 0
    order_id: str = ""
    fill_latency_ms: float = 0.0

    # Market state at entry
    market_bid_cents: int = 0
    market_ask_cents: int = 0
    market_volume: float = 0.0
    hours_to_expiry: float = 0.0

    # Outcome (filled in later)
    outcome: TradeOutcome = TradeOutcome.PENDING
    exit_price_cents: int = 0
    pnl_cents: int = 0
    pnl_pct: float = 0.0
    hold_time_seconds: float = 0.0
    market_result: str = ""        # "yes" or "no" (actual result)
    outcome_timestamp: float = 0.0

    # Learning metadata
    was_correct: bool | None = None
    regret: float = 0.0           # difference between optimal and actual
    epoch: int = 0                 # which training epoch used this

    # Multi-factor confidence breakdown (Phase 11)
    confidence_breakdown: dict[str, Any] = field(default_factory=dict)

    # Data provenance — distinguish bootstrap vs live trades
    source: str = "live"  # "live", "bootstrap", "bootstrap_active"

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON storage."""
        d = {}
        for k, v in self.__dict__.items():
            if isinstance(v, TradeOutcome):
                d[k] = v.value
            elif isinstance(v, (Decimal, np.floating)):
                d[k] = float(v)
            else:
                d[k] = v
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TradeRecord":
        """Deserialize from dict."""
        if "outcome" in d and isinstance(d["outcome"], str):
            d["outcome"] = TradeOutcome(d["outcome"])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class MarketSnapshot:
    """Point-in-time snapshot of a market for regime detection."""
    ticker: str
    timestamp: float
    midpoint: float
    spread: float
    volume: float
    volatility: float = 0.0
    trend: float = 0.0  # positive = bullish, negative = bearish


class TradeMemory:
    """
    Frankenstein's memory — stores all trades and market observations.

    Acts as an experience replay buffer for continuous learning.
    Old memories are gradually forgotten (FIFO) but high-impact
    trades (big wins/losses) are retained longer.
    """

    def __init__(
        self,
        max_trades: int = 50_000,
        max_snapshots: int = 100_000,
        persist_path: str | None = None,
    ):
        self.max_trades = max_trades
        self.max_snapshots = max_snapshots
        self.persist_path = persist_path

        # Core storage
        self._trades: deque[TradeRecord] = deque(maxlen=max_trades)
        self._snapshots: deque[MarketSnapshot] = deque(maxlen=max_snapshots)
        self._important_trades: list[TradeRecord] = []  # High-impact trades (capped at 500)

        # Indexes for fast lookup
        self._by_ticker: dict[str, list[str]] = {}  # ticker → [trade_id]
        self._by_outcome: dict[TradeOutcome, int] = {o: 0 for o in TradeOutcome}
        self._pending_trades: dict[str, TradeRecord] = {}  # trade_id → record

        # Stats
        self.total_recorded = 0
        self.total_resolved = 0
        self.total_wins = 0
        self.total_losses = 0

        # Load from disk if path exists
        if persist_path and Path(persist_path).exists():
            self.load(persist_path)

        log.info("trade_memory_initialized", max_trades=max_trades, loaded=len(self._trades))

    # ── Record Trades ─────────────────────────────────────────────────

    def record_trade(
        self,
        ticker: str,
        prediction: Prediction,
        features: MarketFeatures,
        action: str,
        count: int,
        price_cents: int,
        order_id: str = "",
        fees_cents: int = 0,
        latency_ms: float = 0.0,
        market_bid: int = 0,
        market_ask: int = 0,
        model_version: str = "",
        confidence_breakdown: dict | None = None,
    ) -> TradeRecord:
        """Record a new trade in memory."""
        record = TradeRecord(
            ticker=ticker,
            predicted_side=prediction.side,
            confidence=prediction.confidence,
            predicted_prob=prediction.predicted_prob,
            raw_predicted_prob=getattr(prediction, 'raw_prob', prediction.predicted_prob),
            edge=prediction.edge,
            model_version=model_version or prediction.model_version,
            features=features.to_array().tolist(),
            feature_names=MarketFeatures.feature_names(),
            action=action,
            side_executed=prediction.side,
            count=count,
            price_cents=price_cents,
            total_cost_cents=price_cents * count,
            fees_cents=fees_cents,
            order_id=order_id,
            fill_latency_ms=latency_ms,
            market_bid_cents=market_bid,
            market_ask_cents=market_ask,
            market_volume=features.volume,
            hours_to_expiry=features.hours_to_expiry,
            confidence_breakdown=confidence_breakdown or {},
        )

        self._trades.append(record)
        self._pending_trades[record.trade_id] = record
        self._by_outcome[TradeOutcome.PENDING] += 1
        self.total_recorded += 1

        # Index by ticker
        self._by_ticker.setdefault(ticker, []).append(record.trade_id)

        log.debug(
            "trade_recorded",
            trade_id=record.trade_id,
            ticker=ticker,
            side=prediction.side,
            conf=f"{prediction.confidence:.3f}",
        )
        return record

    def resolve_trade(
        self,
        trade_id: str,
        outcome: TradeOutcome,
        exit_price_cents: int = 0,
        pnl_cents: int = 0,
        market_result: str = "",
    ) -> TradeRecord | None:
        """Mark a trade as resolved with its outcome."""
        record = self._pending_trades.pop(trade_id, None)
        if not record:
            # Search in main buffer
            for t in reversed(self._trades):
                if t.trade_id == trade_id:
                    record = t
                    break
        if not record:
            return None

        # Update outcome
        record.outcome = outcome
        record.exit_price_cents = exit_price_cents
        record.pnl_cents = pnl_cents
        record.market_result = market_result
        record.outcome_timestamp = time.time()
        record.hold_time_seconds = record.outcome_timestamp - record.timestamp

        if record.total_cost_cents > 0:
            record.pnl_pct = pnl_cents / record.total_cost_cents
        record.was_correct = (
            record.predicted_side == market_result if market_result else None
        )

        # Update counters
        self._by_outcome[TradeOutcome.PENDING] = max(0, self._by_outcome[TradeOutcome.PENDING] - 1)
        self._by_outcome[outcome] += 1
        if outcome not in (TradeOutcome.EXPIRED, TradeOutcome.CANCELLED):
            self.total_resolved += 1

        if outcome == TradeOutcome.WIN:
            self.total_wins += 1
        elif outcome == TradeOutcome.LOSS:
            self.total_losses += 1

        # Pin high-impact trades (capped at 500)
        if abs(pnl_cents) > 500:  # > $5 P&L
            self._important_trades.append(record)
            if len(self._important_trades) > 500:
                self._important_trades = self._important_trades[-500:]

        log.info(
            "trade_resolved",
            trade_id=trade_id,
            outcome=outcome.value,
            pnl=f"${pnl_cents / 100:.2f}",
            correct=record.was_correct,
        )
        return record

    # ── Record Market Snapshots ───────────────────────────────────────

    def record_snapshot(self, ticker: str, midpoint: float, spread: float, volume: float) -> None:
        """Record a market observation for regime detection."""
        snap = MarketSnapshot(
            ticker=ticker,
            timestamp=time.time(),
            midpoint=midpoint,
            spread=spread,
            volume=volume,
        )
        self._snapshots.append(snap)

    # ── Training Data Extraction ──────────────────────────────────────

    def get_training_data(
        self,
        min_trades: int = 50,
        only_resolved: bool = True,
        max_age_hours: float = 0,  # 0 = no limit
        holdout_pct: float = 0.0,  # Phase 16: reserve % for validation
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        """
        Extract feature matrix X and labels y for model retraining.

        Labels: 1.0 if market resolved YES, 0.0 if NO.
        This teaches the model P(YES settles) — the actual outcome —
        instead of the circular "was my prediction correct".

        Phase 16: Also returns sample weights that emphasize:
        - Recent trades (exponential recency)
        - Trades where we were CORRECT (reward good signals)
        - High-confidence trades that resolved (calibration feedback)
        """
        now = time.time()
        records = []
        seen_ids: set[str] = set()

        for t in self._trades:
            if only_resolved and t.outcome == TradeOutcome.PENDING:
                continue
            # Need a known market result (YES or NO) to create a label
            if t.market_result not in ("yes", "no"):
                continue
            if max_age_hours > 0 and (now - t.timestamp) > max_age_hours * 3600:
                continue
            if not t.features:
                continue
            if t.trade_id not in seen_ids:
                records.append(t)
                seen_ids.add(t.trade_id)

        # Also include important (pinned) trades
        for t in self._important_trades:
            if t.market_result in ("yes", "no") and t.features and t.trade_id not in seen_ids:
                records.append(t)
                seen_ids.add(t.trade_id)

        if len(records) < min_trades:
            log.info("insufficient_training_data", available=len(records), required=min_trades)
            return None

        # Handle feature dimension mismatch: old records may have fewer
        # features than the current model expects (60).
        # Pad shorter vectors with zeros so numpy can build a matrix.
        expected_dim = len(MarketFeatures.feature_names())  # 60
        padded = []
        for r in records:
            feat = list(r.features)
            if len(feat) < expected_dim:
                feat.extend([0.0] * (expected_dim - len(feat)))
            elif len(feat) > expected_dim:
                feat = feat[:expected_dim]
            padded.append(feat)

        X = np.array(padded, dtype=np.float32)
        # Label = 1.0 if market resolved YES, 0.0 if NO
        # This is the correct target: predict P(YES outcome)
        y = np.array(
            [1.0 if r.market_result == "yes" else 0.0 for r in records],
            dtype=np.float32,
        )

        log.info(
            "training_data_extracted",
            samples=len(records),
            positive_rate=f"{y.mean():.3f}",
        )

        # Phase 16: compute sample weights
        # Emphasize recent trades and those where we were correct
        # Down-weight bootstrap data once real trades accumulate
        real_count = sum(1 for r in records if r.source == "live")
        weights = np.ones(len(records), dtype=np.float32)
        for i, r in enumerate(records):
            # Recency: exponential decay, trades in last 24h get full weight
            age_hours = (now - r.timestamp) / 3600.0
            recency_weight = np.exp(-age_hours / 72.0)  # half-life ~72h
            weights[i] *= max(recency_weight, 0.3)  # floor at 30%

            # Hard example mining: trades where we were WRONG get 1.5×
            # weight.  The model already "knows" easy cases — the errors
            # are where it needs the most gradient signal.  This is the
            # standard approach in boosting / focal-loss literature.
            if r.was_correct is False:
                weights[i] *= 1.5
            # Correct predictions train normally (weight=1.0)

            # Bootstrap down-weighting: once we have enough real trades,
            # bootstrap data becomes less valuable (and potentially harmful
            # if it contains feature leakage from settlement prices).
            if r.source in ("bootstrap", "bootstrap_active"):
                if real_count >= 200:
                    weights[i] = 0.0  # exclude entirely
                elif real_count >= 50:
                    weights[i] *= 0.2  # heavy discount
                else:
                    weights[i] *= 0.5  # moderate discount even early

        # Normalize so weights average to 1.0
        # First, filter out zero-weight samples (excluded bootstrap)
        nonzero_mask = weights > 0
        if nonzero_mask.sum() < min_trades:
            # Not enough non-bootstrap data yet, keep everything
            pass
        else:
            X = X[nonzero_mask]
            y = y[nonzero_mask]
            weights = weights[nonzero_mask]

        if weights.sum() > 0:
            weights = weights * (len(weights) / weights.sum())

        # Phase 16: Feedback-resistant training — time-based holdout
        # Reserve the most recent holdout_pct of trades as validation
        # that the learner can use for champion/challenger comparison.
        # This prevents the model from training on data it will be
        # validated against, breaking the feedback loop.
        if holdout_pct > 0 and len(X) > min_trades:
            split_idx = int(len(X) * (1 - holdout_pct))
            if split_idx >= min_trades:
                holdout_size = len(X) - split_idx
                log.info("holdout_applied", train_size=split_idx,
                         holdout_size=holdout_size, holdout_pct=holdout_pct)
                X = X[:split_idx]
                y = y[:split_idx]
                weights = weights[:split_idx]

        return X, y, weights

    def get_recent_trades(self, n: int = 100, ticker: str | None = None) -> list[TradeRecord]:
        """Get most recent N trades, optionally filtered by ticker."""
        trades = list(self._trades)
        if ticker:
            trades = [t for t in trades if t.ticker == ticker]
        return trades[-n:]

    def get_pending_trades(self) -> list[TradeRecord]:
        """Get all trades awaiting resolution."""
        return list(self._pending_trades.values())

    def get_resolved_trades(self) -> list[TradeRecord]:
        """Get all trades that have been resolved (WIN/LOSS/BREAKEVEN only)."""
        return [
            t for t in self._trades
            if t.outcome not in (TradeOutcome.PENDING, TradeOutcome.EXPIRED, TradeOutcome.CANCELLED)
        ]

    # ── Statistics ────────────────────────────────────────────────────

    @property
    def win_rate(self) -> float:
        total = self.total_wins + self.total_losses
        return self.total_wins / total if total > 0 else 0.0

    @property
    def total_pnl_cents(self) -> int:
        return sum(t.pnl_cents for t in self._trades if t.outcome != TradeOutcome.PENDING)

    @property
    def avg_pnl_per_trade(self) -> float:
        resolved = [t for t in self._trades if t.outcome != TradeOutcome.PENDING]
        if not resolved:
            return 0.0
        return sum(t.pnl_cents for t in resolved) / len(resolved)

    @property
    def size(self) -> int:
        return len(self._trades)

    def prune_ticker_index(self) -> int:
        """Remove stale entries from _by_ticker that reference evicted trades.

        Called periodically to prevent unbounded growth from deque eviction.
        """
        active_ids = {t.trade_id for t in self._trades}
        pruned = 0
        empty_tickers = []
        for ticker, trade_ids in self._by_ticker.items():
            before = len(trade_ids)
            self._by_ticker[ticker] = [tid for tid in trade_ids if tid in active_ids]
            pruned += before - len(self._by_ticker[ticker])
            if not self._by_ticker[ticker]:
                empty_tickers.append(ticker)
        for ticker in empty_tickers:
            del self._by_ticker[ticker]
        return pruned

    def stats(self) -> dict[str, Any]:
        """Full memory statistics."""
        resolved = [t for t in self._trades if t.outcome != TradeOutcome.PENDING]
        return {
            "total_recorded": self.total_recorded,
            "total_resolved": self.total_resolved,
            "pending": len(self._pending_trades),
            "buffer_size": len(self._trades),
            "important_pinned": len(self._important_trades),
            "win_rate": f"{self.win_rate:.1%}",
            "total_pnl": f"${self.total_pnl_cents / 100:.2f}",
            "avg_pnl_per_trade": f"${self.avg_pnl_per_trade / 100:.2f}",
            "outcomes": {k.value: v for k, v in self._by_outcome.items()},
            "unique_tickers": len(self._by_ticker),
            "category_analytics": self.category_analytics(),
        }

    def category_analytics(self) -> dict[str, dict[str, Any]]:
        """Phase 15: Detailed per-category analytics from memory."""
        cats: dict[str, list] = {}
        for t in self._trades:
            if t.outcome in (TradeOutcome.PENDING, TradeOutcome.CANCELLED, TradeOutcome.EXPIRED):
                continue
            cat = t.category or "unknown"
            cats.setdefault(cat, []).append(t)

        result = {}
        for cat, trades in sorted(cats.items()):
            wins = sum(1 for t in trades if t.outcome == TradeOutcome.WIN)
            losses = sum(1 for t in trades if t.outcome == TradeOutcome.LOSS)
            pnls = [t.pnl_cents / 100.0 for t in trades]
            total_pnl = sum(pnls)
            # Streak tracking
            streak = 0
            for t in reversed(trades):
                if t.outcome == TradeOutcome.LOSS:
                    streak += 1
                else:
                    break
            result[cat] = {
                "trades": len(trades),
                "wins": wins,
                "losses": losses,
                "win_rate": round(wins / len(trades), 3) if trades else 0.0,
                "total_pnl": round(total_pnl, 2),
                "avg_pnl": round(total_pnl / len(trades), 2) if trades else 0.0,
                "best": round(max(pnls), 2) if pnls else 0.0,
                "worst": round(min(pnls), 2) if pnls else 0.0,
                "current_loss_streak": streak,
            }
        return result

    # ── Persistence ───────────────────────────────────────────────────

    def save(self, path: str | None = None) -> None:
        """Save memory to disk as JSON."""
        save_path = path or self.persist_path
        if not save_path:
            return

        # Prune stale ticker index entries before saving
        self.prune_ticker_index()

        data = {
            "version": 1,
            "total_recorded": self.total_recorded,
            "total_resolved": self.total_resolved,
            "total_wins": self.total_wins,
            "total_losses": self.total_losses,
            "trades": [t.to_dict() for t in self._trades],
            "important_trades": [t.to_dict() for t in self._important_trades],
        }

        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

        log.info("memory_saved", path=save_path, trades=len(self._trades))

    def load(self, path: str | None = None) -> None:
        """Load memory from disk."""
        load_path = path or self.persist_path
        if not load_path or not Path(load_path).exists():
            return

        try:
            with open(load_path) as f:
                data = json.load(f)

            self.total_recorded = data.get("total_recorded", 0)
            self.total_resolved = data.get("total_resolved", 0)
            self.total_wins = data.get("total_wins", 0)
            self.total_losses = data.get("total_losses", 0)

            # Phase 24: Backfill categories on load — historical trades
            # were recorded before category detection was wired in,
            # leaving 700+ trades as "unknown" which poisons retirement.
            from app.frankenstein.categories import detect_category as _detect_cat

            backfilled = 0
            for td in data.get("trades", []):
                record = TradeRecord.from_dict(td)

                # Backfill missing/unknown categories from ticker + title
                if not record.category or record.category in ("unknown", ""):
                    detected = _detect_cat(
                        record.market_title,
                        category_hint="",
                        ticker=record.ticker,
                    )
                    if detected and detected != "general":
                        record.category = detected
                        backfilled += 1

                self._trades.append(record)
                if record.outcome == TradeOutcome.PENDING:
                    self._pending_trades[record.trade_id] = record
                self._by_ticker.setdefault(record.ticker, []).append(record.trade_id)
                # Rebuild outcome counters
                self._by_outcome[record.outcome] = self._by_outcome.get(record.outcome, 0) + 1

            if backfilled:
                log.info("memory_categories_backfilled", count=backfilled)

            for td in data.get("important_trades", []):
                self._important_trades.append(TradeRecord.from_dict(td))

            log.info("memory_loaded", path=load_path, trades=len(self._trades))
        except Exception as e:
            log.error("memory_load_failed", error=str(e))

    def clear(self) -> None:
        """Wipe all memory."""
        self._trades.clear()
        self._snapshots.clear()
        self._important_trades.clear()
        self._pending_trades.clear()
        self._by_ticker.clear()
        self._by_outcome = {o: 0 for o in TradeOutcome}
        self.total_recorded = 0
        self.total_resolved = 0
        self.total_wins = 0
        self.total_losses = 0
        log.warning("memory_cleared")

    def purge_bootstrap_data(self) -> dict[str, Any]:
        """Remove all bootstrap/synthetic records from memory.

        Used after deploying fixes to clear poisoned training data that
        was generated with settlement-price leakage.  Keeps all live trades.
        """
        before = len(self._trades)

        # Partition into keep / remove
        kept: deque[TradeRecord] = deque(maxlen=self.max_trades)
        kept_important: list[TradeRecord] = []
        removed = 0

        for t in self._trades:
            is_bootstrap = (
                getattr(t, 'source', '') in ('bootstrap', 'bootstrap_active')
                or (t.model_version or '').startswith('bootstrap')
                or (t.order_id or '').startswith('bootstrap-')
            )
            if is_bootstrap:
                removed += 1
            else:
                kept.append(t)

        for t in self._important_trades:
            is_bootstrap = (
                getattr(t, 'source', '') in ('bootstrap', 'bootstrap_active')
                or (t.model_version or '').startswith('bootstrap')
                or (t.order_id or '').startswith('bootstrap-')
            )
            if not is_bootstrap:
                kept_important.append(t)

        self._trades = kept
        self._important_trades = kept_important

        # Rebuild all indexes from scratch
        self._rebuild_indexes()
        self.save()

        after = len(self._trades)
        log.warning("bootstrap_data_purged", removed=removed, remaining=after)
        return {"removed": removed, "remaining": after, "before": before}

    def _rebuild_indexes(self) -> None:
        """Rebuild all indexes and counters from the trades list."""
        self._by_ticker.clear()
        self._by_outcome = {o: 0 for o in TradeOutcome}
        self._pending_trades.clear()
        self.total_recorded = len(self._trades)
        self.total_resolved = 0
        self.total_wins = 0
        self.total_losses = 0

        for t in self._trades:
            self._by_ticker.setdefault(t.ticker, []).append(t.trade_id)
            self._by_outcome[t.outcome] = self._by_outcome.get(t.outcome, 0) + 1
            if t.outcome == TradeOutcome.PENDING:
                self._pending_trades[t.trade_id] = t
            elif t.outcome not in (TradeOutcome.CANCELLED, TradeOutcome.EXPIRED):
                self.total_resolved += 1
            if t.outcome == TradeOutcome.WIN:
                self.total_wins += 1
            elif t.outcome == TradeOutcome.LOSS:
                self.total_losses += 1
