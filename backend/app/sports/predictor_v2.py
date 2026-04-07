"""
JA Hedge — Sports Prediction Model V2 (Phase 30).

Complete rewrite of sports prediction with:
  1. Multi-signal fusion (Vegas, social, news, line movement)
  2. Proper Vegas edge with time-decay for stale data
  3. Correct side determination (which team does the Kalshi market reference)
  4. Confidence calibration tuned to actual sports market dynamics
  5. Hedging: detect correlated markets on the same game → hedge positions
  6. Per-category circuit breaker — auto-stop after consecutive losses
  7. Aggressive Kelly sizing when confidence is high
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

from app.logging_config import get_logger

log = get_logger("sports.predictor_v2")


# ── Configuration ─────────────────────────────────────────────────────────

# Minimum discrepancy between Kalshi and external consensus to trade
MIN_EDGE_THRESHOLD = 0.04        # 4% minimum edge
MAX_EDGE_THRESHOLD = 0.35        # >35% is suspicious (stale data)

# Time-decay for external odds data
ODDS_FRESH_SECONDS = 120         # <2 min = full trust
ODDS_STALE_SECONDS = 600         # >10 min = decaying
ODDS_DEAD_SECONDS = 1800         # >30 min = ignore entirely

# Confidence tiers
CONFIDENCE_TIER_HIGH = 0.80      # multiple strong signals agree
CONFIDENCE_TIER_MEDIUM = 0.60    # single strong signal
CONFIDENCE_TIER_LOW = 0.40       # weak or conflicting signals

# Hedging configuration
HEDGE_MIN_CORRELATED_MARKETS = 2  # need at least 2 markets on same game
HEDGE_TARGET_PROFIT_PCT = 0.03    # lock in 3% profit when possible

# Per-category circuit breaker
CATEGORY_LOSS_STREAK_PAUSE = 8   # pause after 8 consecutive losses
CATEGORY_LOSS_RATE_PAUSE = 0.20  # pause if WR drops below 20% (min 20 trades)
CATEGORY_PAUSE_DURATION = 3600   # pause for 1 hour
CATEGORY_MIN_TRADES_FOR_WR = 20  # need 20 trades before WR-based pause


@dataclass
class PredictionSignal:
    """A single signal contributing to the prediction."""
    source: str          # "vegas_consensus", "social_sentiment", "news", "line_move"
    direction: str       # "yes" or "no"
    strength: float      # 0.0 to 1.0
    freshness: float     # 0.0 (dead) to 1.0 (fresh)
    details: str = ""


@dataclass
class SportsV2Prediction:
    """Enhanced prediction with full signal chain."""
    side: str = "yes"
    confidence: float = 0.0
    predicted_prob: float = 0.5
    edge: float = 0.0
    model_name: str = "sports_v2"
    model_version: str = "v2.0"

    # Signal chain
    signals: list[PredictionSignal] = field(default_factory=list)
    signal_agreement: float = 0.0  # how much signals agree (0=conflicting, 1=unanimous)
    dominant_signal: str = ""       # which signal drove the decision

    # Sports context
    sport_id: str = ""
    market_type: str = ""
    vegas_prob: float = 0.0
    kalshi_price: float = 0.0
    discrepancy: float = 0.0
    
    # Hedging
    hedge_opportunity: bool = False
    hedge_ticker: str = ""
    hedge_side: str = ""
    hedge_edge: float = 0.0

    def to_base_prediction(self):
        """Convert to base Prediction for Frankenstein compatibility."""
        from app.ai.models import Prediction
        return Prediction(
            side=self.side,
            confidence=self.confidence,
            predicted_prob=self.predicted_prob,
            edge=self.edge,
            model_name=self.model_name,
            model_version=self.model_version,
        )


@dataclass
class CategoryHealth:
    """Tracks health metrics per sport category for circuit breaker."""
    wins: int = 0
    losses: int = 0
    current_streak: int = 0       # negative = loss streak
    is_paused: bool = False
    paused_at: float = 0.0
    pause_reason: str = ""
    total_pnl_cents: int = 0

    @property
    def total_trades(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.wins / self.total_trades

    def record_win(self, pnl_cents: int = 0) -> None:
        self.wins += 1
        self.current_streak = max(1, self.current_streak + 1) if self.current_streak > 0 else 1
        self.total_pnl_cents += pnl_cents

    def record_loss(self, pnl_cents: int = 0) -> None:
        self.losses += 1
        self.current_streak = min(-1, self.current_streak - 1) if self.current_streak < 0 else -1
        self.total_pnl_cents += pnl_cents

    def should_pause(self) -> tuple[bool, str]:
        """Check if this category should be paused."""
        # Loss streak check
        if self.current_streak <= -CATEGORY_LOSS_STREAK_PAUSE:
            return True, f"loss_streak_{abs(self.current_streak)}"
        # Win rate check (need enough trades)
        if self.total_trades >= CATEGORY_MIN_TRADES_FOR_WR:
            if self.win_rate < CATEGORY_LOSS_RATE_PAUSE:
                return True, f"low_win_rate_{self.win_rate:.1%}"
        return False, ""


class SportsCircuitBreaker:
    """Per-category circuit breaker for sports trading."""

    def __init__(self) -> None:
        self._categories: dict[str, CategoryHealth] = {}
        self._global_paused = False

    def get_health(self, sport_id: str) -> CategoryHealth:
        if sport_id not in self._categories:
            self._categories[sport_id] = CategoryHealth()
        return self._categories[sport_id]

    def record_outcome(self, sport_id: str, won: bool, pnl_cents: int = 0) -> None:
        """Record a trade outcome and check if we should pause."""
        health = self.get_health(sport_id)
        if won:
            health.record_win(pnl_cents)
            # Reset pause on a win streak of 2+ after being paused
            if health.is_paused and health.current_streak >= 2:
                health.is_paused = False
                health.pause_reason = ""
                log.info("sports_category_unpaused",
                         sport=sport_id, streak=health.current_streak)
        else:
            health.record_loss(pnl_cents)
            should_pause, reason = health.should_pause()
            if should_pause and not health.is_paused:
                health.is_paused = True
                health.paused_at = time.time()
                health.pause_reason = reason
                log.warning("sports_category_paused",
                            sport=sport_id, reason=reason,
                            wins=health.wins, losses=health.losses,
                            wr=f"{health.win_rate:.1%}")

    def can_trade(self, sport_id: str) -> tuple[bool, str]:
        """Check if we can trade in this sport category."""
        if self._global_paused:
            return False, "sports_globally_paused"

        health = self.get_health(sport_id)
        if not health.is_paused:
            return True, ""

        # Check if pause has expired
        elapsed = time.time() - health.paused_at
        if elapsed > CATEGORY_PAUSE_DURATION:
            health.is_paused = False
            health.pause_reason = ""
            log.info("sports_category_pause_expired",
                     sport=sport_id, elapsed_h=f"{elapsed/3600:.1f}")
            return True, ""

        return False, health.pause_reason

    def stats(self) -> dict[str, Any]:
        result = {}
        for sport_id, health in self._categories.items():
            result[sport_id] = {
                "wins": health.wins,
                "losses": health.losses,
                "win_rate": f"{health.win_rate:.1%}",
                "streak": health.current_streak,
                "is_paused": health.is_paused,
                "pause_reason": health.pause_reason,
                "pnl": f"${health.total_pnl_cents / 100:.2f}",
            }
        return result


class SportsHedger:
    """
    Detects and creates hedge opportunities on the same game.

    Hedging approach for Kalshi sports:
    - If we bet YES on "Team A wins" and the market moves against us,
      look for a correlated market (e.g., "Team A wins by 1-5") that
      can offset our loss.
    - On the same game, moneyline + spread + totals markets can be
      used to create synthetic hedges.
    - The goal: reduce variance, not eliminate profit. A perfect hedge
      = breakeven. We want partial hedges that guarantee small profit
      or limit max loss.
    """

    def __init__(self) -> None:
        # game_event → list of (ticker, side, price, edge)
        self._active_positions: dict[str, list[dict]] = {}
        self._hedge_count = 0

    def register_position(
        self,
        event_ticker: str,
        ticker: str,
        side: str,
        price_cents: int,
        edge: float,
        market_type: str = "moneyline",
    ) -> None:
        """Register a new position for hedge tracking."""
        if not event_ticker:
            return
        if event_ticker not in self._active_positions:
            self._active_positions[event_ticker] = []
        self._active_positions[event_ticker].append({
            "ticker": ticker,
            "side": side,
            "price_cents": price_cents,
            "edge": edge,
            "market_type": market_type,
            "timestamp": time.time(),
        })

    def find_hedge(
        self,
        event_ticker: str,
        new_ticker: str,
        new_side: str,
        new_price_cents: int,
        new_edge: float,
        new_market_type: str = "moneyline",
    ) -> dict | None:
        """
        Check if a new trade creates a hedge with existing positions.

        Returns hedge info dict if this trade would create a profitable
        hedge, None otherwise.
        """
        existing = self._active_positions.get(event_ticker, [])
        if not existing:
            return None

        for pos in existing:
            # Same ticker, opposite side = direct hedge
            if pos["ticker"] == new_ticker and pos["side"] != new_side:
                # Calculate if the hedge locks in profit
                if pos["side"] == "yes":
                    existing_cost = pos["price_cents"]
                    hedge_cost = 100 - new_price_cents  # buying NO
                    total_cost = existing_cost + hedge_cost
                    # If total cost < 100, we lock in profit regardless of outcome
                    if total_cost < 97:  # 3¢ minimum profit
                        profit_cents = 100 - total_cost
                        return {
                            "type": "direct_hedge",
                            "locked_profit_cents": profit_cents,
                            "existing_ticker": pos["ticker"],
                            "existing_side": pos["side"],
                        }

            # Same game, different market type = cross-market hedge
            if (pos["market_type"] != new_market_type
                    and pos["ticker"] != new_ticker):
                # Moneyline YES + Spread NO on same team ≈ partial hedge
                # Both can't maximally lose simultaneously
                combined_edge = (pos["edge"] + new_edge) / 2
                if combined_edge > 0.06:  # combined edge must still be positive
                    return {
                        "type": "cross_market_hedge",
                        "combined_edge": combined_edge,
                        "existing_ticker": pos["ticker"],
                        "existing_type": pos["market_type"],
                    }

        return None

    def remove_position(self, event_ticker: str, ticker: str) -> None:
        """Remove a closed position from hedge tracking."""
        if event_ticker in self._active_positions:
            self._active_positions[event_ticker] = [
                p for p in self._active_positions[event_ticker]
                if p["ticker"] != ticker
            ]
            if not self._active_positions[event_ticker]:
                del self._active_positions[event_ticker]

    def stats(self) -> dict[str, Any]:
        return {
            "tracked_games": len(self._active_positions),
            "tracked_positions": sum(len(v) for v in self._active_positions.values()),
            "hedges_found": self._hedge_count,
        }


def _compute_freshness(fetched_at: float) -> float:
    """Time-decay function for external data freshness."""
    age = time.time() - fetched_at
    if age <= ODDS_FRESH_SECONDS:
        return 1.0
    if age >= ODDS_DEAD_SECONDS:
        return 0.0
    # Linear decay between fresh and dead
    return 1.0 - (age - ODDS_FRESH_SECONDS) / (ODDS_DEAD_SECONDS - ODDS_FRESH_SECONDS)


class SportsPredictorV2:
    """
    Enhanced sports predictor with multi-signal fusion and hedging.

    Prediction flow:
    1. Gather signals: Vegas consensus, social sentiment, news, line movement
    2. Apply time-decay to stale signals
    3. Determine correct side (which team does this Kalshi market reference)
    4. Fuse signals with agreement-weighted confidence
    5. Check circuit breaker (has this sport been losing too much?)
    6. Check for hedge opportunities
    7. Apply aggressive Kelly sizing
    """

    def __init__(self) -> None:
        self.circuit_breaker = SportsCircuitBreaker()
        self.hedger = SportsHedger()
        self._stats = {
            "predictions": 0,
            "signals_generated": 0,
            "hedges_found": 0,
            "trades_blocked_by_breaker": 0,
            "no_signal": 0,
            "stale_data_skipped": 0,
        }

    def predict(
        self,
        sports_features: Any,  # SportsFeatures
        base_features: Any = None,  # MarketFeatures
        *,
        market_title: str = "",
        event_ticker: str = "",
        ticker: str = "",
    ) -> SportsV2Prediction | None:
        """
        Generate a sports prediction using multi-signal fusion.
        """
        self._stats["predictions"] += 1

        sport_id = getattr(sports_features, "sport_id", "unknown")
        market_type = getattr(sports_features, "market_type", "moneyline")

        # 1. Circuit breaker check
        can_trade, block_reason = self.circuit_breaker.can_trade(sport_id)
        if not can_trade:
            self._stats["trades_blocked_by_breaker"] += 1
            return None

        # 2. Gather all signals
        signals: list[PredictionSignal] = []

        # Signal 1: Vegas/ESPN consensus
        vegas_signal = self._compute_vegas_signal(sports_features, market_title)
        if vegas_signal:
            signals.append(vegas_signal)

        # Signal 2: Social sentiment
        social_signal = self._compute_social_signal(sports_features)
        if social_signal:
            signals.append(social_signal)

        # Signal 3: Line movement / steam
        movement_signal = self._compute_movement_signal(sports_features)
        if movement_signal:
            signals.append(movement_signal)

        # Signal 4: Live game state (if in-progress)
        live_signal = self._compute_live_signal(sports_features)
        if live_signal:
            signals.append(live_signal)

        if not signals:
            self._stats["no_signal"] += 1
            # Kalshi-only fallback — extremely conservative
            return self._kalshi_only_fallback(sports_features, base_features)

        self._stats["signals_generated"] += len(signals)

        # 3. Fuse signals into prediction
        prediction = self._fuse_signals(signals, sports_features)
        if prediction is None:
            return None

        prediction.sport_id = sport_id
        prediction.market_type = market_type

        # 4. Check edge thresholds
        if abs(prediction.edge) < MIN_EDGE_THRESHOLD:
            return None
        if abs(prediction.edge) > MAX_EDGE_THRESHOLD:
            self._stats["stale_data_skipped"] += 1
            return None

        # 5. Check for hedge opportunities
        hedge = self.hedger.find_hedge(
            event_ticker=event_ticker,
            new_ticker=ticker,
            new_side=prediction.side,
            new_price_cents=int(prediction.kalshi_price * 100),
            new_edge=prediction.edge,
            new_market_type=market_type,
        )
        if hedge:
            prediction.hedge_opportunity = True
            prediction.hedge_ticker = hedge.get("existing_ticker", "")
            prediction.hedge_side = hedge.get("type", "")
            prediction.hedge_edge = hedge.get("combined_edge", hedge.get("locked_profit_cents", 0) / 100)
            self._stats["hedges_found"] += 1
            # Boost confidence for hedged trades
            prediction.confidence = min(0.95, prediction.confidence * 1.15)

        return prediction

    def _compute_vegas_signal(
        self,
        sf: Any,  # SportsFeatures
        market_title: str = "",
    ) -> PredictionSignal | None:
        """Signal 1: Vegas/ESPN consensus vs Kalshi price."""
        vegas_prob = getattr(sf, "vegas_implied_prob", 0)
        kalshi_price = getattr(sf, "kalshi_price", 0)
        fetched_at = getattr(sf, "time_since_odds_update", 0)

        if vegas_prob <= 0.02 or vegas_prob >= 0.98:
            return None
        if kalshi_price <= 0.02 or kalshi_price >= 0.98:
            return None

        # Time-decay: how fresh is the Vegas data?
        # time_since_odds_update is already seconds-ago, compute freshness
        age_seconds = fetched_at if fetched_at > 0 else ODDS_DEAD_SECONDS
        if age_seconds > ODDS_DEAD_SECONDS:
            return None

        freshness = max(0.0, 1.0 - age_seconds / ODDS_DEAD_SECONDS)

        discrepancy = kalshi_price - vegas_prob
        abs_disc = abs(discrepancy)

        if abs_disc < 0.03:  # too small to be meaningful
            return None

        # Direction: if Kalshi > Vegas, Kalshi is overpriced → NO
        direction = "no" if discrepancy > 0 else "yes"

        # Strength scales with discrepancy magnitude
        strength = min(1.0, abs_disc / 0.25)  # 25% disc = max strength

        # Bookmaker agreement boosts strength
        num_books = getattr(sf, "num_bookmakers", 0)
        book_spread = getattr(sf, "bookmaker_spread", 1.0)
        if num_books >= 6 and book_spread < 0.05:
            strength = min(1.0, strength * 1.2)  # strong agreement
        elif num_books < 3:
            strength *= 0.6  # few bookmakers = less reliable

        return PredictionSignal(
            source="vegas_consensus",
            direction=direction,
            strength=strength,
            freshness=freshness,
            details=f"disc={discrepancy:+.3f} books={num_books} spread={book_spread:.3f}",
        )

    def _compute_social_signal(self, sf: Any) -> PredictionSignal | None:
        """Signal 2: Social media sentiment from Reddit/Twitter."""
        # The realtime feed populates these on GameOdds objects,
        # but they flow through SportsFeatures via the edge_signal composite.
        # We need the raw social sentiment — check if it's available.
        edge_signal = getattr(sf, "edge_signal", 0)
        confidence_signal = getattr(sf, "confidence_signal", 0)

        # edge_signal already includes social sentiment if available.
        # We extract a weak directional signal from the composite.
        if abs(edge_signal) < 0.05 or confidence_signal < 0.3:
            return None

        direction = "yes" if edge_signal > 0 else "no"
        strength = min(1.0, abs(edge_signal)) * 0.5  # half weight vs Vegas

        return PredictionSignal(
            source="composite_edge",
            direction=direction,
            strength=strength,
            freshness=0.8,  # composite is periodically refreshed
            details=f"edge_signal={edge_signal:.3f} conf={confidence_signal:.3f}",
        )

    def _compute_movement_signal(self, sf: Any) -> PredictionSignal | None:
        """Signal 3: Line movement detection (steam moves)."""
        steam = getattr(sf, "steam_move", False)
        reverse = getattr(sf, "reverse_line_move", False)
        vegas_moved = getattr(sf, "vegas_line_moved", 0)

        if not steam and not reverse and abs(vegas_moved) < 0.03:
            return None

        if steam:
            # Sharp money detected — follow the steam
            direction = "yes" if vegas_moved > 0 else "no"
            strength = 0.7
            details = f"steam_move line_moved={vegas_moved:+.3f}"
        elif reverse:
            # Reverse line movement — contrarian signal
            direction = "no" if vegas_moved > 0 else "yes"
            strength = 0.5
            details = f"reverse_line_move={vegas_moved:+.3f}"
        else:
            direction = "yes" if vegas_moved > 0 else "no"
            strength = min(0.6, abs(vegas_moved) * 4)
            details = f"line_moved={vegas_moved:+.3f}"

        return PredictionSignal(
            source="line_movement",
            direction=direction,
            strength=strength,
            freshness=0.9,
            details=details,
        )

    def _compute_live_signal(self, sf: Any) -> PredictionSignal | None:
        """Signal 4: Live game state (if in-progress)."""
        is_live = getattr(sf, "is_live", False)
        if not is_live:
            return None

        progress = getattr(sf, "game_progress", 0)
        score_diff = getattr(sf, "score_differential", 0)
        is_blowout = getattr(sf, "is_blowout", False)
        is_garbage = getattr(sf, "is_garbage_time", False)
        is_crunch = getattr(sf, "is_crunch_time", False)

        if progress < 0.3:
            return None  # too early to signal

        # Blowout in late game — high confidence leader wins
        if is_blowout and progress > 0.70:
            direction = "yes" if score_diff > 0 else "no"
            strength = min(1.0, 0.6 + progress * 0.4)
            return PredictionSignal(
                source="live_blowout",
                direction=direction,
                strength=strength,
                freshness=1.0,
                details=f"blowout diff={score_diff} progress={progress:.0%}",
            )

        # Garbage time — fade the market (it often overreacts to final scores)
        if is_garbage:
            direction = "no" if score_diff > 0 else "yes"
            strength = 0.3  # weak signal
            return PredictionSignal(
                source="live_garbage_fade",
                direction=direction,
                strength=strength,
                freshness=1.0,
                details=f"garbage_time diff={score_diff}",
            )

        # Close game, crunch time — momentum matters more
        if is_crunch:
            momentum = getattr(sf, "momentum_home", 0)
            if abs(momentum) > 2.0:
                direction = "yes" if momentum > 0 else "no"
                strength = min(0.6, abs(momentum) / 10.0)
                return PredictionSignal(
                    source="live_crunch_momentum",
                    direction=direction,
                    strength=strength,
                    freshness=1.0,
                    details=f"crunch_time momentum={momentum:.1f}",
                )

        return None

    def _fuse_signals(
        self,
        signals: list[PredictionSignal],
        sf: Any,
    ) -> SportsV2Prediction | None:
        """
        Fuse multiple signals into a single prediction.

        Weighted fusion:
        - Each signal contributes strength × freshness to its direction
        - Agreement between signals boosts confidence
        - Conflicting signals reduce confidence
        """
        kalshi_price = getattr(sf, "kalshi_price", 0.5)
        vegas_prob = getattr(sf, "vegas_implied_prob", 0)

        # Weighted vote
        yes_weight = 0.0
        no_weight = 0.0
        total_weight = 0.0

        # Source priority weights
        SOURCE_WEIGHTS = {
            "vegas_consensus": 3.0,      # Vegas is the strongest signal
            "line_movement": 1.5,        # Line movement is informative
            "live_blowout": 2.5,         # Late blowouts are very predictable
            "live_crunch_momentum": 1.0,
            "live_garbage_fade": 0.5,    # Weak signal
            "composite_edge": 1.0,
        }

        for sig in signals:
            source_w = SOURCE_WEIGHTS.get(sig.source, 1.0)
            effective_weight = sig.strength * sig.freshness * source_w

            if sig.direction == "yes":
                yes_weight += effective_weight
            else:
                no_weight += effective_weight
            total_weight += effective_weight

        if total_weight < 0.1:
            return None

        # Direction
        if yes_weight > no_weight:
            side = "yes"
            direction_strength = yes_weight / total_weight
        else:
            side = "no"
            direction_strength = no_weight / total_weight

        # Agreement score: 1.0 = all signals agree, 0.5 = split
        agreement = direction_strength

        # Determine predicted probability
        if vegas_prob > 0.02:
            # Use Vegas as the "true" probability anchor
            if side == "yes":
                predicted_prob = vegas_prob
            else:
                predicted_prob = 1.0 - vegas_prob
        else:
            # No Vegas data — use signal strength to estimate
            predicted_prob = 0.5 + (direction_strength - 0.5) * 0.3

        # Compute edge
        if side == "yes":
            cost = kalshi_price
        else:
            cost = 1.0 - kalshi_price
        edge = predicted_prob - cost

        # Confidence: base from agreement, boosted by signal count and quality
        confidence = 0.35 + agreement * 0.35  # 0.35 to 0.70 range
        # Bonus for multiple agreeing signals
        if len(signals) >= 3 and agreement > 0.75:
            confidence += 0.15  # strong multi-signal agreement
        elif len(signals) >= 2 and agreement > 0.65:
            confidence += 0.08
        # Penalty for single weak signal
        if len(signals) == 1 and signals[0].strength < 0.5:
            confidence -= 0.10

        confidence = max(0.20, min(0.95, confidence))

        # Dominant signal
        dominant = max(signals, key=lambda s: s.strength * s.freshness)

        return SportsV2Prediction(
            side=side,
            confidence=confidence,
            predicted_prob=predicted_prob,
            edge=edge,
            signals=signals,
            signal_agreement=agreement,
            dominant_signal=dominant.source,
            vegas_prob=vegas_prob,
            kalshi_price=kalshi_price,
            discrepancy=kalshi_price - vegas_prob if vegas_prob > 0 else 0,
        )

    def _kalshi_only_fallback(
        self,
        sf: Any,
        base_features: Any,
    ) -> SportsV2Prediction | None:
        """
        Conservative fallback when no external signals available.

        Phase 30: Much more conservative than V1 to reduce losses.
        Only trades when there's a clear market microstructure signal.
        """
        price = getattr(sf, "kalshi_price", 0)
        if price <= 0.05 or price >= 0.95:
            return None

        if base_features is None:
            return None

        volume = getattr(base_features, "volume", 0)
        hours = getattr(base_features, "hours_to_expiry", 0)

        # Extremely conservative: need good volume and time
        if volume < 50 or hours < 1.0:
            return None

        # Only trade extreme mispricings (>10% from nearest anchor)
        sport_id = getattr(sf, "sport_id", "")
        base_rates = {
            "nba": {"game": 0.50, "prop": 0.30},
            "nfl": {"game": 0.50, "prop": 0.35},
            "mlb": {"game": 0.50, "prop": 0.25},
            "nhl": {"game": 0.50, "prop": 0.25},
            "ncaab": {"game": 0.50, "prop": 0.30},
        }
        rates = base_rates.get(sport_id, {"game": 0.50, "prop": 0.25})
        market_type = getattr(sf, "market_type", "moneyline")
        anchor = rates["game"] if market_type == "moneyline" else rates["prop"]

        deviation = price - anchor
        if abs(deviation) < 0.10:  # need 10%+ deviation
            return None

        if deviation > 0:
            side = "no"
            predicted_prob = 1.0 - anchor
            cost = 1.0 - price
        else:
            side = "yes"
            predicted_prob = anchor
            cost = price

        edge = predicted_prob - cost
        if edge < 0.08:  # very high bar for kalshi-only
            return None

        return SportsV2Prediction(
            side=side,
            confidence=0.35,  # very low confidence
            predicted_prob=predicted_prob,
            edge=edge,
            model_name="sports_v2_kalshi_only",
            signals=[PredictionSignal(
                source="kalshi_only_mean_revert",
                direction=side,
                strength=0.3,
                freshness=1.0,
                details=f"price={price:.2f} anchor={anchor:.2f} dev={deviation:+.2f}",
            )],
            signal_agreement=0.5,
            dominant_signal="kalshi_only_mean_revert",
            kalshi_price=price,
            sport_id=sport_id,
            market_type=market_type,
        )

    def record_outcome(self, sport_id: str, won: bool, pnl_cents: int = 0) -> None:
        """Record outcome for circuit breaker."""
        self.circuit_breaker.record_outcome(sport_id, won, pnl_cents)

    def stats(self) -> dict[str, Any]:
        return {
            "version": "v2.0",
            "stats": dict(self._stats),
            "circuit_breaker": self.circuit_breaker.stats(),
            "hedger": self.hedger.stats(),
        }


# Singleton
sports_predictor_v2 = SportsPredictorV2()
