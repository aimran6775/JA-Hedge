"""
JA Hedge — Pre-Built Trading Strategies Engine.

Real, battle-tested prediction-market strategies:

1. MOMENTUM_CHASER     — Follow recent price trends near resolution
2. CONTRARIAN_FADE     — Fade extreme prices far from expiry
3. SPREAD_CAPTURE      — Market-make inside wide spreads
4. EXPIRY_CONVERGENCE  — Trade convergence to 0/100 near expiry
5. VOLUME_BREAKOUT     — Enter on volume spikes confirming direction
6. MEAN_REVERSION      — Bet against overreactions (far from expiry)
7. SHARP_MONEY         — Follow smart-money signals (large block trades)
8. KELLY_OPTIMAL       — Pure Kelly criterion on any detected edge

Each strategy produces a StrategySignal with:
  - ticker, side, confidence, edge, recommended size
  - strategy_name, reasoning
"""

from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.ai.features import MarketFeatures
from app.ai.models import Prediction
from app.kalshi.models import Market, MarketStatus
from app.logging_config import get_logger

log = get_logger("strategies.engine")


# ── Data Types ────────────────────────────────────────────────────────────


class StrategyName(str, Enum):
    MOMENTUM_CHASER = "momentum_chaser"
    CONTRARIAN_FADE = "contrarian_fade"
    SPREAD_CAPTURE = "spread_capture"
    EXPIRY_CONVERGENCE = "expiry_convergence"
    VOLUME_BREAKOUT = "volume_breakout"
    MEAN_REVERSION = "mean_reversion"
    SHARP_MONEY = "sharp_money"
    KELLY_OPTIMAL = "kelly_optimal"


@dataclass
class StrategySignal:
    """Output from a strategy evaluation."""

    ticker: str
    strategy: str
    side: str                    # "yes" or "no"
    confidence: float            # 0.0 – 1.0
    edge: float                  # predicted edge vs market price
    predicted_prob: float        # strategy's estimated true probability
    recommended_count: int       # suggested position size
    price_cents: int             # suggested limit price
    expected_profit: float       # edge * count * $1
    reasoning: str               # human-readable explanation
    urgency: float = 0.5        # 0 = can wait, 1 = act now
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "strategy": self.strategy,
            "side": self.side,
            "confidence": round(self.confidence, 4),
            "edge": round(self.edge, 4),
            "predicted_prob": round(self.predicted_prob, 4),
            "recommended_count": self.recommended_count,
            "price_cents": self.price_cents,
            "expected_profit": round(self.expected_profit, 4),
            "reasoning": self.reasoning,
            "urgency": round(self.urgency, 2),
            "timestamp": self.timestamp,
        }


@dataclass
class StrategyConfig:
    """User-configurable parameters for each strategy."""

    enabled: bool = True
    min_confidence: float = 0.55
    min_edge: float = 0.02
    max_position_pct: float = 0.05   # max % of balance per trade
    kelly_fraction: float = 0.25
    max_positions: int = 5
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


# ── Strategy Base ─────────────────────────────────────────────────────────


class TradingStrategyBase(ABC):
    """Base class for all pre-built strategies."""

    @property
    @abstractmethod
    def name(self) -> StrategyName:
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        ...

    @property
    @abstractmethod
    def risk_level(self) -> str:
        """'low', 'medium', 'high'"""
        ...

    @property
    def default_config(self) -> StrategyConfig:
        return StrategyConfig(description=self.description)

    @abstractmethod
    def evaluate(
        self,
        market: Market,
        features: MarketFeatures,
        prediction: Prediction,
        balance_cents: int,
    ) -> StrategySignal | None:
        """
        Evaluate a market for this strategy.

        Returns a StrategySignal if an opportunity is found, else None.
        """
        ...

    def _kelly_size(
        self, confidence: float, edge: float, balance_cents: int,
        price_cents: int, max_pct: float = 0.05, kelly_frac: float = 0.25,
    ) -> int:
        """Kelly criterion position sizing for binary contracts."""
        if edge <= 0 or price_cents <= 0 or price_cents >= 100:
            return 0
        p = confidence
        c = price_cents / 100.0
        if p <= c:
            return 0
        kelly = (p - c) / (1.0 - c)
        adjusted = kelly * kelly_frac
        max_cost = balance_cents * max_pct
        cost_per = price_cents
        max_contracts = int(max_cost / cost_per) if cost_per > 0 else 0
        count = max(1, int(adjusted * max_contracts))
        return min(count, 50)  # hard cap


