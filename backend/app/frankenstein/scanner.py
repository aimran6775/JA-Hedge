"""
Frankenstein — Market Scanner. 🧟🔍

The core trading intelligence: scans markets, filters candidates,
computes features, predicts outcomes, evaluates signals, and selects
trades to execute.

Extracted from brain.py _scan_and_trade() — the ~700-line method
that is the heart of the system.

The Scanner does NOT hold state about lifecycle (awaken/sleep) or
scheduling.  It receives injected dependencies and performs one
scan cycle per call.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from app.ai.features import FeatureEngine, MarketFeatures
from app.ai.models import Prediction, PredictionModel, XGBoostPredictor
from app.engine.advanced_risk import AdvancedRiskManager
from app.engine.execution import ExecutionEngine
from app.frankenstein.categories import CategoryStrategyRegistry, detect_category
from app.frankenstein.confidence import ConfidenceBreakdown, ConfidenceScorer
from app.frankenstein.constants import (
    CATEGORY_EDGE_CAPS,
    MAX_DAILY_TRADES,
    MAX_PER_CATEGORY,
    MAX_PER_EVENT,
    MIN_PRICE_FLOOR_CENTS,
    MIN_PRICE_FLOOR_LEARNING_CENTS,
    ROUND_TRIP_FEE_CENTS,
    USE_MAKER_ORDERS,
    round_trip_fee_pct,
)
from app.frankenstein.event_bus import Event, EventBus, EventType
from app.frankenstein.fill_predictor import FillPredictor
from app.frankenstein.learner import OnlineLearner
from app.frankenstein.memory import TradeMemory
from app.frankenstein.order_manager import OrderManager
from app.frankenstein.performance import PerformanceTracker
from app.frankenstein.strategy import AdaptiveStrategy, StrategyParams
from app.kalshi.models import Market, MarketStatus
from app.logging_config import get_logger
from app.pipeline import market_cache
from app.production import ExchangeSchedule

log = get_logger("frankenstein.scanner")


class MarketScanner:
    """
    One-shot market scanner — call ``scan()`` each cycle.

    Dependencies are injected via the constructor so the scanner
    is testable in isolation.
    """

    def __init__(
        self,
        model: XGBoostPredictor,
        feature_engine: FeatureEngine,
        execution_engine: ExecutionEngine,
        strategy: AdaptiveStrategy,
        memory: TradeMemory,
        learner: OnlineLearner,
        performance: PerformanceTracker,
        categories: CategoryStrategyRegistry,
        order_manager: OrderManager,
        adv_risk: AdvancedRiskManager,
        schedule: ExchangeSchedule,
        event_bus: EventBus | None = None,
        *,
        capital_allocator: Any | None = None,
        fill_predictor: FillPredictor | None = None,
        sports_detector: Any | None = None,
        sports_predictor: Any | None = None,
        sports_feat: Any | None = None,
        sports_risk: Any | None = None,
        sports_only: bool = True,
        category_models: dict[str, XGBoostPredictor] | None = None,
    ) -> None:
        self._model = model
        self._features = feature_engine
        self._execution = execution_engine
        self._strategy = strategy
        self.memory = memory
        self._learner = learner
        self._performance = performance
        self._categories = categories
        self._order_mgr = order_manager
        self._adv_risk = adv_risk
        self._schedule = schedule
        self._bus = event_bus
        self._capital = capital_allocator  # Phase 3+4
        self._fill_pred = fill_predictor   # Phase 5

        # Sports
        self._sports_detector = sports_detector
        self._sports_predictor = sports_predictor
        self._sports_feat = sports_feat
        self._sports_risk = sports_risk
        self._sports_only = sports_only

        # Category specialist models
        self._category_models: dict[str, XGBoostPredictor] = category_models or {}

        # Cooldowns
        self._recently_traded: dict[str, float] = {}
        self._recently_traded_events: dict[str, float] = {}
        self._trade_cooldown_seconds: float = 30.0    # Phase 27: 30s ticker cooldown (was 60)
        self._event_cooldown_seconds: float = 15.0    # Phase 27: 15s event cooldown (was 30)

    # ── Learning-Mode Detection ───────────────────────────────────────

    def _is_in_learning_mode(self) -> bool:
        """
        Determine if we should be in learning mode.

        Phase 25b FIX: Previously used `not model.is_trained`, which was
        wrong because a stale checkpoint loaded from disk makes is_trained=True
        even though we have ZERO usable training data.

        Now checks the actual training data availability: how many resolved
        trades have definitive market_result (yes/no)?  If we have fewer than
        MIN_TRAINING_SAMPLES trades with real outcomes, we're still learning.
        """
        from app.frankenstein.constants import MIN_TRAINING_SAMPLES

        usable = 0
        for t in self.memory._trades:
            if t.market_result in ("yes", "no") and t.features:
                usable += 1
                if usable >= MIN_TRAINING_SAMPLES:
                    return False  # Have enough real data
        return True  # Still learning

    # ── Main Scan ─────────────────────────────────────────────────────

    async def scan(self, state: Any) -> dict[str, Any]:
        """
        One full scan cycle: filter → features → predict → evaluate → execute.

        ``state`` is the FrankensteinState dataclass from brain.py.

        Returns a scan_debug dict for the status API.
        """
        start = time.monotonic()
        state.total_scans += 1

        # ── Daily trade reset ─────────────────────────────────────
        from datetime import datetime, timezone as _tz

        _today = datetime.now(_tz.utc).strftime("%Y-%m-%d")
        if state.daily_trade_date != _today:
            state.daily_trade_count = 0
            state.daily_trade_date = _today

        if state.daily_trade_count >= MAX_DAILY_TRADES:
            return {"exit": "daily_trade_cap_reached",
                    "daily_trades": state.daily_trade_count, "cap": MAX_DAILY_TRADES}

        # ── Circuit breaker ───────────────────────────────────────
        from app.frankenstein.constants import CIRCUIT_BREAKER_COOLDOWN_HOURS

        if state.circuit_breaker_triggered:
            elapsed_hours = (time.time() - state.circuit_breaker_triggered_at) / 3600
            if elapsed_hours < CIRCUIT_BREAKER_COOLDOWN_HOURS:
                return {"exit": "circuit_breaker_active",
                        "hours_remaining": round(CIRCUIT_BREAKER_COOLDOWN_HOURS - elapsed_hours, 1)}
            else:
                state.circuit_breaker_triggered = False
                log.info("🧟🔄 Circuit breaker cooldown expired, resuming trading")

        # Exchange schedule
        _, session = ExchangeSchedule.should_trade()
        liquidity = ExchangeSchedule.liquidity_factor()

        # 1. Active markets
        markets = market_cache.get_active()
        if not markets:
            return {"exit": "no_active_markets", "cache_total": market_cache.count}

        # Cleanup stale orders
        await self._order_mgr.cleanup_stale_orders()

        # 2. Filter candidates
        candidates = self._filter_candidates(markets)
        if not candidates:
            # Phase 9: Diagnostic logging for supply gaps
            if state.total_scans % 60 == 0:  # Log every ~30 min (60 scans × 30s)
                log.info("no_candidates_diagnostic",
                         active_markets=len(markets),
                         session=session,
                         sports_only=self._sports_only)
            return {"exit": "no_candidates_after_filter",
                    "active_markets": len(markets), "session": session,
                    "sports_only": self._sports_only}

        # 3. Pre-filter
        candidates = self._pre_filter(candidates)
        if not candidates:
            return {"exit": "all_failed_prefilter"}

        # 3b. Populate price history buffers
        for m in candidates:
            mid = float(m.midpoint or m.last_price or 0)
            vol = float(m.volume or 0)
            oi = float(m.open_interest or 0)
            spread = float(m.spread or 0)
            if mid > 0:
                self._features.update(m.ticker, mid, vol, oi, spread)

        # 3c. Seed price histories from Kalshi candles
        await self._seed_price_histories(candidates)

        # 3d. Enrich orderbook depth
        await self._enrich_orderbook_depth(candidates[:20])

        # 4. Compute features
        features_list = [self._features.compute(m) for m in candidates]

        # 4a. Feature completeness gate
        candidates, features_list = self._feature_completeness_gate(candidates, features_list)
        if not candidates:
            return {"exit": "all_failed_feature_gate"}

        # 4b. Cross-event probability arbitrage
        self._inject_event_prob_sums(candidates, features_list)

        # 4c. Intelligence Hub enrichment
        self._intelligence_enrich(candidates, features_list)

        # 4d. Batch predict
        predictions = self._model.predict_batch(features_list)

        # 4e. Category specialist override
        self._category_specialist_override(candidates, features_list, predictions)

        # 5. Evaluate signals & build trade candidates
        params = self._strategy.params
        trade_candidates = self._evaluate_signals(
            candidates, features_list, predictions, params, state, liquidity,
        )

        # Strategy engine merge
        self._merge_strategy_engine(candidates, predictions, trade_candidates, params)

        # Phase 17: Rank by composite score — EV * fill probability proxy
        # Tighter spreads → higher fill probability → rank higher
        def _rank_score(c: dict) -> float:
            ev = c["ev"]
            spread = c["features"].spread  # 0-1 range
            # Spread penalty: 1¢ spread → 1.0x, 5¢ → 0.7x, 10¢ → 0.5x
            spread_factor = max(0.3, 1.0 - spread * 5.0)
            return ev * spread_factor

        trade_candidates.sort(key=_rank_score, reverse=True)

        _daily_remaining = MAX_DAILY_TRADES - state.daily_trade_count
        _open = self._count_open_positions()
        _position_room = max(0, params.max_simultaneous_positions - _open)
        max_trades_per_scan = max(
            1,  # ALWAYS allow at least 1 trade per scan
            min(_position_room, 12, _daily_remaining),  # Phase 27: up to 12 per scan (was 7)
        )

        # Execute top trades
        scan_debug = await self._execute_top(
            trade_candidates, max_trades_per_scan, candidates, state, params,
        )

        elapsed = (time.monotonic() - start) * 1000
        state.current_scan_time_ms = elapsed
        state.last_scan_time = time.time()
        scan_debug["candidates"] = len(candidates)
        scan_debug["ms"] = round(elapsed, 1)

        if scan_debug.get("exec_successes", 0) > 0 or scan_debug.get("trade_candidates", 0) > 0:
            log.info(
                "🧟 SCAN",
                candidates=len(candidates),
                signals=scan_debug.get("signals", 0),
                trade_candidates=scan_debug.get("trade_candidates", 0),
                max_trades=max_trades_per_scan,
                executed=scan_debug.get("exec_successes", 0),
                rejected=scan_debug.get("exec_rejections", 0) + scan_debug.get("portfolio_rejections", 0),
                ms=f"{elapsed:.1f}",
                gen=state.generation,
            )

        return scan_debug

    # ── Candidate Filtering ───────────────────────────────────────────

    def _filter_candidates(self, markets: list[Market]) -> list[Market]:
        """Filter markets to tradeable candidates.

        MAKER MODE AWARE: When USE_MAKER_ORDERS is True, we don't need
        existing liquidity (bid/ask/volume).  We only need a price reference
        to compute features and evaluate edge.  We CREATE liquidity by
        posting limit orders — that's the whole maker strategy.
        """
        params = self._strategy.params
        candidates = []

        # Blacklist market prefixes with proven terrible win rates.
        # Phase 27: Removed KXBTC15M/KXETH15M from junk — bootstrap data trained on these.
        # Keep only truly junk prefixes.
        JUNK_PREFIXES = (
            "KXMVE", "KXSPOTSTREAMGLOBAL", "KXPARLAY",
            # Proven losers (data from 1192 trades):
            "KXEPLGOAL", "KXEPLFIRSTGOAL",     # EPL goal markets: 2-5% WR
            "KXMVECROSSCATEGORY",                # Cross-category esports: 5% WR
            "KXNCAAMB1HSPREAD",                  # NCAA 1H spread: 13% WR
            "KXQUICKSETTLE",                     # Quick-settle: 34% WR, -$52 PnL
        )

        max_spread = params.max_spread_cents
        if self._execution._risk_manager:
            risk_spread = self._execution._risk_manager.limits.max_spread_cents
            max_spread = min(max_spread, risk_spread)

        for m in markets:
            if m.status not in (MarketStatus.ACTIVE, MarketStatus.OPEN):
                continue
            ticker_upper = (m.ticker or "").upper()
            if ticker_upper.startswith(JUNK_PREFIXES):
                continue

            # ── Price reference: need at least SOME price to evaluate ──
            # Try dollar-based fields first, then cents-based fallback
            bid = float(m.yes_bid or 0)
            ask = float(m.yes_ask or 0)
            last = float(m.last_price or 0)

            # Cents-based fallback (some API responses only include cents)
            if bid == 0 and m.yes_bid_cents and m.yes_bid_cents > 0:
                bid = m.yes_bid_cents / 100.0
            if ask == 0 and m.yes_ask_cents and m.yes_ask_cents > 0:
                ask = m.yes_ask_cents / 100.0
            if last == 0 and m.last_price_cents and m.last_price_cents > 0:
                last = m.last_price_cents / 100.0

            # Compute midpoint from best available data
            if bid > 0 and ask > 0:
                mid = (bid + ask) / 2.0
            elif last > 0:
                mid = last
            elif bid > 0:
                mid = bid
            elif ask > 0:
                mid = ask
            else:
                continue  # No price reference at all — can't evaluate

            # Price range — avoid extreme probabilities
            if mid < 0.02 or mid > 0.98:
                continue

            if USE_MAKER_ORDERS:
                # ── MAKER MODE ──────────────────────────────────────
                # We create liquidity — don't need existing bid/ask/volume.
                # Only skip if the spread is truly insane (>60¢ = book is garbage).
                if bid > 0 and ask > 0:
                    spread_cents = int((ask - bid) * 100)
                    if spread_cents > 60:
                        continue
                # Volume: NOT checked. Maker orders don't need existing volume.
                # Spread: NOT checked (for empty books). We set our own price.
            else:
                # ── TAKER MODE ──────────────────────────────────────
                # Need existing liquidity to cross the spread
                if m.yes_bid is None and m.yes_ask is None and m.last_price is None:
                    continue
                if m.spread is None:
                    continue
                spread_cents = int(float(m.spread) * 100)
                if spread_cents > max_spread:
                    continue
                if bid <= 0 and ask <= 0:
                    continue
                vol = float(m.volume if m.volume is not None else (m.volume_int or 0))
                if vol < 2:
                    continue
                if mid > 0:
                    spread_pct = float(spread_cents) / (mid * 100)
                    if spread_pct > 0.40:
                        continue

            from app.pipeline.portfolio_tracker import portfolio_state
            pos = portfolio_state.positions.get(m.ticker)
            if pos and abs(pos.position or 0) >= params.max_position_size:
                continue

            candidates.append(m)

        # Sports-preferred mode
        if self._sports_only and self._sports_detector:
            sports_cands = [c for c in candidates if self._sports_detector.is_sports_market(c)]
            if sports_cands:
                non_sports = [c for c in candidates if c not in sports_cands]
                return (sports_cands + non_sports[:50])[:500]
            log.debug("no_liquid_sports", total_candidates=len(candidates))

        return candidates[:500]

    def _pre_filter(self, candidates: list[Market]) -> list[Market]:
        """Pre-filter: cooldown, binary-only, price range, fee floor, expiry."""
        pre_filtered = []
        for m in candidates:
            ticker = m.ticker
            if ticker in self._recently_traded:
                continue
            # Check EVENT cooldown in the correct dict (was checking _recently_traded — wrong)
            _evt = getattr(m, "event_ticker", "") or ""
            if _evt and _evt in self._recently_traded_events:
                continue
            if getattr(m, "market_type", "binary") != "binary":
                continue
            mid = float(m.midpoint or m.last_price or 0)
            # Maker mode = 0 fees, so we can trade wider price ranges
            # Phase 3: widened from 0.08-0.92 to 0.05-0.95 for more candidates
            if mid < 0.05 or mid > 0.95:
                continue

            mid_cents = int(mid * 100)
            effective_cost_cents = min(mid_cents, 100 - mid_cents)
            fee_pct = round_trip_fee_pct(effective_cost_cents)
            _fee_cap = 0.56 if self._is_in_learning_mode() else 0.45
            if fee_pct > _fee_cap:
                continue

            if hasattr(m, "expiration_time") and m.expiration_time:
                from datetime import datetime, timezone as _tz
                _delta = (m.expiration_time - datetime.now(_tz.utc)).total_seconds() / 3600
                # Sports/props often expire within an hour — allow shorter
                _min_hours = 0.5 if self._is_in_learning_mode() else 0.75
                if _delta < _min_hours:
                    continue

            pre_filtered.append(m)
        return pre_filtered

    def _feature_completeness_gate(
        self,
        candidates: list[Market],
        features_list: list[MarketFeatures],
    ) -> tuple[list[Market], list[MarketFeatures]]:
        """Skip markets where too many features are defaults (0.0).

        Cold-start relaxation: during the first few scans, price history
        buffers are empty so most of the ~80 features will be zero.
        Use a very relaxed threshold until we accumulate enough history,
        then tighten gradually.  When the model is untrained, we need
        ANY candidates to flow through so the system can start learning.
        """
        filtered_c = []
        filtered_f = []

        # Count how many markets already have seeded history
        _seeded = sum(
            1 for m in candidates
            if m.ticker in self._features._histories
            and len(self._features._histories[m.ticker].prices) >= 5
        )
        _cold_start = _seeded < 20  # Not enough seeded yet (was 10)

        for m, feat in zip(candidates, features_list):
            arr = feat.to_array()
            zero_pct = (arr == 0.0).sum() / max(len(arr), 1)
            if _cold_start:
                # Ultra-relaxed: on cold start, we just need ANY non-zero data.
                # Model is untrained → learning mode → every trade is a learning trade.
                # Maker mode = 0 fees so imprecise signals are cheap.
                _thr = 0.98
            elif self._is_in_learning_mode():
                _thr = 0.85  # Still relaxed until enough real data
            elif len(candidates) < 50:
                _thr = 0.65  # Relax when few candidates
            else:
                _thr = 0.50  # Normal operation
            if zero_pct > _thr:
                continue
            filtered_c.append(m)
            filtered_f.append(feat)
        return filtered_c, filtered_f

    def _inject_event_prob_sums(
        self,
        candidates: list[Market],
        features_list: list[MarketFeatures],
    ) -> None:
        """Cross-event probability arbitrage detection."""
        event_prob_sums: dict[str, float] = {}
        event_members: dict[str, list[str]] = {}
        for m in candidates:
            evt = getattr(m, "event_ticker", "") or ""
            if evt:
                mid = float(m.midpoint or m.last_price or 0)
                event_prob_sums[evt] = event_prob_sums.get(evt, 0.0) + mid
                event_members.setdefault(evt, []).append(m.ticker)
        for m, feat in zip(candidates, features_list):
            evt = getattr(m, "event_ticker", "") or ""
            if evt and evt in event_prob_sums and len(event_members.get(evt, [])) >= 2:
                feat.event_prob_sum = event_prob_sums[evt]

    def _intelligence_enrich(
        self,
        candidates: list[Market],
        features_list: list[MarketFeatures],
    ) -> None:
        """Enrich features with Intelligence Hub alt-data via TickerMapper.

        Phase 23: Uses TickerMapper to bridge Kalshi tickers to intelligence
        signal keys, then populates 15 alt-data features in MarketFeatures.
        """
        try:
            from app.state import state as _hub_st
            hub = _hub_st.intelligence_hub
            if not hub or not hub._running:
                return

            from app.intelligence.ticker_mapper import TickerMapper
            mapper = getattr(self, "_ticker_mapper", None)
            if mapper is None:
                mapper = TickerMapper()
                self._ticker_mapper = mapper

            for m, feat in zip(candidates, features_list):
                try:
                    mapping = mapper.map(
                        m.ticker,
                        title=getattr(m, "title", "") or "",
                        category_hint=getattr(m, "category", "") or "",
                    )

                    source_count = 0

                    # Collect signals from ALL matching intelligence keys
                    for key in mapping.intelligence_keys:
                        signals = hub.get_signals_for_ticker(key)
                        for sig in signals:
                            source_count += 1
                            sf = sig.features

                            # ── Sports: Vegas odds ────────────────
                            if sig.source_type.value == "sports_odds":
                                home_prob = sf.get("home_prob", 0)
                                away_prob = sf.get("away_prob", 0)
                                if home_prob > 0 or away_prob > 0:
                                    # Use the stronger probability as the signal
                                    vegas_prob = max(home_prob, away_prob)
                                    feat.alt_vegas_prob = vegas_prob
                                    feat.alt_cross_platform_edge = feat.last_price - vegas_prob

                            # ── Crypto: current price vs strike ───
                            elif sig.source_type.value == "crypto":
                                crypto_price = sf.get("crypto_price", 0)
                                momentum = sf.get("crypto_momentum", 0)
                                feat.alt_crypto_momentum = momentum
                                if crypto_price > 0 and mapping.strike_price:
                                    dist = (crypto_price - mapping.strike_price) / mapping.strike_price
                                    feat.alt_crypto_strike_dist = max(-2.0, min(2.0, dist))
                                    # Use crypto price to estimate probability
                                    # If price is way above strike → YES likely
                                    # If price is way below → NO likely
                                    feat.alt_cross_platform_edge = feat.last_price - (1.0 if dist > 0.1 else 0.0 if dist < -0.1 else 0.5)

                            # ── Prediction markets (Polymarket) ───
                            elif sig.source_type.value == "prediction_market":
                                poly_prob = sf.get("poly_price", sig.signal_value)
                                if 0 < poly_prob <= 1.0:
                                    feat.alt_polymarket_prob = poly_prob
                                    feat.alt_cross_platform_edge = feat.last_price - poly_prob

                            # ── Economic data ─────────────────────
                            elif sig.source_type.value == "economic":
                                vix = sf.get("VIXCLS_value", sf.get("vix_value", 0))
                                if vix > 0:
                                    feat.alt_econ_vix = min(1.0, vix / 60.0)  # Normalise VIX: 60 = extreme

                                yield_10y = sf.get("DGS10_value", 0)
                                yield_2y = sf.get("DGS2_value", 0)
                                if yield_10y > 0 and yield_2y > 0:
                                    feat.alt_yield_spread = yield_10y - yield_2y

                                # For bond/rate markets, get the underlying value
                                series_val = sf.get(f"{mapping.underlying}_value", 0)
                                if series_val and mapping.underlying:
                                    feat.alt_econ_value = series_val
                                    if mapping.strike_price:
                                        dist = (series_val - mapping.strike_price) / max(0.01, abs(mapping.strike_price))
                                        feat.alt_econ_strike_dist = max(-2.0, min(2.0, dist))

                            # ── News sentiment ────────────────────
                            elif sig.source_type.value == "news":
                                feat.alt_news_sentiment = sig.signal_value
                                feat.alt_news_volume = min(1.0, sf.get("social_volume", sf.get("article_count", 0)) / 50.0)

                            # ── Social sentiment ──────────────────
                            elif sig.source_type.value == "social":
                                feat.alt_social_sentiment = sig.signal_value

                            # ── Weather ───────────────────────────
                            elif sig.source_type.value == "weather":
                                temp = sf.get("temp_f", sf.get("forecast_temp_f", 0))
                                if temp != 0:
                                    feat.alt_weather_temp = temp / 120.0  # Normalise: 120°F = 1.0
                                feat.alt_weather_extreme = sf.get("extreme_score", sf.get("alert_severity", 0))

                    # ── Category-level fallback: news + social ────
                    # If no ticker-level match, try category-level signals
                    if source_count == 0 and mapping.category != "unknown":
                        for prefix in ["news:", "social:"]:
                            cat_key = f"{prefix}{mapping.category}"
                            cat_signals = hub.get_signals_for_ticker(cat_key)
                            for sig in cat_signals:
                                source_count += 1
                                if prefix == "news:":
                                    feat.alt_news_sentiment = sig.signal_value
                                    feat.alt_news_volume = min(1.0, sig.features.get("social_volume", sig.features.get("article_count", 0)) / 50.0)
                                elif prefix == "social:":
                                    feat.alt_social_sentiment = sig.signal_value

                    # Normalised source count (0-1, where 1 = 5+ sources agree)
                    feat.alt_source_count = min(1.0, source_count / 5.0)

                except Exception as e:
                    log.debug("intelligence_enrich_single_error", ticker=m.ticker, error=str(e))

        except Exception as e:
            log.debug("intelligence_enrich_error", error=str(e))

    def _category_specialist_override(
        self,
        candidates: list[Market],
        features_list: list[MarketFeatures],
        predictions: list[Prediction],
    ) -> None:
        """Override predictions with category-specialist models (60/40 blend)."""
        for i, (m, feat) in enumerate(zip(candidates, features_list)):
            cat = detect_category(m.title or "", m.category or "", ticker=m.ticker)
            if cat in self._category_models:
                try:
                    spec_pred = self._category_models[cat].predict(feat)
                    if spec_pred and spec_pred.confidence > predictions[i].confidence:
                        blended_prob = 0.60 * spec_pred.predicted_prob + 0.40 * predictions[i].predicted_prob
                        predictions[i] = Prediction(
                            predicted_prob=blended_prob,
                            confidence=spec_pred.confidence,
                            side=spec_pred.side,
                            edge=spec_pred.edge,
                            model_name=f"cat_{cat}",
                        )
                except Exception:
                    pass

    # ── Signal Evaluation ─────────────────────────────────────────────

    def _evaluate_signals(
        self,
        candidates: list[Market],
        features_list: list[MarketFeatures],
        predictions: list[Prediction],
        params: StrategyParams,
        state: Any,
        liquidity: float,
    ) -> list[dict[str, Any]]:
        """Evaluate each signal through all quality gates."""
        _is_learning = self._is_in_learning_mode()
        # Phase 25b: In learning mode, bypass the grade gate entirely.
        # Phase 27: In graduated mode, lower from B+ to B for more trade flow.
        # Model has 0.77 AUC + maker 0¢ fees = can profit on marginal signals.
        min_grade = "F" if _is_learning else "B"
        conf_scorer = ConfidenceScorer(
            min_grade=min_grade,
            portfolio_heat=self._adv_risk.portfolio_heat if hasattr(self._adv_risk, "portfolio_heat") else 0.0,
            current_drawdown_pct=self._adv_risk.current_drawdown_pct if hasattr(self._adv_risk, "current_drawdown_pct") else 0.0,
            open_positions=self._count_open_positions(),
            max_positions=params.max_simultaneous_positions,
        )

        # Clean expired cooldowns
        now_ts = time.time()
        self._recently_traded = {
            t: ts for t, ts in self._recently_traded.items()
            if now_ts - ts < self._trade_cooldown_seconds
        }
        self._recently_traded_events = {
            e: ts for e, ts in self._recently_traded_events.items()
            if now_ts - ts < self._event_cooldown_seconds
        }

        tickers_this_scan: set[str] = set()
        events_this_scan: dict[str, int] = {}
        categories_this_scan: dict[str, int] = {}
        trade_candidates: list[dict[str, Any]] = []

        for market, features, prediction in zip(candidates, features_list, predictions):
            # Duplicate protection
            if market.ticker in self._recently_traded:
                continue
            _evt_tk = getattr(market, "event_ticker", "") or ""
            if _evt_tk and _evt_tk in self._recently_traded_events:
                continue
            if market.ticker in tickers_this_scan:
                continue

            # Diversification
            evt = getattr(market, "event_ticker", "") or ""
            if evt and events_this_scan.get(evt, 0) >= MAX_PER_EVENT:
                continue
            _pre_cat = detect_category(market.title or "", market.category or "", ticker=market.ticker)
            if categories_this_scan.get(_pre_cat, 0) >= MAX_PER_CATEGORY:
                continue

            # Early retirement check — don't even evaluate retired categories
            if self._performance and self._performance.is_category_retired(_pre_cat):
                continue

            # Category performance gate — only gate on THIS session's stats,
            # needs 30+ trades and sub-30% WR to gate (was 20 trades, 40% WR)
            cat_stat = self._get_category_stats().get(_pre_cat)
            if cat_stat:
                cat_total = cat_stat.get("wins", 0) + cat_stat.get("losses", 0)
                if cat_total >= 30:
                    cat_wr = cat_stat["wins"] / cat_total
                    if cat_wr < 0.30:
                        continue

            # Category adjustments
            prediction, _ = self._categories.adjust_prediction(
                prediction, features,
                market_title=market.title or "",
                category_hint=market.category or "",
                ticker=market.ticker,
            )

            # Sports override
            sports_pred = None
            if self._sports_detector and self._sports_predictor and self._sports_feat:
                info = self._sports_detector.detect(market)
                if info.is_sports:
                    sports_features = self._sports_feat.compute(market, features)
                    sports_pred = self._sports_predictor.predict(sports_features, features)

            if sports_pred is not None:
                prediction = sports_pred.to_base_prediction()
                if self._sports_risk and self._sports_detector:
                    info = self._sports_detector.detect(market)
                    passed, reason = self._sports_risk.check(
                        ticker=market.ticker,
                        event_ticker=market.event_ticker,
                        sport_id=info.sport_id,
                        count=1,
                        price_cents=int(features.midpoint * 100),
                        is_live=info.is_live,
                        edge=prediction.edge,
                    )
                    if not passed:
                        continue

            # Price floor
            mid_price = features.midpoint
            _floor_cents = MIN_PRICE_FLOOR_LEARNING_CENTS if _is_learning else MIN_PRICE_FLOOR_CENTS
            _floor = _floor_cents / 100.0
            if mid_price < _floor or mid_price > 1.0 - _floor:
                continue

            # Market-anchor sanity (edge cap)
            cat = detect_category(market.title or "", market.category or "", ticker=market.ticker)
            MAX_ALLOWED_EDGE = CATEGORY_EDGE_CAPS.get(cat, 0.12)
            # Phase 25: During learning mode, raise edge caps by 50% to let
            # more trades through for data collection.
            from app.frankenstein.constants import LEARNING_MODE_EDGE_CAP_MULT
            if _is_learning:
                MAX_ALLOWED_EDGE *= LEARNING_MODE_EDGE_CAP_MULT
            if abs(prediction.edge) > MAX_ALLOWED_EDGE:
                continue

            # Fee-aware minimum edge
            half_spread = features.spread / 2.0
            price_cents = int(features.midpoint * 100)
            effective_cost = min(price_cents, 100 - price_cents)

            if USE_MAKER_ORDERS:
                fee_as_fraction = 0.0
            else:
                fee_as_fraction = ROUND_TRIP_FEE_CENTS / 100.0

            if _is_learning:
                # Phase 25b: MAKER LEARNING — hold-to-settlement strategy.
                # Entry: maker order at our price (0¢ fee).
                # Exit: settlement (0¢ fee).
                # We never cross the spread, so half_spread is NOT a cost.
                # Taker mode still needs to beat the actual fee + spread.
                if USE_MAKER_ORDERS:
                    cost_to_beat = 0.0  # Maker + hold-to-settlement = no spread cost
                    _base_edge = 0.005  # Just above zero — any signal is worth testing
                else:
                    cost_to_beat = fee_as_fraction + half_spread
                    _base_edge = 0.07
                effective_min_edge = max(_base_edge, cost_to_beat * 1.0)
            else:
                effective_min_edge = params.min_edge
                # Phase 27: Lower category min edges for aggressive trading.
                # Model has 0.77 AUC + maker 0¢ fees = can profit on smaller edges.
                _CATEGORY_MIN_EDGES_MAKER = {
                    "sports": 0.04, "crypto": 0.05, "finance": 0.04,
                    "weather": 0.04, "politics": 0.04, "economics": 0.04,
                    "entertainment": 0.04, "science": 0.04,
                    "culture": 0.04, "social_media": 0.03,
                    "current_events": 0.04, "tech": 0.04, "legal": 0.04,
                    "general": 0.04,
                }
                _CATEGORY_MIN_EDGES_TAKER = {
                    "sports": 0.06, "crypto": 0.10, "finance": 0.08,
                    "weather": 0.07, "politics": 0.08, "economics": 0.08,
                    "entertainment": 0.06, "science": 0.06,
                    "culture": 0.06, "social_media": 0.05,
                    "current_events": 0.07, "tech": 0.08, "legal": 0.07,
                    "general": 0.06,
                }
                _edges = _CATEGORY_MIN_EDGES_MAKER if USE_MAKER_ORDERS else _CATEGORY_MIN_EDGES_TAKER
                cat_min = _edges.get(cat, 0.04 if USE_MAKER_ORDERS else 0.06)
                effective_min_edge = max(effective_min_edge, cat_min)
                cost_to_beat = fee_as_fraction + half_spread
                effective_min_edge = max(effective_min_edge, cost_to_beat * (1.2 if USE_MAKER_ORDERS else 1.5))

            if abs(prediction.edge) < effective_min_edge:
                continue

            # Absolute edge floor — never trade below this.
            # Learning mode gets a much lower floor to break cold-start.
            # Phase 25b: Heuristic produces edges of 0.005-0.02 — we need
            # these to flow through for training data.  Maker 0¢ fees means
            # any positive edge is worth taking at 1-2 contracts.
            _ABSOLUTE_MIN_EDGE = 0.003 if _is_learning else 0.025
            if abs(prediction.edge) < _ABSOLUTE_MIN_EDGE:
                continue

            # Confidence scoring
            conf_breakdown = conf_scorer.score(
                prediction, features,
                model_trained=self._model.is_trained,
                has_vegas=sports_pred is not None,
                is_sports=bool(
                    self._sports_detector and self._sports_detector.detect(market).is_sports
                ) if self._sports_detector else False,
                exchange_session=(
                    self._schedule.current_session()
                    if hasattr(self._schedule, "current_session") else "regular"
                ),
            )
            if not conf_breakdown.should_trade:
                continue

            # Tree agreement gate: skip when model trees disagree significantly
            # tree_agreement < 0.55 means the ensemble is basically coin-flipping
            if not _is_learning and hasattr(prediction, "tree_agreement"):
                if prediction.tree_agreement < 0.55:
                    continue

            # Calibration gate: skip uncalibrated predictions on trained model
            if not _is_learning and hasattr(prediction, "is_calibrated"):
                if not prediction.is_calibrated and prediction.calibration_error > 0.10:
                    continue

            state.total_signals += 1

            # Kelly sizing
            # Phase 25: In learning mode, use fixed 1-2 contracts instead of
            # Kelly.  Kelly with no training data is meaningless — it just
            # amplifies heuristic noise.  Fixed small bets = controlled risk
            # while collecting training data.
            if _is_learning:
                kelly = 0.01  # minimal — will map to 1-2 contracts via min_count
            else:
                kelly = self._kelly_size(prediction, features, params, market=market)
            if kelly <= 0:
                if _is_learning:
                    kelly = 0.01
                else:
                    continue

            # Confidence-based scaling — Phase 27: more generous for aggressive trading
            confidence_scale = {
                "A+": 1.0, "A": 0.90, "B+": 0.75, "B": 0.55, "C+": 0.35, "C": 0.20,
            }.get(conf_breakdown.grade, 0.15)

            # Phase 27: More aggressive category Kelly — every category can profit
            _cat_kelly_mult = {
                "crypto": 1.2,       # High volume, model trained on this
                "politics": 1.0,
                "economics": 1.0,
                "weather": 0.9,
                "sports": 0.9,       # Still slightly cautious
                "entertainment": 0.9,
                "culture": 0.85,
                "social_media": 0.85,
                "current_events": 0.9,
                "tech": 0.9,
                "legal": 0.85,
                "science": 0.9,
                "finance": 1.1,
            }.get(_pre_cat, 0.9)
            kelly *= confidence_scale * _cat_kelly_mult
            kelly = self._adv_risk.adjusted_kelly(kelly)
            kelly *= liquidity

            raw_count = int(kelly * params.max_position_size)
            price_cents = self._order_mgr.compute_price(prediction, features, market=market)

            # Grade-based sizing — Phase 27: bigger positions for high grades
            if _is_learning:
                min_count = 1
            elif conf_breakdown.grade in ("A+",):
                min_count = 5   # Phase 27: 5 contracts minimum for A+
            elif conf_breakdown.grade in ("A",):
                min_count = 3   # Phase 27: 3 contracts for A
            elif conf_breakdown.grade in ("B+",):
                min_count = 2   # Phase 27: 2 contracts for B+
            else:
                min_count = 1

            count = max(min_count, raw_count)
            count = min(count, params.max_position_size)

            # Net EV check
            cost_frac = price_cents / 100.0
            fee_cost = 0.0 if USE_MAKER_ORDERS else ROUND_TRIP_FEE_CENTS / 100.0
            # Phase 25b: In maker mode + hold-to-settlement, there is NO spread
            # cost.  Entry = maker order (our price), exit = settlement (0¢ or $1).
            # We never cross the spread.  In learning mode, be even more relaxed.
            if USE_MAKER_ORDERS and _is_learning:
                spread_cost = 0.0  # Hold to settlement — no spread crossing
            elif USE_MAKER_ORDERS:
                spread_cost = features.spread / 4.0  # Half credit for maker entry
            else:
                spread_cost = features.spread / 2.0  # Full half-spread for taker
            net_edge = abs(prediction.edge) - spread_cost - fee_cost
            if net_edge <= 0:
                continue
            ev = net_edge * count * (1.0 - cost_frac)

            # Enrich confidence breakdown
            breakdown_dict = conf_breakdown.to_dict()
            breakdown_dict["uncertainty"] = {
                "tree_agreement": round(prediction.tree_agreement, 3),
                "prediction_std": round(prediction.prediction_std, 4),
                "is_calibrated": prediction.is_calibrated,
                "calibration_error": round(prediction.calibration_error, 4),
                "calibrated_prob": round(prediction.calibrated_prob, 4) if prediction.calibrated_prob is not None else None,
            }

            trade_candidates.append({
                "market": market,
                "prediction": prediction,
                "features": features,
                "count": count,
                "price_cents": price_cents,
                "kelly": kelly,
                "ev": ev,
                "confidence_breakdown": breakdown_dict,
            })
            tickers_this_scan.add(market.ticker)
            if evt:
                events_this_scan[evt] = events_this_scan.get(evt, 0) + 1
            categories_this_scan[_pre_cat] = categories_this_scan.get(_pre_cat, 0) + 1

        return trade_candidates

    # ── Strategy Engine Merge ─────────────────────────────────────────

    def _merge_strategy_engine(
        self,
        candidates: list[Market],
        predictions: list[Prediction],
        trade_candidates: list[dict[str, Any]],
        params: StrategyParams,
    ) -> None:
        """Merge signals from the pre-built strategy engine."""
        try:
            from app.state import state as _app_state
            if not _app_state.strategy_engine:
                return

            from app.pipeline.portfolio_tracker import portfolio_state as _ps
            balance_cents = _ps.balance_cents or 1000000
            strat_signals = _app_state.strategy_engine.scan_all_markets(
                candidates,
                {m.ticker: self._features.compute(m) for m in candidates},
                {m.ticker: pred for m, pred in zip(candidates, predictions)},
                balance_cents,
            )

            existing_tickers = {c["market"].ticker for c in trade_candidates}

            for sig in strat_signals[:20]:
                if sig.ticker in existing_tickers:
                    continue
                if sig.ticker in self._recently_traded:
                    continue
                sig_market = next((m for m in candidates if m.ticker == sig.ticker), None)
                if not sig_market:
                    continue
                _sig_evt = getattr(sig_market, "event_ticker", "") or ""
                if _sig_evt and _sig_evt in self._recently_traded:
                    continue

                feat = self._features.compute(sig_market)
                if feat.midpoint < 0.15 or feat.midpoint > 0.85:
                    continue
                half_spread = feat.spread / 2.0 if feat.spread else 0.0
                if abs(sig.edge) <= half_spread:
                    continue

                _sig_cat = detect_category(sig_market.title or "", sig_market.category or "", ticker=sig_market.ticker)
                _sig_cap = CATEGORY_EDGE_CAPS.get(_sig_cat, 0.10)
                clamped_edge = max(-_sig_cap, min(_sig_cap, sig.edge))
                if abs(clamped_edge) < params.min_edge:
                    continue

                pred_for_sig = Prediction(
                    predicted_prob=sig.confidence,
                    confidence=min(sig.confidence, 0.60),
                    side=sig.side,
                    edge=clamped_edge,
                    model_name=sig.strategy,
                )

                risk_limit = 10
                if self._execution._risk_manager:
                    risk_limit = self._execution._risk_manager.limits.max_position_size
                count = max(1, min(sig.recommended_count, risk_limit))
                price_cents = self._order_mgr.compute_price(pred_for_sig, feat, market=sig_market)
                cost_frac = price_cents / 100.0

                # Net EV check — same as main scan path (Issue #24)
                spread_cost = feat.spread / 2.0 if feat.spread else 0.0
                fee_cost = 0.0 if USE_MAKER_ORDERS else ROUND_TRIP_FEE_CENTS / 100.0
                net_edge = abs(clamped_edge) - spread_cost - fee_cost
                if net_edge <= 0:
                    continue

                ev = net_edge * count * (1.0 - cost_frac)

                # Portfolio risk check — same as main scan path
                passed, reject_reason = self._adv_risk.portfolio_check(
                    ticker=sig_market.ticker, count=count, price_cents=price_cents,
                    event_ticker=getattr(sig_market, "event_ticker", ""),
                    category=_sig_cat,
                )
                if not passed:
                    continue

                trade_candidates.append({
                    "market": sig_market,
                    "prediction": pred_for_sig,
                    "features": feat,
                    "count": count,
                    "price_cents": price_cents,
                    "kelly": sig.edge * 0.25,
                    "ev": ev,
                })
        except Exception as e:
            log.debug("strategy_engine_merge_error", error=str(e))

    # ── Execution ─────────────────────────────────────────────────────

    async def _execute_top(
        self,
        trade_candidates: list[dict[str, Any]],
        max_trades: int,
        candidates: list[Market],
        state: Any,
        params: StrategyParams,
    ) -> dict[str, Any]:
        """Execute the top-ranked trade candidates."""
        scan_debug: dict[str, Any] = {
            "trade_candidates": len(trade_candidates),
            "max_trades": max_trades,
            "open_positions": self._count_open_positions(),
            "signals": state.total_signals,
            "portfolio_rejections": 0,
            "exec_rejections": 0,
            "exec_successes": 0,
            "top_candidates": [],
        }

        for candidate in trade_candidates[: max(max_trades, 0)]:
            market = candidate["market"]
            prediction = candidate["prediction"]
            features = candidate["features"]
            count = candidate["count"]
            price_cents = candidate["price_cents"]

            # Phase 27: Relaxed liquidity-aware count scaling
            # Maker mode = we ARE the liquidity. Less aggressive capping.
            vol = features.volume
            if vol < 20:
                count = min(count, 5)    # Phase 27: very thin → max 5 (was 2)
            elif vol < 100:
                count = min(count, 10)   # Phase 27: thin → max 10 (was 5)
            # High volume → no cap beyond position limits

            # Pre-exec spread recheck
            risk_spread_limit = 55  # Phase 27: synced with strategy max_spread_cents
            if self._execution._risk_manager:
                risk_spread_limit = self._execution._risk_manager.limits.max_spread_cents
            fresh = market_cache.get(market.ticker)
            if fresh and fresh.spread is not None:
                fresh_spread = int(float(fresh.spread) * 100)
                if fresh_spread > risk_spread_limit:
                    scan_debug["exec_rejections"] += 1
                    scan_debug["top_candidates"].append({
                        "ticker": market.ticker, "stage": "spread_recheck_rejected",
                        "spread": fresh_spread, "limit": params.max_spread_cents,
                    })
                    continue

            # Portfolio-level risk check
            _detected_cat = detect_category(
                market.title or "", market.category or "", ticker=market.ticker,
            )
            passed, reject_reason = self._adv_risk.portfolio_check(
                ticker=market.ticker, count=count,
                price_cents=price_cents,
                event_ticker=getattr(market, "event_ticker", ""),
                category=_detected_cat,
            )
            if not passed:
                scan_debug["portfolio_rejections"] += 1
                scan_debug["top_candidates"].append({
                    "ticker": market.ticker, "stage": "portfolio_rejected",
                    "reason": reject_reason,
                })
                continue

            # Phase 20: Skip retired categories
            _cat_retire = _detected_cat
            if self._performance and self._performance.is_category_retired(_cat_retire):
                scan_debug["portfolio_rejections"] += 1
                scan_debug["top_candidates"].append({
                    "ticker": market.ticker, "stage": "category_retired",
                    "category": _cat_retire,
                })
                continue

            # Phase 3+4: Capital budget check
            if self._capital:
                cost_cents = count * price_cents
                can_afford, cap_reason = self._capital.can_afford(cost_cents)
                if not can_afford:
                    scan_debug["portfolio_rejections"] += 1
                    scan_debug["top_candidates"].append({
                        "ticker": market.ticker, "stage": "capital_rejected",
                        "reason": cap_reason,
                    })
                    continue

                # Phase 17: Category budget check
                cat_ok, cat_reason = self._capital.can_afford_category(cost_cents, _detected_cat)
                if not cat_ok:
                    scan_debug["portfolio_rejections"] += 1
                    scan_debug["top_candidates"].append({
                        "ticker": market.ticker, "stage": "category_budget",
                        "reason": cat_reason,
                    })
                    continue

            # Record snapshot
            self.memory.record_snapshot(
                ticker=market.ticker, midpoint=features.midpoint,
                spread=features.spread, volume=features.volume,
            )

            # Execute (Phase 6: multi-level quoting)
            result = await self._order_mgr.execute_multi_level_trade(
                market=market, prediction=prediction,
                features=features, count=count, price_cents=price_cents,
            )

            if result and result.success:
                state.total_trades_executed += 1
                state.daily_trade_count += 1
                scan_debug["exec_successes"] += 1
                scan_debug["top_candidates"].append({
                    "ticker": market.ticker, "stage": "executed",
                    "order_id": result.order_id,
                })

                # Cooldowns
                self._recently_traded[market.ticker] = time.time()
                _evt_cd = getattr(market, "event_ticker", "") or ""
                if _evt_cd:
                    self._recently_traded_events[_evt_cd] = time.time()

                # Register with risk managers
                self._adv_risk.register_position(
                    ticker=market.ticker,
                    event_ticker=getattr(market, "event_ticker", ""),
                    category=_detected_cat,
                    side=prediction.side, count=count,
                    cost_cents=count * price_cents,
                    hours_to_expiry=features.hours_to_expiry,
                )

                # Phase 17: Track category deployment
                if self._capital:
                    self._capital.on_category_trade(_detected_cat, count * price_cents)

                if self._sports_risk and self._sports_detector:
                    info = self._sports_detector.detect(market)
                    if info.is_sports:
                        self._sports_risk.register_position(
                            ticker=market.ticker,
                            event_ticker=market.event_ticker,
                            sport_id=info.sport_id,
                            cost_cents=count * price_cents,
                            is_live=info.is_live,
                        )

                # Detect category & record in memory
                trade_category = detect_category(
                    market.title or "", market.category or "", ticker=market.ticker,
                )
                trade_record = self.memory.record_trade(
                    ticker=market.ticker, prediction=prediction,
                    features=features, action="buy", count=count,
                    price_cents=price_cents,
                    order_id=result.order_id or "",
                    latency_ms=result.latency_ms,
                    market_bid=int((market.yes_bid or 0) * 100) if isinstance(market.yes_bid, float) else (market.yes_bid or 0),
                    market_ask=int((market.yes_ask or 0) * 100) if isinstance(market.yes_ask, float) else (market.yes_ask or 0),
                    model_version=self._learner.current_version,
                    confidence_breakdown=candidate.get("confidence_breakdown"),
                )
                trade_record.category = trade_category

                # SQLite persist
                try:
                    from app.production import SQLiteStore
                    _persist_dir = str(
                        __import__("pathlib").Path(self.memory._persist_path).parent
                    )
                    _sqlite = SQLiteStore(db_path=f"{_persist_dir}/frankenstein.db")
                    _sqlite.save_trade({
                        "trade_id": result.order_id or f"{market.ticker}_{int(time.time())}",
                        "ticker": market.ticker,
                        "timestamp": time.time(),
                        "predicted_side": prediction.side,
                        "confidence": prediction.confidence,
                        "predicted_prob": prediction.predicted_prob,
                        "edge": prediction.edge,
                        "action": "buy", "count": count,
                        "price_cents": price_cents,
                        "total_cost_cents": count * price_cents,
                        "order_id": result.order_id or "",
                        "model_version": self._learner.current_version,
                    })
                except Exception:
                    pass
            else:
                state.total_trades_rejected += 1
                err = (
                    getattr(result, "error", None)
                    or getattr(result, "risk_rejection_reason", None)
                    or "unknown"
                )
                scan_debug["exec_rejections"] += 1
                scan_debug["top_candidates"].append({
                    "ticker": market.ticker, "stage": "exec_rejected", "error": err,
                })

        return scan_debug

    # ── Data Enrichment ───────────────────────────────────────────────

    async def _enrich_orderbook_depth(self, candidates: list[Market]) -> None:
        """Fetch L2 orderbook depth for top candidates."""
        try:
            from app.state import state as _st
            if not _st.kalshi_api:
                return
            for m in candidates[:20]:
                try:
                    ob = await _st.kalshi_api.markets.get_orderbook(m.ticker, depth=5)
                    bid_total = sum(float(lvl.count or 0) for lvl in ob.yes_bids)
                    ask_total = sum(float(lvl.count or 0) for lvl in ob.no_bids)
                    total = bid_total + ask_total
                    imb = (bid_total - ask_total) / total if total > 0 else 0.0
                    self._features._ob_depth_cache[m.ticker] = {
                        "bid_depth": bid_total,
                        "ask_depth": ask_total,
                        "imbalance": max(-1.0, min(1.0, imb)),
                    }
                except Exception:
                    pass
        except Exception as e:
            log.debug("orderbook_depth_error", error=str(e))

    async def _seed_price_histories(self, candidates: list[Market]) -> None:
        """Seed price history buffers from Kalshi candlestick API."""
        MAX_SEEDS_PER_SCAN = 40
        seeded = 0

        for m in candidates:
            if seeded >= MAX_SEEDS_PER_SCAN:
                break
            hist = self._features._histories.get(m.ticker)
            if hist and len(hist.prices) >= 10:
                continue
            series_ticker = getattr(m, "series_ticker", None)
            if not series_ticker:
                continue
            try:
                from app.state import state as _st
                if not _st.kalshi_api:
                    continue
                end_ts = int(time.time())
                start_ts = end_ts - 14400
                candles = await _st.kalshi_api.historical.get_candlesticks(
                    series_ticker=series_ticker, market_ticker=m.ticker,
                    start_ts=start_ts, end_ts=end_ts, period_interval=1,
                )
                if candles:
                    for c in candles:
                        bid_close = float(c.yes_bid.close or 0) / 100.0 if c.yes_bid and c.yes_bid.close else 0
                        ask_close = float(c.yes_ask.close or 0) / 100.0 if c.yes_ask and c.yes_ask.close else 0
                        if bid_close > 0 and ask_close > 0:
                            price = (bid_close + ask_close) / 2.0
                        elif c.price and c.price.close:
                            price = float(c.price.close) / 100.0
                        else:
                            continue
                        vol = float(c.volume or 0)
                        spread = (ask_close - bid_close) if ask_close > bid_close else 0
                        self._features.update(m.ticker, price, vol, 0, spread)
                    seeded += 1
                    log.debug("history_seeded", ticker=m.ticker, candles=len(candles))

                    # Also fetch 60-min candles for 24h context
                    try:
                        start_ts_h = end_ts - 86400
                        hourly = await _st.kalshi_api.historical.get_candlesticks(
                            series_ticker=series_ticker, market_ticker=m.ticker,
                            start_ts=start_ts_h, end_ts=start_ts, period_interval=60,
                        )
                        if hourly:
                            for c in hourly:
                                bid_close = float(c.yes_bid.close or 0) / 100.0 if c.yes_bid and c.yes_bid.close else 0
                                ask_close = float(c.yes_ask.close or 0) / 100.0 if c.yes_ask and c.yes_ask.close else 0
                                if bid_close > 0 and ask_close > 0:
                                    price = (bid_close + ask_close) / 2.0
                                elif c.price and c.price.close:
                                    price = float(c.price.close) / 100.0
                                else:
                                    continue
                                vol = float(c.volume or 0)
                                spread = (ask_close - bid_close) if ask_close > bid_close else 0
                                self._features.update(m.ticker, price, vol, 0, spread)
                    except Exception:
                        pass
            except Exception:
                pass

    # ── Kelly Sizing ──────────────────────────────────────────────────

    def _kelly_size(
        self,
        prediction: Prediction,
        features: MarketFeatures,
        params: StrategyParams,
        market: Market | None = None,
    ) -> float:
        """
        Kelly criterion for binary contracts.

        Binary contract math:
          Buy at cost c (0-1 range, e.g., 0.40 = 40¢ per contract)
          Win:  receive $1, net profit = (1 - c)
          Lose: lose entire cost c

        Kelly optimal fraction:  f* = (p - c) / (1 - c)
        """
        from app.frankenstein.constants import TAKER_FEE_CENTS as _TFC

        mid = features.midpoint

        if prediction.side == "yes":
            p = prediction.predicted_prob
            if USE_MAKER_ORDERS:
                if market and market.yes_bid is not None and float(market.yes_bid) > 0:
                    c = min(float(market.yes_bid) + 0.01, 0.99)
                else:
                    c = max(mid - 0.01, 0.01)
            else:
                if market and market.yes_ask is not None and float(market.yes_ask) > 0:
                    c = min(float(market.yes_ask), 0.99)
                else:
                    c = min(mid + 0.01, 0.99)
        else:
            p = 1.0 - prediction.predicted_prob
            if USE_MAKER_ORDERS:
                if market and market.no_bid is not None and float(market.no_bid) > 0:
                    c = min(float(market.no_bid) + 0.01, 0.99)
                elif market and market.yes_ask is not None and float(market.yes_ask) > 0:
                    c = max(1.0 - float(market.yes_ask) + 0.01, 0.01)
                else:
                    c = max(1.0 - mid - 0.01, 0.01)
            else:
                if market and market.no_ask is not None and float(market.no_ask) > 0:
                    c = min(float(market.no_ask), 0.99)
                elif market and market.yes_bid is not None and float(market.yes_bid) > 0:
                    c = min(1.0 - float(market.yes_bid), 0.99)
                else:
                    c = min(1.0 - mid + 0.01, 0.99)

        if USE_MAKER_ORDERS:
            fee_per_side = 0.0
            real_cost = c
            net_win = 1.0 - c
        else:
            fee_per_side = _TFC / 100.0
            real_cost = c + fee_per_side
            net_win = (1.0 - fee_per_side) - c

        if p <= real_cost or real_cost <= 0.01 or real_cost >= 0.99 or net_win <= 0:
            return 0.0

        kelly = (p - real_cost) / net_win
        adjusted = kelly * params.kelly_fraction

        if hasattr(prediction, "prediction_std") and prediction.prediction_std > 0:
            uncertainty_scale = max(0.2, 1.0 - prediction.prediction_std * 3.0)
            adjusted *= uncertainty_scale

        # Phase 5: discount by predicted fill probability
        # Lower fill prob → smaller position (capital may sit idle)
        if self._fill_pred and self._fill_pred.total_observations >= 30 and market:
            try:
                fp = self._fill_pred.predict_from_order_context(
                    ticker=market.ticker,
                    side=prediction.side,
                    price_cents=int(c * 100),
                    market=market,
                    features=features,
                )
                # Don't reduce below 30% of Kelly — partial fills still valuable
                fill_discount = max(0.30, fp)
                adjusted *= fill_discount
            except Exception:
                pass  # Never block sizing for prediction errors

        return max(0.0, min(adjusted, 1.0))

    # ── Helpers ───────────────────────────────────────────────────────

    def _count_open_positions(self) -> int:
        from app.pipeline.portfolio_tracker import portfolio_state
        return sum(1 for pos in portfolio_state.positions.values() if (pos.position or 0) != 0)

    def _get_category_stats(self) -> dict[str, dict[str, int]]:
        """Get category stats (may come from resolver via brain wiring)."""
        # This will be wired by brain to point at resolver.category_stats
        return getattr(self, "_category_stats_ref", {})

    # ── Phase 2: Reactive Fast-Path Scan ──────────────────────────────

    async def scan_ticker(
        self,
        ticker: str,
        state: Any,
        *,
        book_data: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """
        Fast-path scan for a single ticker triggered by a real-time event.

        Unlike the full ``scan()`` which iterates all active markets,
        this evaluates ONE market immediately when its price changes.

        Returns a scan_debug dict if a trade was attempted, or None
        if the ticker was filtered out.

        Called by the Brain when it receives a TICKER_UPDATE event
        from the WS bridge. This is the core of the reactive architecture:
        instead of waiting up to 30s for the next poll, we evaluate
        a market within milliseconds of a price change.

        Guard rails:
        - Only fires if the system is trading and not paused
        - Respects daily trade cap, circuit breaker, cooldowns
        - Subject to all the same quality gates as full scan
        - Rate-limited: won't re-evaluate same ticker within 5s
        """
        start = time.monotonic()

        # Basic guards
        if state.is_paused or not state.is_trading:
            return None

        from datetime import datetime, timezone as _tz
        _today = datetime.now(_tz.utc).strftime("%Y-%m-%d")
        if state.daily_trade_date != _today:
            state.daily_trade_count = 0
            state.daily_trade_date = _today
        if state.daily_trade_count >= MAX_DAILY_TRADES:
            return None

        if state.circuit_breaker_triggered:
            return None

        # Cooldown check
        if ticker in self._recently_traded:
            return None

        # Rate-limit per ticker: don't re-evaluate faster than 5s
        _rt_key = f"_rt_{ticker}"
        now_ts = time.time()
        last_eval = self._recently_traded.get(_rt_key, 0)
        if now_ts - last_eval < 5.0:
            return None
        self._recently_traded[_rt_key] = now_ts

        # Get market from cache
        market = market_cache.get(ticker)
        if not market:
            return None

        # Quick eligibility checks (subset of _filter_candidates + _pre_filter)
        if market.status not in (MarketStatus.ACTIVE, MarketStatus.OPEN):
            return None

        # Phase 22: Block toxic market prefixes in reactive path too
        ticker_upper = (ticker or "").upper()
        _REACTIVE_JUNK = (
            "KXMVE", "KXSPOTSTREAMGLOBAL", "KXPARLAY",
            "KXEPLGOAL", "KXEPLFIRSTGOAL", "KXMVECROSSCATEGORY",
            "KXNCAAMB1HSPREAD", "KXQUICKSETTLE",
            "KXBTC15M", "KXETH15M", "KXSOL15M", "KXDOGE15M", "KXXRP15M",
            "KXADA15M", "KXAVAX15M", "KXLINK15M", "KXDOT15M", "KXMATIC15M",
        )
        if ticker_upper.startswith(_REACTIVE_JUNK):
            return None

        mid = float(market.midpoint or market.last_price or 0)
        if mid < 0.08 or mid > 0.92:
            return None

        vol = float(market.volume if market.volume is not None else (market.volume_int or 0))
        if vol < 3:
            return None

        if market.spread is not None:
            spread_cents = int(float(market.spread) * 100)
            if spread_cents > self._strategy.params.max_spread_cents:
                return None

        # Event cooldown
        _evt = getattr(market, "event_ticker", "") or ""
        if _evt and _evt in self._recently_traded_events:
            return None

        # Position limit
        from app.pipeline.portfolio_tracker import portfolio_state
        pos = portfolio_state.positions.get(ticker)
        if pos and abs(pos.position or 0) >= self._strategy.params.max_position_size:
            return None

        # Compute features
        if book_data:
            # Inject fresh WS data before computing
            ws_mid = book_data.get("mid", 0)
            ws_vol = book_data.get("volume", 0)
            ws_spread = (book_data.get("yes_ask", 0) - book_data.get("yes_bid", 0))
            if ws_mid > 0:
                self._features.update(ticker, ws_mid, float(ws_vol or 0), 0, ws_spread)

        features = self._features.compute(market)

        # Feature completeness
        arr = features.to_array()
        zero_pct = (arr == 0.0).sum() / max(len(arr), 1)
        _thr = 0.50 if self._is_in_learning_mode() else 0.30
        if zero_pct > _thr:
            return None

        # Predict
        prediction = self._model.predict(features)
        if not prediction:
            return None

        # Category specialist override
        cat = detect_category(market.title or "", market.category or "", ticker=market.ticker)
        if cat in self._category_models:
            try:
                spec_pred = self._category_models[cat].predict(features)
                if spec_pred and spec_pred.confidence > prediction.confidence:
                    blended_prob = 0.60 * spec_pred.predicted_prob + 0.40 * prediction.predicted_prob
                    prediction = Prediction(
                        predicted_prob=blended_prob,
                        confidence=spec_pred.confidence,
                        side=spec_pred.side,
                        edge=spec_pred.edge,
                        model_name=f"cat_{cat}",
                    )
            except Exception:
                pass

        # Skip retired categories
        if self._performance and self._performance.is_category_retired(cat):
            return None

        # Edge cap
        MAX_ALLOWED_EDGE = CATEGORY_EDGE_CAPS.get(cat, 0.10)
        if abs(prediction.edge) > MAX_ALLOWED_EDGE:
            return None

        # Fee-aware minimum edge (aligned with full scan thresholds)
        half_spread = features.spread / 2.0
        if USE_MAKER_ORDERS:
            cost_to_beat = half_spread
            # Use category-specific min edges (same as full scan)
            _REACTIVE_MIN_EDGES = {
                "sports": 0.06, "crypto": 0.08, "finance": 0.07,
                "weather": 0.06, "politics": 0.07, "economics": 0.07,
                "entertainment": 0.06, "science": 0.06,
                "culture": 0.06, "social_media": 0.05,
                "current_events": 0.06, "tech": 0.07, "legal": 0.06,
                "general": 0.06,
            }
            cat_min = _REACTIVE_MIN_EDGES.get(cat, 0.06)
            effective_min_edge = max(cat_min, cost_to_beat * 1.2)
        else:
            cost_to_beat = ROUND_TRIP_FEE_CENTS / 100.0 + half_spread
            effective_min_edge = max(self._strategy.params.min_edge, cost_to_beat * 1.5)

        if abs(prediction.edge) < effective_min_edge:
            return None

        # Phase 22: Absolute edge floor (same as full scan)
        if abs(prediction.edge) < 0.04:
            return None

        # Price floor
        _floor_cents = MIN_PRICE_FLOOR_LEARNING_CENTS if self._is_in_learning_mode() else MIN_PRICE_FLOOR_CENTS
        _floor = _floor_cents / 100.0
        if features.midpoint < _floor or features.midpoint > 1.0 - _floor:
            return None

        # Kelly sizing
        params = self._strategy.params
        kelly = self._kelly_size(prediction, features, params, market=market)
        if kelly <= 0:
            return None

        # Sizing
        count = max(1, int(kelly * params.max_position_size))
        count = min(count, params.max_position_size)
        price_cents = self._order_mgr.compute_price(prediction, features, market=market)

        # Net EV check
        cost_frac = price_cents / 100.0
        spread_cost = features.spread / 2.0
        fee_cost = 0.0 if USE_MAKER_ORDERS else ROUND_TRIP_FEE_CENTS / 100.0
        net_edge = abs(prediction.edge) - spread_cost - fee_cost
        if net_edge <= 0:
            return None

        # Portfolio risk check
        passed, reject_reason = self._adv_risk.portfolio_check(
            ticker=ticker, count=count, price_cents=price_cents,
            event_ticker=getattr(market, "event_ticker", ""),
            category=cat,
        )
        if not passed:
            return {"ticker": ticker, "stage": "portfolio_rejected", "reason": reject_reason}

        # Phase 3+4: Capital budget check
        if self._capital:
            cost_cents = count * price_cents
            can_afford, cap_reason = self._capital.can_afford(cost_cents)
            if not can_afford:
                return {"ticker": ticker, "stage": "capital_rejected", "reason": cap_reason}

        # Execute! (Phase 6: multi-level quoting)
        result = await self._order_mgr.execute_multi_level_trade(
            market=market, prediction=prediction,
            features=features, count=count, price_cents=price_cents,
        )

        elapsed_ms = (time.monotonic() - start) * 1000

        if result and result.success:
            state.total_trades_executed += 1
            state.daily_trade_count += 1
            self._recently_traded[ticker] = time.time()
            if _evt:
                self._recently_traded_events[_evt] = time.time()

            # Register with risk manager
            self._adv_risk.register_position(
                ticker=ticker,
                event_ticker=getattr(market, "event_ticker", ""),
                category=cat,
                side=prediction.side, count=count,
                cost_cents=count * price_cents,
                hours_to_expiry=features.hours_to_expiry,
            )

            # Record in memory
            trade_category = detect_category(market.title or "", market.category or "", ticker=ticker)
            trade_record = self.memory.record_trade(
                ticker=ticker, prediction=prediction,
                features=features, action="buy", count=count,
                price_cents=price_cents,
                order_id=result.order_id or "",
                latency_ms=result.latency_ms,
                market_bid=int((market.yes_bid or 0) * 100) if isinstance(market.yes_bid, float) else (market.yes_bid or 0),
                market_ask=int((market.yes_ask or 0) * 100) if isinstance(market.yes_ask, float) else (market.yes_ask or 0),
                model_version=self._learner.current_version,
            )
            trade_record.category = trade_category

            log.info("🧟⚡ REACTIVE TRADE",
                     ticker=ticker, side=prediction.side,
                     edge=f"{prediction.edge:.3f}",
                     price=f"{price_cents}¢", count=count,
                     ms=f"{elapsed_ms:.1f}")

            return {
                "ticker": ticker, "stage": "executed_reactive",
                "order_id": result.order_id, "ms": round(elapsed_ms, 1),
            }
        else:
            state.total_trades_rejected += 1
            return {"ticker": ticker, "stage": "exec_rejected_reactive"}
