"""
Frankenstein — Outcome Resolver. 🧟📊

Checks for settled markets and resolves pending trades to WIN/LOSS/EXPIRED.

Resolution strategy (tries 4 methods):
  1. Kalshi settlements API (real/demo trading)
  2. Market status check via API (checks if settled)
  3. Paper trading: extreme price (≥0.99/≤0.01)
  4. Timeout after 48 hours → expired

Extracted from brain.py _resolve_outcomes_task().
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.frankenstein.constants import (
    EXTREME_PRICE_THRESHOLD_NO,
    EXTREME_PRICE_THRESHOLD_YES,
    TAKER_FEE_CENTS,
    USE_MAKER_ORDERS,
)
from app.frankenstein.event_bus import Event, EventBus, EventType
from app.frankenstein.memory import TradeMemory, TradeOutcome, TradeRecord
from app.logging_config import get_logger
from app.pipeline import market_cache

log = get_logger("frankenstein.resolver")


class OutcomeResolver:
    """Resolves pending trades by checking market settlements."""

    def __init__(
        self,
        memory: TradeMemory,
        model: Any,  # PredictionModel — avoided hard import to reduce coupling
        event_bus: EventBus | None = None,
        *,
        sports_detector: Any | None = None,
        sports_monitor: Any | None = None,
    ) -> None:
        self.memory = memory
        self._model = model
        self._bus = event_bus

        # Sports (injected later by brain)
        self._sports_detector = sports_detector
        self._sports_monitor = sports_monitor
        self._sports_predictor_v2 = None  # Phase 30: injected by brain
        self._sports_risk = None           # Phase 30: injected by brain

        # Phase 35: Market harvester (injected by brain)
        self._harvester: Any = None

        # {category: {"wins": int, "losses": int}}
        self.category_stats: dict[str, dict[str, int]] = {}

    # ── Main Task ─────────────────────────────────────────────────────

    async def resolve(self) -> int:
        """Check for settled markets and resolve pending trades.

        Returns the number of trades resolved.
        """
        pending = self.memory.get_pending_trades()
        if not pending:
            return 0

        resolved_count = 0

        # Batch-fetch recent settlements from Kalshi
        settlements_by_ticker: dict[str, Any] = {}
        try:
            from app.state import state as _st
            if _st.kalshi_api:
                slist, _ = await _st.kalshi_api.portfolio.list_settlements(limit=200)
                for s in slist:
                    settlements_by_ticker[s.ticker] = s
        except Exception as e:
            log.debug("settlement_fetch_error", error=str(e))

        # Phase 28: Batch-fetch market statuses for all pending tickers at once.
        # This is MUCH faster than individual API calls per trade (N → 1 call).
        # Phase 35c: Add timeout to prevent hanging on slow API
        market_statuses: dict[str, Any] = {}
        try:
            from app.state import state as _st
            if _st.kalshi_api:
                # Collect unique tickers from pending trades
                pending_tickers = list({t.ticker for t in pending})
                # Fetch in batches of 50 (API may limit) with timeout
                for i in range(0, len(pending_tickers), 50):
                    batch_tickers = pending_tickers[i:i+50]
                    for tk in batch_tickers:
                        try:
                            async with asyncio.timeout(5.0):  # 5s per market
                                mkt = await _st.kalshi_api.markets.get_market(tk)
                                if mkt:
                                    market_statuses[tk] = mkt
                        except asyncio.TimeoutError:
                            log.debug("market_fetch_timeout", ticker=tk)
                        except Exception:
                            pass  # Individual fetch failure is fine
        except Exception as e:
            log.debug("batch_market_status_error", error=str(e))

        for trade in pending:
            try:
                # Skip exit/sell records
                if trade.action == "sell":
                    self.memory.resolve_trade(trade.trade_id, TradeOutcome.BREAKEVEN)
                    continue

                resolved = (
                    self._try_settlement_api(trade, settlements_by_ticker)
                    or await self._try_market_status(trade, market_statuses)
                    or self._try_paper_extreme_price(trade)
                    or self._try_timeout(trade)
                )
                if resolved:
                    resolved_count += 1

            except Exception as e:
                log.debug("outcome_check_error", ticker=trade.ticker, error=str(e))

        if resolved_count > 0:
            log.info(
                "🧟📊 OUTCOMES_RESOLVED",
                count=resolved_count,
                remaining=len(pending) - resolved_count,
            )

            # Publish event
            if self._bus:
                await self._bus.publish(Event(
                    type=EventType.OUTCOME_RESOLVED,
                    data={"resolved_count": resolved_count},
                    source="resolver",
                ))

        # Phase 35: Feed ALL settlements to market harvester for free training data.
        # This includes markets we didn't trade — every settlement is a training sample.
        if self._harvester and settlements_by_ticker:
            try:
                settled_map: dict[str, str] = {}
                for ticker, settlement in settlements_by_ticker.items():
                    result = getattr(settlement, "market_result", None)
                    if result is not None:
                        r_str = result.value.lower() if hasattr(result, "value") else str(result).lower()
                        if r_str in ("yes", "no"):
                            settled_map[ticker] = r_str
                if settled_map:
                    self._harvester.try_harvest(settled_map)
            except Exception as e:
                log.debug("harvester_feed_error", error=str(e))

        return resolved_count

    # ── Method 1: Settlements API ─────────────────────────────────────

    def _try_settlement_api(
        self,
        trade: TradeRecord,
        settlements: dict[str, Any],
    ) -> bool:
        settlement = settlements.get(trade.ticker)
        if not settlement or settlement.market_result is None:
            return False

        result_str = settlement.market_result.value.lower()
        correct = trade.predicted_side == result_str

        # Record calibration data
        self._record_calibration(trade, result_str)

        if result_str == "void":
            self.memory.resolve_trade(trade.trade_id, TradeOutcome.CANCELLED)
            self._settle_paper_position(trade.ticker, "void")
            return True

        pnl_cents = self._compute_pnl(trade, correct)
        outcome = TradeOutcome.WIN if correct else TradeOutcome.LOSS
        self.memory.resolve_trade(
            trade.trade_id, outcome,
            pnl_cents=pnl_cents, market_result=result_str,
        )
        self._settle_paper_position(trade.ticker, result_str)
        self._report_sports_outcome(trade, pnl_cents)
        self._track_category_outcome(trade, correct)
        return True

    # ── Method 2: Market Status ───────────────────────────────────────

    async def _try_market_status(self, trade: TradeRecord, prefetched: dict[str, Any] | None = None) -> bool:
        market_settled = False
        market_result_str = None

        # Check cache first (free)
        cached_market = market_cache.get(trade.ticker)
        if cached_market:
            status_val = (
                cached_market.status.value
                if hasattr(cached_market.status, "value")
                else str(cached_market.status)
            )
            if status_val.lower() in ("settled", "closed"):
                market_settled = True
                final_price = float(cached_market.last_price or cached_market.midpoint or 0.5)
                if isinstance(final_price, int):
                    final_price = final_price / 100
                if final_price >= EXTREME_PRICE_THRESHOLD_YES:
                    market_result_str = "yes"
                elif final_price <= EXTREME_PRICE_THRESHOLD_NO:
                    market_result_str = "no"

        # Phase 28: Use pre-fetched batch data (avoids individual API calls)
        if not market_settled and prefetched and trade.ticker in prefetched:
            mkt = prefetched[trade.ticker]
            status_val = (
                mkt.status.value
                if hasattr(mkt.status, "value")
                else str(mkt.status)
            )
            if status_val.lower() in ("settled", "closed"):
                market_settled = True
                result_attr = getattr(mkt, "result", None) or getattr(mkt, "market_result", None)
                if result_attr:
                    market_result_str = (
                        result_attr.value.lower()
                        if hasattr(result_attr, "value")
                        else str(result_attr).lower()
                    )
                else:
                    fp = float(mkt.last_price or 0.5)
                    if isinstance(fp, int):
                        fp = fp / 100
                    if fp >= EXTREME_PRICE_THRESHOLD_YES:
                        market_result_str = "yes"
                    elif fp <= EXTREME_PRICE_THRESHOLD_NO:
                        market_result_str = "no"

        # Fallback: if cache and batch both missed, try individual API call
        if not market_settled:
            try:
                from app.state import state as _st
                if _st.kalshi_api:
                    mkt = await _st.kalshi_api.markets.get_market(trade.ticker)
                    status_val = (
                        mkt.status.value
                        if hasattr(mkt.status, "value")
                        else str(mkt.status)
                    )
                    if status_val.lower() in ("settled", "closed"):
                        market_settled = True
                        result_attr = getattr(mkt, "result", None) or getattr(mkt, "market_result", None)
                        if result_attr:
                            market_result_str = (
                                result_attr.value.lower()
                                if hasattr(result_attr, "value")
                                else str(result_attr).lower()
                            )
                        else:
                            fp = float(mkt.last_price or 0.5)
                            if isinstance(fp, int):
                                fp = fp / 100
                            if fp >= EXTREME_PRICE_THRESHOLD_YES:
                                market_result_str = "yes"
                            elif fp <= EXTREME_PRICE_THRESHOLD_NO:
                                market_result_str = "no"
            except Exception:
                pass

        if not market_settled:
            return False

        if market_result_str:
            correct = trade.predicted_side == market_result_str
            self._record_calibration(trade, market_result_str)
            pnl_cents = self._compute_pnl(trade, correct)
            outcome = TradeOutcome.WIN if correct else TradeOutcome.LOSS
            self.memory.resolve_trade(
                trade.trade_id, outcome,
                pnl_cents=pnl_cents, market_result=market_result_str,
            )
            self._settle_paper_position(trade.ticker, market_result_str)
            self._report_sports_outcome(trade, pnl_cents)
            self._track_category_outcome(trade, correct)
        else:
            self.memory.resolve_trade(trade.trade_id, TradeOutcome.EXPIRED)
            self._settle_paper_position(trade.ticker, "expired")

        return True

    # ── Method 3: Paper Trading Extreme Price ─────────────────────────

    def _try_paper_extreme_price(self, trade: TradeRecord) -> bool:
        try:
            cached = market_cache.get(trade.ticker)
            if not cached:
                return False

            current_price = float(cached.last_price or cached.midpoint or 0)
            if isinstance(current_price, int):
                current_price = current_price / 100

            # Phase 25: Tightened from 0.95/0.05 to 0.98/0.02.
            # At 95% there's still a 5% chance we assign the wrong label,
            # which pollutes training data.  At 98% the outcome is near-certain.
            from app.frankenstein.constants import (
                EXTREME_PRICE_THRESHOLD_YES,
                EXTREME_PRICE_THRESHOLD_NO,
            )
            if current_price >= EXTREME_PRICE_THRESHOLD_YES:
                correct = trade.predicted_side == "yes"
                pnl_cents = self._compute_pnl(trade, correct)
                outcome = TradeOutcome.WIN if correct else TradeOutcome.LOSS
                self.memory.resolve_trade(
                    trade.trade_id, outcome,
                    pnl_cents=pnl_cents, market_result="yes",
                )
                self._settle_paper_position(trade.ticker, "yes")
                self._track_category_outcome(trade, correct)
                return True

            if current_price <= EXTREME_PRICE_THRESHOLD_NO:
                correct = trade.predicted_side == "no"
                pnl_cents = self._compute_pnl(trade, correct)
                outcome = TradeOutcome.WIN if correct else TradeOutcome.LOSS
                self.memory.resolve_trade(
                    trade.trade_id, outcome,
                    pnl_cents=pnl_cents, market_result="no",
                )
                self._settle_paper_position(trade.ticker, "no")
                self._track_category_outcome(trade, correct)
                return True

        except Exception:
            pass
        return False

    # ── Method 4: Timeout ─────────────────────────────────────────────

    def _try_timeout(self, trade: TradeRecord) -> bool:
        from app.frankenstein.constants import (
            TIMEOUT_HOURS,
            TIMEOUT_PRICE_YES,
            TIMEOUT_PRICE_NO,
        )
        elapsed = time.time() - trade.timestamp
        timeout_seconds = TIMEOUT_HOURS * 3600
        if elapsed > timeout_seconds:
            # Phase 25: Tightened from 6h/0.75 to 24h/0.90.
            # Old: 75% threshold = 25% chance of wrong label = massive noise.
            # New: 90% threshold = only resolve when near-certain.
            # Price inconclusive → EXPIRED (don't inject noisy labels).
            cached = market_cache.get(trade.ticker)
            if cached:
                cp = float(cached.last_price or cached.midpoint or 0)
                if isinstance(cp, int):
                    cp = cp / 100
                if cp >= TIMEOUT_PRICE_YES:
                    correct = trade.predicted_side == "yes"
                    pnl_cents = self._compute_pnl(trade, correct)
                    outcome = TradeOutcome.WIN if correct else TradeOutcome.LOSS
                    self.memory.resolve_trade(
                        trade.trade_id, outcome,
                        pnl_cents=pnl_cents, market_result="yes",
                    )
                    self._settle_paper_position(trade.ticker, "yes")
                    self._track_category_outcome(trade, correct)
                    return True
                elif cp <= TIMEOUT_PRICE_NO:
                    correct = trade.predicted_side == "no"
                    pnl_cents = self._compute_pnl(trade, correct)
                    outcome = TradeOutcome.WIN if correct else TradeOutcome.LOSS
                    self.memory.resolve_trade(
                        trade.trade_id, outcome,
                        pnl_cents=pnl_cents, market_result="no",
                    )
                    self._settle_paper_position(trade.ticker, "no")
                    self._track_category_outcome(trade, correct)
                    return True
            # Price inconclusive — expire without injecting a label.
            # This is BETTER than assigning a wrong label.
            self.memory.resolve_trade(trade.trade_id, TradeOutcome.EXPIRED)
            self._settle_paper_position(trade.ticker, "expired")
            return True
        return False

    # ── Helpers ───────────────────────────────────────────────────────

    def _compute_pnl(self, trade: TradeRecord, correct: bool) -> int:
        """Compute PnL in cents for a resolved trade."""
        if correct:
            sell_fee = 0 if USE_MAKER_ORDERS else TAKER_FEE_CENTS * trade.count
            return trade.count * 100 - trade.total_cost_cents - sell_fee
        else:
            return -trade.total_cost_cents

    def _settle_paper_position(self, ticker: str, result: str) -> None:
        """Credit/debit the paper trader balance on market settlement."""
        try:
            from app.state import state as _st
            sim = getattr(_st, "paper_simulator", None)
            if sim is not None:
                sim.settle_market(ticker, result)
        except Exception as e:
            log.debug("paper_settlement_error", ticker=ticker, error=str(e))

    def _record_calibration(self, trade: TradeRecord, result_str: str) -> None:
        """Record calibration data for model tracking."""
        if result_str in ("yes", "no") and hasattr(self._model, "calibration"):
            actual_yes = 1 if result_str == "yes" else 0
            raw_p = getattr(trade, "raw_predicted_prob", 0.0) or trade.predicted_prob
            self._model.calibration.record(raw_p, actual_yes)

    def _report_sports_outcome(self, trade: TradeRecord, pnl_cents: int) -> None:
        """Report trade outcome to sports monitor.

        Note: Category win/loss tracking is handled exclusively by
        _track_category_outcome() to avoid double-counting.
        """
        if not self._sports_monitor or not self._sports_detector:
            return
        try:
            from app.kalshi.models import Market as _MktModel
            info = self._sports_detector.detect(
                _MktModel(
                    ticker=trade.ticker,
                    event_ticker=getattr(trade, "event_ticker", "") or "",
                )
            )
            if info.is_sports:
                self._sports_monitor.record_trade_outcome(
                    sport_id=info.sport_id,
                    strategy=trade.model_version or "vegas_baseline",
                    pnl_cents=pnl_cents,
                    edge=getattr(trade, "edge", 0.0),
                    is_live=info.is_live,
                )
        except Exception as e:
            log.debug("sports_monitor_report_error", error=str(e))

    def _track_category_outcome(self, trade: TradeRecord, correct: bool) -> None:
        """Track outcome by category for circuit breaker & gating."""
        try:
            from app.frankenstein.categories import detect_category
            cat = detect_category(
                trade.market_title or "", trade.category or "",
                ticker=trade.ticker,
            )
            if cat not in self.category_stats:
                self.category_stats[cat] = {"wins": 0, "losses": 0}
            if correct:
                self.category_stats[cat]["wins"] += 1
            else:
                self.category_stats[cat]["losses"] += 1
        except Exception:
            pass

        # Phase 30: Clean up sports risk positions (fixes the leak)
        try:
            if self._sports_risk:
                self._sports_risk.remove_position(trade.ticker)
        except Exception:
            pass

        # Phase 30: Feed V2 predictor circuit breaker
        try:
            if self._sports_predictor_v2 and self._sports_detector:
                from app.kalshi.models import Market as _MktModel
                info = self._sports_detector.detect(
                    _MktModel(
                        ticker=trade.ticker,
                        event_ticker=getattr(trade, "event_ticker", "") or "",
                    )
                )
                if info.is_sports:
                    pnl_cents = self._compute_pnl(trade, correct)
                    self._sports_predictor_v2.record_outcome(
                        sport_id=info.sport_id,
                        won=correct,
                        pnl_cents=pnl_cents,
                    )
                    # Also clean up hedger
                    self._sports_predictor_v2.hedger.remove_position(
                        event_ticker=getattr(trade, "event_ticker", "") or "",
                        ticker=trade.ticker,
                    )
        except Exception:
            pass