# ── Strategy 1: Momentum Chaser ──────────────────────────────────────────


class MomentumChaser(TradingStrategyBase):
    """
    Follow recent price momentum in prediction markets.

    Prediction markets CONVERGE toward truth — momentum is a real signal,
    not noise. When a market moves 5%+ in a direction with volume, the
    informed traders are likely moving it toward the correct outcome.

    Best for: Markets <48h from expiry with clear directional movement.
    """

    @property
    def name(self) -> StrategyName:
        return StrategyName.MOMENTUM_CHASER

    @property
    def display_name(self) -> str:
        return "Momentum Chaser"

    @property
    def description(self) -> str:
        return "Follow strong price trends near resolution — prediction markets converge toward truth"

    @property
    def risk_level(self) -> str:
        return "medium"

    def evaluate(self, market: Market, features: MarketFeatures, prediction: Prediction, balance_cents: int) -> StrategySignal | None:
        mid = features.midpoint
        if mid <= 0.05 or mid >= 0.95:
            return None

        # Need meaningful momentum (>2% in last 5min)
        momentum = features.price_change_5m
        if abs(momentum) < 0.02:
            return None

        # Stronger signal closer to expiry (convergence is real)
        if features.hours_to_expiry > 48:
            return None

        # Time urgency factor: more confident near expiry
        time_factor = max(0.3, 1.0 - features.hours_to_expiry / 48.0)

        # Volume confirmation boosts confidence
        volume_boost = 0.0
        if features.volume_ratio > 1.5:
            volume_boost = min(0.15, (features.volume_ratio - 1.0) * 0.1)

        if momentum > 0:
            # Price rising → YES is winning
            side = "yes"
            prob_yes = min(mid + abs(momentum) * 1.5, 0.95)
            edge = prob_yes - mid
            confidence = min(0.5 + abs(momentum) * 3.0 + volume_boost, 0.90) * time_factor
            price_cents = max(1, min(99, int(mid * 100) + 1))
        else:
            # Price falling → NO is winning
            side = "no"
            prob_yes = max(mid - abs(momentum) * 1.5, 0.05)
            edge = mid - prob_yes
            confidence = min(0.5 + abs(momentum) * 3.0 + volume_boost, 0.90) * time_factor
            price_cents = max(1, min(99, int((1 - mid) * 100) + 1))

        if confidence < 0.55 or edge < 0.02:
            return None

        count = self._kelly_size(confidence, edge, balance_cents, price_cents)
        if count <= 0:
            return None

        return StrategySignal(
            ticker=market.ticker,
            strategy=self.name.value,
            side=side,
            confidence=confidence,
            edge=edge,
            predicted_prob=prob_yes,
            recommended_count=count,
            price_cents=price_cents,
            expected_profit=edge * count,
            reasoning=f"5m momentum {momentum:+.1%} with {features.volume_ratio:.1f}x volume, {features.hours_to_expiry:.0f}h to expiry",
            urgency=time_factor,
        )


# ── Strategy 2: Contrarian Fade ──────────────────────────────────────────


class ContrarianFade(TradingStrategyBase):
    """
    Fade extreme prices far from expiry.

    When a market is at 85%+ or 15%- but has >72h to go, there's often
    reversion. Events far from resolution are uncertain — the market
    often over-extrapolates early information.

    Best for: Markets >72h from expiry at extreme prices with low volume.
    """

    @property
    def name(self) -> StrategyName:
        return StrategyName.CONTRARIAN_FADE

    @property
    def display_name(self) -> str:
        return "Contrarian Fade"

    @property
    def description(self) -> str:
        return "Fade extreme prices far from expiry — markets over-extrapolate early"

    @property
    def risk_level(self) -> str:
        return "high"

    def evaluate(self, market: Market, features: MarketFeatures, prediction: Prediction, balance_cents: int) -> StrategySignal | None:
        mid = features.midpoint
        if mid <= 0.10 or mid >= 0.90:
            return None

        # Only far from expiry
        if features.hours_to_expiry < 72:
            return None

        # Need extreme price
        dist_from_50 = abs(mid - 0.5)
        if dist_from_50 < 0.30:
            return None

        # Fade toward 50%
        if mid > 0.5:
            # Market says YES at 80%+ — fade by buying NO
            side = "no"
            reversion_target = mid - dist_from_50 * 0.3  # partial reversion
            prob_yes = reversion_target
            edge = mid - reversion_target
            price_cents = max(1, min(99, int((1 - mid) * 100) + 2))
        else:
            # Market says NO at 80%+ — fade by buying YES
            side = "yes"
            reversion_target = mid + dist_from_50 * 0.3
            prob_yes = reversion_target
            edge = reversion_target - mid
            price_cents = max(1, min(99, int(mid * 100) + 2))

        # Low volume = less informed = more likely to revert
        vol_factor = 1.0
        if features.volume_ratio < 0.5:
            vol_factor = 1.15

        confidence = min(0.50 + dist_from_50 * 0.3, 0.75) * vol_factor

        if confidence < 0.55 or edge < 0.03:
            return None

        count = self._kelly_size(confidence, edge, balance_cents, price_cents, kelly_frac=0.15)
        if count <= 0:
            return None

        return StrategySignal(
            ticker=market.ticker,
            strategy=self.name.value,
            side=side,
            confidence=confidence,
            edge=edge,
            predicted_prob=prob_yes,
            recommended_count=count,
            price_cents=price_cents,
            expected_profit=edge * count,
            reasoning=f"Market at {mid:.0%} with {features.hours_to_expiry:.0f}h remaining — over-extrapolation likely, partial reversion expected",
            urgency=0.3,
        )


# ── Strategy 3: Spread Capture ───────────────────────────────────────────


class SpreadCapture(TradingStrategyBase):
    """
    Market-make inside wide spreads for safe profit.

    When the bid-ask spread is >8¢, place a limit order inside the spread.
    If filled, we capture the spread premium. Low risk, low reward, high
    hit rate.

    Best for: Markets with wide spreads and moderate volume.
    """

    @property
    def name(self) -> StrategyName:
        return StrategyName.SPREAD_CAPTURE

    @property
    def display_name(self) -> str:
        return "Spread Capture"

    @property
    def description(self) -> str:
        return "Market-make inside wide spreads — low risk, consistent small gains"

    @property
    def risk_level(self) -> str:
        return "low"

    def evaluate(self, market: Market, features: MarketFeatures, prediction: Prediction, balance_cents: int) -> StrategySignal | None:
        mid = features.midpoint
        spread_cents = int(features.spread * 100)

        # Need meaningful spread
        if spread_cents < 8:
            return None

        # Don't market-make at extremes (high binary risk)
        if mid < 0.15 or mid > 0.85:
            return None

        # Prefer using model direction, but lean YES for the mid
        side = prediction.side if prediction.confidence > 0.52 else ("yes" if mid < 0.5 else "no")

        if side == "yes":
            # Place bid inside spread (above yes_bid)
            bid = float(market.yes_bid or 0)
            price_cents = max(1, int(bid * 100) + 2)
            edge = spread_cents / 200.0  # half the spread in probability terms
            prob_yes = mid + edge * 0.5
        else:
            no_bid = float(market.no_bid or 0) if market.no_bid else (1.0 - float(market.yes_ask or 1))
            price_cents = max(1, int(no_bid * 100) + 2)
            edge = spread_cents / 200.0
            prob_yes = mid - edge * 0.5

        confidence = min(0.55 + spread_cents * 0.008, 0.75)

        if edge < 0.02:
            return None

        # Small sizes for spread capture
        count = self._kelly_size(confidence, edge, balance_cents, price_cents, max_pct=0.03, kelly_frac=0.15)
        if count <= 0:
            count = 1

        return StrategySignal(
            ticker=market.ticker,
            strategy=self.name.value,
            side=side,
            confidence=confidence,
            edge=edge,
            predicted_prob=prob_yes,
            recommended_count=count,
            price_cents=price_cents,
            expected_profit=edge * count,
            reasoning=f"Spread {spread_cents}¢ — placing inside spread at {price_cents}¢, expected capture ~{spread_cents // 2}¢",
            urgency=0.4,
        )


# ── Strategy 4: Expiry Convergence ───────────────────────────────────────


class ExpiryConvergence(TradingStrategyBase):
    """
    Trade convergence to 0 or 100 very near expiry.

    Prediction markets MUST settle at 0 or 100. When a market is at 75%+
    or 25%- with <6h to expiry, the convergence toward the dominant side
    is highly reliable. This is the bread-and-butter of prediction market
    trading.

    Best for: Markets <6h from expiry with strong directional lean.
    """

    @property
    def name(self) -> StrategyName:
        return StrategyName.EXPIRY_CONVERGENCE

    @property
    def display_name(self) -> str:
        return "Expiry Convergence"

    @property
    def description(self) -> str:
        return "Trade convergence to 0/100 near expiry — the core prediction market edge"

    @property
    def risk_level(self) -> str:
        return "low"

    def evaluate(self, market: Market, features: MarketFeatures, prediction: Prediction, balance_cents: int) -> StrategySignal | None:
        mid = features.midpoint
        if mid <= 0.01 or mid >= 0.99:
            return None

        # Only very near expiry
        if features.hours_to_expiry > 6:
            return None

        # Need a strong lean
        dist = abs(mid - 0.5)
        if dist < 0.20:
            return None  # too uncertain near expiry

        # Convergence toward the dominant side
        if mid > 0.5:
            side = "yes"
            # Market says YES at X% — it should converge further toward 100
            # Our edge is (100 - X)% * probability_of_being_right
            prob_right = min(0.65 + dist * 0.5, 0.95)
            prob_yes = mid + (1.0 - mid) * 0.3  # partial convergence
            edge = prob_yes - mid
            price_cents = max(1, min(99, int(mid * 100) + 1))
        else:
            side = "no"
            prob_right = min(0.65 + dist * 0.5, 0.95)
            prob_yes = mid - mid * 0.3
            edge = mid - prob_yes
            price_cents = max(1, min(99, int((1 - mid) * 100) + 1))

        # More confidence when more extreme and closer to expiry
        time_boost = max(0.5, 1.0 - features.hours_to_expiry / 6.0)
        confidence = prob_right * time_boost

        if confidence < 0.60 or edge < 0.02:
            return None

        count = self._kelly_size(confidence, edge, balance_cents, price_cents)
        if count <= 0:
            return None

        return StrategySignal(
            ticker=market.ticker,
            strategy=self.name.value,
            side=side,
            confidence=confidence,
            edge=edge,
            predicted_prob=prob_yes,
            recommended_count=count,
            price_cents=price_cents,
            expected_profit=edge * count,
            reasoning=f"Market at {mid:.0%} with only {features.hours_to_expiry:.1f}h left — convergence toward {'100' if side == 'yes' else '0'} expected",
            urgency=min(1.0, 1.0 - features.hours_to_expiry / 6.0),
        )


# ── Strategy 5: Volume Breakout ──────────────────────────────────────────


class VolumeBreakout(TradingStrategyBase):
    """
    Enter on volume spikes that confirm price direction.

    When volume surges 2x+ above average AND price moves in the same
    direction, informed traders are likely acting on new information.

    Best for: Markets with sudden volume spikes + directional price action.
    """

    @property
    def name(self) -> StrategyName:
        return StrategyName.VOLUME_BREAKOUT

    @property
    def display_name(self) -> str:
        return "Volume Breakout"

    @property
    def description(self) -> str:
        return "Enter on volume spikes confirming direction — follow the informed money"

    @property
    def risk_level(self) -> str:
        return "medium"

    def evaluate(self, market: Market, features: MarketFeatures, prediction: Prediction, balance_cents: int) -> StrategySignal | None:
        mid = features.midpoint
        if mid <= 0.05 or mid >= 0.95:
            return None

        # Need a volume spike
        if features.volume_ratio < 2.0:
            return None

        # Need directional price movement to confirm
        price_move = features.price_change_5m
        if abs(price_move) < 0.015:
            return None

        # Volume and price must agree
        if (features.volume_ratio > 2.0 and abs(price_move) > 0.015):
            vol_strength = min(features.volume_ratio / 5.0, 1.0)

            if price_move > 0:
                side = "yes"
                prob_yes = min(mid + abs(price_move) * 2.0 * vol_strength, 0.95)
                edge = prob_yes - mid
                price_cents = max(1, min(99, int(mid * 100) + 1))
            else:
                side = "no"
                prob_yes = max(mid - abs(price_move) * 2.0 * vol_strength, 0.05)
                edge = mid - prob_yes
                price_cents = max(1, min(99, int((1 - mid) * 100) + 1))

            confidence = min(0.55 + vol_strength * 0.25 + abs(price_move) * 2.0, 0.88)

            if confidence < 0.55 or edge < 0.02:
                return None

            count = self._kelly_size(confidence, edge, balance_cents, price_cents)
            if count <= 0:
                return None

            return StrategySignal(
                ticker=market.ticker,
                strategy=self.name.value,
                side=side,
                confidence=confidence,
                edge=edge,
                predicted_prob=prob_yes,
                recommended_count=count,
                price_cents=price_cents,
                expected_profit=edge * count,
                reasoning=f"Volume spike {features.volume_ratio:.1f}x with {price_move:+.1%} move — informed traders active",
                urgency=0.8,
            )
        return None


# ── Strategy 6: Mean Reversion ───────────────────────────────────────────


class MeanReversion(TradingStrategyBase):
    """
    Bet against overreactions in prediction markets.

    After sudden large moves (>5% in 5min), markets often partially
    revert — especially when the move is on low volume (panic, not info).

    Best for: Markets with recent large moves on low relative volume.
    """

    @property
    def name(self) -> StrategyName:
        return StrategyName.MEAN_REVERSION

    @property
    def display_name(self) -> str:
        return "Mean Reversion"

    @property
    def description(self) -> str:
        return "Bet against overreactions — fade large moves on low volume"

    @property
    def risk_level(self) -> str:
        return "high"

    def evaluate(self, market: Market, features: MarketFeatures, prediction: Prediction, balance_cents: int) -> StrategySignal | None:
        mid = features.midpoint
        if mid <= 0.10 or mid >= 0.90:
            return None

        # Need a large recent move
        move = features.price_change_5m
        if abs(move) < 0.05:
            return None

        # Low volume = overreaction (not informed)
        # High volume = information (don't fade)
        if features.volume_ratio > 2.0:
            return None  # high volume moves are real

        # Far from expiry = more reversion room
        if features.hours_to_expiry < 12:
            return None

        # Fade the move
        reversion_pct = 0.4  # expect 40% reversion
        if move > 0:
            side = "no"
            prob_yes = mid - abs(move) * reversion_pct
            edge = mid - prob_yes
            price_cents = max(1, min(99, int((1 - mid) * 100) + 1))
        else:
            side = "yes"
            prob_yes = mid + abs(move) * reversion_pct
            edge = prob_yes - mid
            price_cents = max(1, min(99, int(mid * 100) + 1))

        # Confidence based on move size and low volume
        confidence = min(0.52 + abs(move) * 2.0, 0.72)

        if confidence < 0.55 or edge < 0.02:
            return None

        count = self._kelly_size(confidence, edge, balance_cents, price_cents, kelly_frac=0.15)
        if count <= 0:
            return None

        return StrategySignal(
            ticker=market.ticker,
            strategy=self.name.value,
            side=side,
            confidence=confidence,
            edge=edge,
            predicted_prob=prob_yes,
            recommended_count=count,
            price_cents=price_cents,
            expected_profit=edge * count,
            reasoning=f"Large move {move:+.1%} on low volume ({features.volume_ratio:.1f}x) — expecting {reversion_pct:.0%} reversion",
            urgency=0.6,
        )


# ── Strategy 7: Sharp Money ─────────────────────────────────────────────


class SharpMoney(TradingStrategyBase):
    """
    Follow smart-money signals: high-confidence model + volume.

    When the model prediction strongly disagrees with the market AND
    volume is confirming, smart money is likely on the right side.

    Best for: Markets where the model has high confidence + volume agrees.
    """

    @property
    def name(self) -> StrategyName:
        return StrategyName.SHARP_MONEY

    @property
    def display_name(self) -> str:
        return "Sharp Money"

    @property
    def description(self) -> str:
        return "Follow smart-money signals — model + volume + momentum alignment"

    @property
    def risk_level(self) -> str:
        return "medium"

    def evaluate(self, market: Market, features: MarketFeatures, prediction: Prediction, balance_cents: int) -> StrategySignal | None:
        mid = features.midpoint
        if mid <= 0.05 or mid >= 0.95:
            return None

        # Need strong model edge (model disagrees with market)
        if abs(prediction.edge) < 0.04:
            return None

        # Need decent model confidence
        if prediction.confidence < 0.58:
            return None

        # Volume should be present
        if features.volume < 5:
            return None

        # Momentum should agree with model
        momentum = features.price_change_5m
        momentum_agrees = (
            (prediction.side == "yes" and momentum >= 0) or
            (prediction.side == "no" and momentum <= 0)
        )

        if not momentum_agrees and abs(momentum) > 0.02:
            return None  # momentum strongly disagrees — skip

        side = prediction.side
        edge = abs(prediction.edge)

        # Boost confidence when all signals align
        alignment_boost = 0.0
        if momentum_agrees and abs(momentum) > 0.01:
            alignment_boost += 0.05
        if features.volume_ratio > 1.2:
            alignment_boost += 0.05

        confidence = min(prediction.confidence + alignment_boost, 0.92)

        if side == "yes":
            price_cents = max(1, min(99, int(mid * 100) + 1))
            prob_yes = prediction.predicted_prob
        else:
            price_cents = max(1, min(99, int((1 - mid) * 100) + 1))
            prob_yes = prediction.predicted_prob

        count = self._kelly_size(confidence, edge, balance_cents, price_cents)
        if count <= 0:
            return None

        reasons = [f"Model: {prediction.confidence:.0%} conf, {edge:.1%} edge"]
        if momentum_agrees and abs(momentum) > 0.01:
            reasons.append(f"Momentum confirms: {momentum:+.1%}")
        if features.volume_ratio > 1.2:
            reasons.append(f"Volume: {features.volume_ratio:.1f}x avg")

        return StrategySignal(
            ticker=market.ticker,
            strategy=self.name.value,
            side=side,
            confidence=confidence,
            edge=edge,
            predicted_prob=prob_yes,
            recommended_count=count,
            price_cents=price_cents,
            expected_profit=edge * count,
            reasoning=" | ".join(reasons),
            urgency=0.7,
        )


# ── Strategy 8: Kelly Optimal ────────────────────────────────────────────


class KellyOptimal(TradingStrategyBase):
    """
    Pure Kelly criterion on any detected edge.

    The simplest strategy — if the model detects ANY positive edge,
    size the position using Kelly criterion and trade. No additional
    filters. Maximum expected log-growth of bankroll.

    Best for: When the model is well-calibrated. Dangerous otherwise.
    """

    @property
    def name(self) -> StrategyName:
        return StrategyName.KELLY_OPTIMAL

    @property
    def display_name(self) -> str:
        return "Kelly Optimal"

    @property
    def description(self) -> str:
        return "Pure Kelly criterion — trade any detected edge at optimal size"

    @property
    def risk_level(self) -> str:
        return "high"

    @property
    def default_config(self) -> StrategyConfig:
        return StrategyConfig(
            enabled=False,  # disabled by default — dangerous with untrained model
            min_confidence=0.58,
            min_edge=0.03,
            kelly_fraction=0.20,
            description=self.description,
        )

    def evaluate(self, market: Market, features: MarketFeatures, prediction: Prediction, balance_cents: int) -> StrategySignal | None:
        mid = features.midpoint
        if mid <= 0.05 or mid >= 0.95:
            return None

        edge = abs(prediction.edge)
        if edge < 0.02:
            return None

        if prediction.confidence < 0.55:
            return None

        side = prediction.side
        if side == "yes":
            price_cents = max(1, min(99, int(mid * 100) + 1))
        else:
            price_cents = max(1, min(99, int((1 - mid) * 100) + 1))

        count = self._kelly_size(prediction.confidence, edge, balance_cents, price_cents, kelly_frac=0.20)
        if count <= 0:
            return None

        return StrategySignal(
            ticker=market.ticker,
            strategy=self.name.value,
            side=side,
            confidence=prediction.confidence,
            edge=edge,
            predicted_prob=prediction.predicted_prob,
            recommended_count=count,
            price_cents=price_cents,
            expected_profit=edge * count,
            reasoning=f"Kelly optimal: {prediction.confidence:.0%} conf, {edge:.1%} edge → {count} contracts",
            urgency=0.5,
        )


# ── Strategy Registry ────────────────────────────────────────────────────


# All available strategies
ALL_STRATEGIES: dict[StrategyName, TradingStrategyBase] = {
    StrategyName.MOMENTUM_CHASER: MomentumChaser(),
    StrategyName.CONTRARIAN_FADE: ContrarianFade(),
    StrategyName.SPREAD_CAPTURE: SpreadCapture(),
    StrategyName.EXPIRY_CONVERGENCE: ExpiryConvergence(),
    StrategyName.VOLUME_BREAKOUT: VolumeBreakout(),
    StrategyName.MEAN_REVERSION: MeanReversion(),
    StrategyName.SHARP_MONEY: SharpMoney(),
    StrategyName.KELLY_OPTIMAL: KellyOptimal(),
}


class StrategyEngine:
    """
    Multi-strategy engine that runs all enabled strategies
    against active markets and produces ranked signals.
    """

    def __init__(self) -> None:
        self._strategies = dict(ALL_STRATEGIES)
        self._configs: dict[str, StrategyConfig] = {
            s.name.value: s.default_config for s in self._strategies.values()
        }
        self._signal_history: list[StrategySignal] = []
        self._stats: dict[str, dict[str, int]] = {
            s.value: {"scans": 0, "signals": 0, "trades": 0, "wins": 0, "losses": 0}
            for s in StrategyName
        }

    @property
    def configs(self) -> dict[str, StrategyConfig]:
        return self._configs

    def set_config(self, strategy_name: str, config: StrategyConfig) -> None:
        """Update configuration for a specific strategy."""
        if strategy_name in self._configs:
            self._configs[strategy_name] = config
            log.info("strategy_config_updated", strategy=strategy_name, config=config.to_dict())

    def toggle_strategy(self, strategy_name: str, enabled: bool) -> None:
        """Enable or disable a specific strategy."""
        if strategy_name in self._configs:
            self._configs[strategy_name].enabled = enabled
            log.info("strategy_toggled", strategy=strategy_name, enabled=enabled)

    def scan_market(
        self,
        market: Market,
        features: MarketFeatures,
        prediction: Prediction,
        balance_cents: int,
    ) -> list[StrategySignal]:
        """
        Run all enabled strategies against a single market.

        Returns list of signals (may be empty or have multiple from
        different strategies for the same market).
        """
        signals: list[StrategySignal] = []

        for strat_name, strategy in self._strategies.items():
            config = self._configs.get(strat_name.value)
            if not config or not config.enabled:
                continue

            self._stats[strat_name.value]["scans"] += 1

            try:
                signal = strategy.evaluate(market, features, prediction, balance_cents)
                if signal is None:
                    continue

                # Apply per-strategy thresholds
                if signal.confidence < config.min_confidence:
                    continue
                if signal.edge < config.min_edge:
                    continue

                signals.append(signal)
                self._stats[strat_name.value]["signals"] += 1

            except Exception as e:
                log.error("strategy_eval_error", strategy=strat_name.value, error=str(e))

        return signals

    def scan_all_markets(
        self,
        markets: list[Market],
        features_map: dict[str, MarketFeatures],
        predictions_map: dict[str, Prediction],
        balance_cents: int,
    ) -> list[StrategySignal]:
        """
        Run all strategies against all markets.

        Returns signals ranked by expected value (best first).
        """
        all_signals: list[StrategySignal] = []

        for market in markets:
            features = features_map.get(market.ticker)
            prediction = predictions_map.get(market.ticker)
            if features is None or prediction is None:
                continue

            signals = self.scan_market(market, features, prediction, balance_cents)
            all_signals.extend(signals)

        # Rank by expected profit × confidence
        all_signals.sort(key=lambda s: s.expected_profit * s.confidence, reverse=True)

        # Keep history (last 200)
        self._signal_history.extend(all_signals)
        self._signal_history = self._signal_history[-200:]

        return all_signals

    def record_outcome(self, strategy_name: str, won: bool) -> None:
        """Record a trade outcome for strategy stats."""
        stats = self._stats.get(strategy_name, {})
        stats["trades"] = stats.get("trades", 0) + 1
        if won:
            stats["wins"] = stats.get("wins", 0) + 1
        else:
            stats["losses"] = stats.get("losses", 0) + 1

    def get_recent_signals(self, n: int = 50) -> list[dict]:
        """Get recent signals across all strategies."""
        return [s.to_dict() for s in self._signal_history[-n:]]

    def status(self) -> dict[str, Any]:
        """Full engine status for API."""
        strategies_info = []
        for strat_name, strategy in self._strategies.items():
            config = self._configs.get(strat_name.value, StrategyConfig())
            stats = self._stats.get(strat_name.value, {})
            total = stats.get("trades", 0)
            wins = stats.get("wins", 0)
            strategies_info.append({
                "name": strat_name.value,
                "display_name": strategy.display_name,
                "description": strategy.description,
                "risk_level": strategy.risk_level,
                "enabled": config.enabled,
                "config": config.to_dict(),
                "stats": {
                    "scans": stats.get("scans", 0),
                    "signals": stats.get("signals", 0),
                    "trades": total,
                    "wins": wins,
                    "losses": stats.get("losses", 0),
                    "win_rate": round(wins / total, 3) if total > 0 else 0.0,
                },
            })

        return {
            "total_strategies": len(self._strategies),
            "enabled_strategies": sum(1 for c in self._configs.values() if c.enabled),
            "total_signals_generated": sum(s.get("signals", 0) for s in self._stats.values()),
            "strategies": strategies_info,
            "recent_signals": self.get_recent_signals(20),
        }
