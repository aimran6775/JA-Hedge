"""
Frankenstein — Multi-Factor Confidence Scoring Engine.

Every trade gets a detailed confidence breakdown across 6 dimensions.
The composite score determines a letter grade (A+ → F) and a final
confidence multiplier that gates trade execution.

Factors:
  1. Model Strength  — Is a trained ML model predicting, or the heuristic?
  2. Edge Quality     — How large & reliable is the predicted edge vs market?
  3. Liquidity        — Bid/ask spread, volume, order book depth
  4. Timing           — Hours to expiry, exchange session, day of week
  5. Volume Signal    — Confirmation from unusual volume patterns
  6. Risk Context     — Portfolio heat, drawdown, position concentration

Each factor scores 0-100, with a weight. The weighted composite
produces the final confidence grade used for trade decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.ai.features import MarketFeatures
from app.ai.models import Prediction
from app.logging_config import get_logger

log = get_logger("frankenstein.confidence")


# ── Factor Weights (must sum to 1.0) ─────────────────────────────────────

FACTOR_WEIGHTS = {
    "model_strength": 0.30,    # Phase 17: Increase — model quality is most important
    "edge_quality": 0.30,      # Phase 17: Increase — edge must be real
    "liquidity": 0.20,         # Phase 17: Increase — can't profit in illiquid markets
    "timing": 0.10,            # Phase 17: Decrease — less important
    "volume_signal": 0.05,     # Phase 17: Decrease — weak signal
    "risk_context": 0.05,      # Phase 17: Decrease — handled by risk manager
}

# ── Grade Thresholds ──────────────────────────────────────────────────────

GRADE_MAP = [
    (90, "A+", "Excellent — very high conviction"),
    (80, "A",  "Strong — high conviction trade"),
    (70, "B+", "Good — solid signal with minor concerns"),
    (60, "B",  "Decent — above average confidence"),
    (50, "C+", "Fair — moderate confidence"),
    (40, "C",  "Marginal — proceed with caution"),
    (35, "D+", "Below average — proceed carefully"),
    (30, "D",  "Weak — low confidence, small position only"),
    (0,  "F",  "Fail — should not trade"),
]


@dataclass
class ConfidenceFactor:
    """A single scored factor in the confidence breakdown."""
    name: str
    score: float          # 0–100
    weight: float         # 0–1
    weighted: float = 0.0 # score * weight
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": round(self.score, 1),
            "weight": round(self.weight, 2),
            "weighted": round(self.weighted, 1),
            "reason": self.reason,
        }


@dataclass
class ConfidenceBreakdown:
    """Full multi-factor confidence assessment for a trade."""
    composite_score: float = 0.0  # 0–100
    grade: str = "F"
    grade_label: str = ""
    factors: list[ConfidenceFactor] = field(default_factory=list)
    should_trade: bool = False
    min_grade_to_trade: str = "A"

    def to_dict(self) -> dict[str, Any]:
        return {
            "composite_score": round(self.composite_score, 1),
            "grade": self.grade,
            "grade_label": self.grade_label,
            "should_trade": self.should_trade,
            "factors": [f.to_dict() for f in self.factors],
        }


class ConfidenceScorer:
    """
    Scores every potential trade across 6 dimensions.

    Usage:
        scorer = ConfidenceScorer()
        breakdown = scorer.score(prediction, features, model_trained=True)
        if breakdown.should_trade:
            execute_trade(...)
    """

    def __init__(
        self,
        min_grade: str = "A",
        portfolio_heat: float = 0.0,
        current_drawdown_pct: float = 0.0,
        open_positions: int = 0,
        max_positions: int = 20,
    ):
        self.min_grade = min_grade
        self.portfolio_heat = portfolio_heat
        self.current_drawdown_pct = current_drawdown_pct
        self.open_positions = open_positions
        self.max_positions = max_positions

    def score(
        self,
        prediction: Prediction,
        features: MarketFeatures,
        *,
        model_trained: bool = False,
        has_vegas: bool = False,
        is_sports: bool = False,
        exchange_session: str = "regular",
    ) -> ConfidenceBreakdown:
        """Compute full confidence breakdown for a trade candidate."""

        factors: list[ConfidenceFactor] = []

        # 1. Model Strength
        factors.append(self._score_model_strength(
            prediction, model_trained, has_vegas, is_sports
        ))

        # 2. Edge Quality
        factors.append(self._score_edge_quality(prediction, features))

        # 3. Liquidity
        factors.append(self._score_liquidity(features))

        # 4. Timing
        factors.append(self._score_timing(features, exchange_session))

        # 5. Volume Signal
        factors.append(self._score_volume(prediction, features))

        # 6. Risk Context
        factors.append(self._score_risk_context())

        # Compute weighted composite
        composite = sum(f.weighted for f in factors)
        composite = max(0.0, min(100.0, composite))

        # Determine grade
        grade, grade_label = "F", "Fail"
        for threshold, g, label in GRADE_MAP:
            if composite >= threshold:
                grade, grade_label = g, label
                break

        # Should we trade?
        grade_order = ["F", "D", "D+", "C", "C+", "B", "B+", "A", "A+"]
        should_trade = grade_order.index(grade) >= grade_order.index(self.min_grade)

        # ── LIQUIDITY VETO ───────────────────────────────────────
        # Even if the composite grade is high, a liquidity score < 20
        # means the book is too thin to trade reliably.  Markets with
        # volume < 10 or spread > 30% are untradeable regardless.
        liquidity_factor = next((f for f in factors if f.name == "Liquidity"), None)
        if liquidity_factor and liquidity_factor.score < 20:
            should_trade = False
            grade_label = f"{grade_label} — VETOED by liquidity ({liquidity_factor.score:.0f}/100)"

        return ConfidenceBreakdown(
            composite_score=composite,
            grade=grade,
            grade_label=grade_label,
            factors=factors,
            should_trade=should_trade,
            min_grade_to_trade=self.min_grade,
        )

    # ── Factor 1: Model Strength ──────────────────────────────────────

    def _score_model_strength(
        self,
        prediction: Prediction,
        model_trained: bool,
        has_vegas: bool,
        is_sports: bool,
    ) -> ConfidenceFactor:
        """
        Score model strength using REAL uncertainty metrics:
        - Tree agreement (how much individual trees agree)
        - Calibration quality (is the model well-calibrated?)
        - Prediction standard deviation (raw variance)
        - Model training status
        """
        score = 0.0
        reasons = []

        # ── Base: trained vs heuristic ──────────────────────
        if model_trained:
            score += 35
            reasons.append("Trained ML model active")
        else:
            score += 10
            reasons.append("Heuristic only (no ML)")

        # ── Tree Agreement (0–1, from individual tree variance) ──
        agreement = getattr(prediction, "tree_agreement", 1.0)
        if agreement >= 0.85:
            score += 25
            reasons.append(f"High tree agreement ({agreement:.0%})")
        elif agreement >= 0.65:
            score += 15
            reasons.append(f"Moderate tree agreement ({agreement:.0%})")
        elif agreement >= 0.45:
            score += 5
            reasons.append(f"Low tree agreement ({agreement:.0%})")
        else:
            score -= 10
            reasons.append(f"Poor tree agreement ({agreement:.0%})")

        # ── Prediction Std (lower = more certain) ───────────
        pred_std = getattr(prediction, "prediction_std", 0.0)
        if pred_std < 0.03:
            score += 10
            reasons.append(f"Low prediction variance (σ={pred_std:.3f})")
        elif pred_std < 0.07:
            score += 5
            reasons.append(f"Moderate variance (σ={pred_std:.3f})")
        elif pred_std > 0.10:
            score -= 10
            reasons.append(f"High variance (σ={pred_std:.3f})")

        # ── Calibration quality ─────────────────────────────
        is_calibrated = getattr(prediction, "is_calibrated", False)
        cal_error = getattr(prediction, "calibration_error", 0.0)
        if is_calibrated:
            if cal_error < 0.05:
                score += 15
                reasons.append(f"Well-calibrated (ECE={cal_error:.1%})")
            elif cal_error < 0.10:
                score += 8
                reasons.append(f"Decent calibration (ECE={cal_error:.1%})")
            else:
                score += 0
                reasons.append(f"Poor calibration (ECE={cal_error:.1%})")
        else:
            score += 0
            reasons.append("Not yet calibrated")

        # ── Vegas/sports modifiers ──────────────────────────
        if has_vegas and is_sports:
            score += 15
            reasons.append("Vegas odds data available")
        elif is_sports and not has_vegas:
            score += 3
            reasons.append("Sports market but no Vegas data")

        score = max(0, min(100, score))
        w = FACTOR_WEIGHTS["model_strength"]
        return ConfidenceFactor(
            name="Model Strength",
            score=score,
            weight=w,
            weighted=score * w,
            reason=" · ".join(reasons),
        )

    # ── Factor 2: Edge Quality ────────────────────────────────────────

    def _score_edge_quality(
        self, prediction: Prediction, features: MarketFeatures
    ) -> ConfidenceFactor:
        edge_abs = abs(prediction.edge)
        reasons = []

        # Phase 17: Stricter edge scoring — need bigger edges
        if edge_abs >= 0.15:
            score = 95
            reasons.append(f"Large edge ({edge_abs:.1%})")
        elif edge_abs >= 0.10:
            score = 80
            reasons.append(f"Strong edge ({edge_abs:.1%})")
        elif edge_abs >= 0.08:
            score = 65
            reasons.append(f"Good edge ({edge_abs:.1%})")
        elif edge_abs >= 0.06:
            score = 50
            reasons.append(f"Moderate edge ({edge_abs:.1%})")
        elif edge_abs >= 0.04:
            score = 30
            reasons.append(f"Small edge ({edge_abs:.1%})")
        else:
            score = 10
            reasons.append(f"Negligible edge ({edge_abs:.1%})")

        # Phase 17: HARD penalty if edge < half-spread — this is the #1 killer
        spread_cost = features.spread_pct / 2.0  # half-spread is real entry cost
        if spread_cost > 0 and edge_abs < spread_cost:
            # Edge doesn't even cover the spread — guaranteed loser
            penalty = 40
            score -= penalty
            reasons.append(f"SPREAD EATS EDGE: edge {edge_abs:.1%} < half-spread {spread_cost:.1%}")
        elif spread_cost > 0 and edge_abs < spread_cost * 1.5:
            # Edge barely covers spread — thin margin
            penalty = 20
            score -= penalty
            reasons.append(f"Thin margin: edge {edge_abs:.1%} vs half-spread {spread_cost:.1%}")

        # Bonus: edge relative to price (edge on cheap contracts is more valuable)
        mid = features.midpoint
        if mid > 0 and mid < 1:
            cost = min(mid, 1 - mid)
            if cost > 0:
                return_pct = edge_abs / cost
                if return_pct > 0.20:
                    score += 10
                    reasons.append(f"High return potential ({return_pct:.0%})")

        score = max(0, min(100, score))
        w = FACTOR_WEIGHTS["edge_quality"]
        return ConfidenceFactor(
            name="Edge Quality",
            score=score,
            weight=w,
            weighted=score * w,
            reason=" · ".join(reasons),
        )

    # ── Factor 3: Liquidity ───────────────────────────────────────────

    def _score_liquidity(self, features: MarketFeatures) -> ConfidenceFactor:
        reasons = []
        score = 50  # neutral start

        # Spread assessment
        spread = features.spread_pct
        if spread <= 0.03:
            score += 30
            reasons.append("Tight spread (≤3%)")
        elif spread <= 0.06:
            score += 15
            reasons.append("Decent spread (3-6%)")
        elif spread <= 0.10:
            score += 0
            reasons.append("Average spread (6-10%)")
        elif spread <= 0.15:
            score -= 15
            reasons.append("Wide spread (10-15%)")
        else:
            score -= 30
            reasons.append(f"Very wide spread ({spread:.0%})")

        # Volume assessment
        vol = features.volume
        if vol >= 500:
            score += 20
            reasons.append(f"High volume ({vol:.0f})")
        elif vol >= 100:
            score += 10
            reasons.append(f"Moderate volume ({vol:.0f})")
        elif vol >= 20:
            score += 0
            reasons.append(f"Low volume ({vol:.0f})")
        else:
            score -= 15
            reasons.append(f"Very low volume ({vol:.0f})")

        score = max(0, min(100, score))
        w = FACTOR_WEIGHTS["liquidity"]
        return ConfidenceFactor(
            name="Liquidity",
            score=score,
            weight=w,
            weighted=score * w,
            reason=" · ".join(reasons),
        )

    # ── Factor 4: Timing ─────────────────────────────────────────────

    def _score_timing(
        self, features: MarketFeatures, session: str
    ) -> ConfidenceFactor:
        reasons = []
        score = 50

        hours = features.hours_to_expiry

        # Time to expiry
        if 2 <= hours <= 48:
            score += 25
            reasons.append(f"Good window ({hours:.0f}h to close)")
        elif 0.5 <= hours < 2:
            score += 10
            reasons.append(f"Near expiry ({hours:.1f}h) — converging")
        elif hours < 0.5:
            score -= 20
            reasons.append(f"Too close to expiry ({hours*60:.0f}m)")
        elif hours > 168:
            score -= 10
            reasons.append(f"Far out ({hours:.0f}h) — more uncertainty")
        else:
            score += 5
            reasons.append(f"Moderate horizon ({hours:.0f}h)")

        # Session
        if session == "regular":
            score += 10
            reasons.append("Regular session")
        elif session == "overnight":
            score -= 5
            reasons.append("Overnight (lower liquidity)")
        elif session == "weekend":
            score -= 10
            reasons.append("Weekend (very low liquidity)")

        score = max(0, min(100, score))
        w = FACTOR_WEIGHTS["timing"]
        return ConfidenceFactor(
            name="Timing",
            score=score,
            weight=w,
            weighted=score * w,
            reason=" · ".join(reasons),
        )

    # ── Factor 5: Volume Signal ───────────────────────────────────────

    def _score_volume(
        self, prediction: Prediction, features: MarketFeatures
    ) -> ConfidenceFactor:
        reasons = []
        score = 50

        vr = features.volume_ratio
        price_move = features.price_change_5m

        # Volume confirmation: high volume + price moving in our direction
        our_direction = 1.0 if prediction.side == "yes" else -1.0
        aligned = (price_move * our_direction) > 0

        if vr > 2.0 and aligned:
            score += 35
            reasons.append(f"Strong volume confirmation ({vr:.1f}x, price aligned)")
        elif vr > 1.5 and aligned:
            score += 20
            reasons.append(f"Volume supports direction ({vr:.1f}x)")
        elif vr > 2.0 and not aligned:
            score -= 15
            reasons.append(f"Volume contradicts our direction ({vr:.1f}x)")
        elif vr < 0.5:
            score -= 10
            reasons.append("Below-average volume")
        else:
            reasons.append(f"Normal volume ({vr:.1f}x)")

        # Momentum confirmation
        mom_5m = abs(features.price_change_5m)
        if mom_5m > 0.03 and aligned:
            score += 10
            reasons.append(f"Strong momentum ({mom_5m:.1%}) in our direction")

        score = max(0, min(100, score))
        w = FACTOR_WEIGHTS["volume_signal"]
        return ConfidenceFactor(
            name="Volume Signal",
            score=score,
            weight=w,
            weighted=score * w,
            reason=" · ".join(reasons),
        )

    # ── Factor 6: Risk Context ────────────────────────────────────────

    def _score_risk_context(self) -> ConfidenceFactor:
        reasons = []
        score = 70  # start optimistic

        # Portfolio heat
        if self.portfolio_heat < 0.3:
            score += 15
            reasons.append(f"Low portfolio heat ({self.portfolio_heat:.0%})")
        elif self.portfolio_heat < 0.6:
            score += 0
            reasons.append(f"Moderate heat ({self.portfolio_heat:.0%})")
        else:
            score -= 20
            reasons.append(f"High portfolio heat ({self.portfolio_heat:.0%})")

        # Drawdown
        dd = self.current_drawdown_pct
        if dd < 0.03:
            score += 10
            reasons.append("No significant drawdown")
        elif dd < 0.07:
            score -= 5
            reasons.append(f"Moderate drawdown ({dd:.1%})")
        else:
            score -= 25
            reasons.append(f"Heavy drawdown ({dd:.1%}) — reduce exposure")

        # Position concentration
        fill_pct = self.open_positions / max(self.max_positions, 1)
        if fill_pct < 0.5:
            score += 5
            reasons.append(f"Capacity available ({self.open_positions}/{self.max_positions})")
        elif fill_pct > 0.8:
            score -= 15
            reasons.append(f"Near capacity ({self.open_positions}/{self.max_positions})")

        score = max(0, min(100, score))
        w = FACTOR_WEIGHTS["risk_context"]
        return ConfidenceFactor(
            name="Risk Context",
            score=score,
            weight=w,
            weighted=score * w,
            reason=" · ".join(reasons),
        )


# ── Convenience ───────────────────────────────────────────────────────────

def explain_decision_logic() -> dict[str, Any]:
    """Return a human-readable explanation of the decision pipeline.

    Used by the /api/frankenstein/decision-engine endpoint and the
    frontend Decision Engine tab.
    """
    return {
        "pipeline": [
            {
                "step": 1,
                "name": "Market Scan",
                "description": "Every 30 seconds, Frankenstein scans up to 500 active Kalshi markets. In Sports-Only mode, non-sports markets are filtered out.",
                "icon": "🔍",
            },
            {
                "step": 2,
                "name": "Feature Extraction",
                "description": "For each market, 60 features are computed: price, volume, spread, momentum, RSI, MACD, time-to-expiry, order book imbalance, cross-market signals, and (when available) Vegas odds data.",
                "icon": "📊",
            },
            {
                "step": 3,
                "name": "ML Prediction + Uncertainty",
                "description": "The XGBoost model predicts P(YES) for each market. Predictions are sampled at ~10 tree checkpoints to compute variance (uncertainty). Calibration data adjusts probabilities based on historical accuracy. Confidence = entropy + edge + tree agreement + calibration quality.",
                "icon": "🧠",
            },
            {
                "step": 4,
                "name": "Confidence Scoring",
                "description": "Each signal is scored across 6 factors: Model Strength, Edge Quality, Liquidity, Timing, Volume Signal, and Risk Context. A weighted composite produces a letter grade (A+ to F). Only A-grade or higher trades are executed.",
                "icon": "⭐",
            },
            {
                "step": 5,
                "name": "Threshold Gate",
                "description": "Signals must meet minimum confidence (65%) and minimum edge (6%). When the model isn't trained, thresholds are raised to 75%/12%. Sports without Vegas data require 68%/8%. Only A-grade signals (composite ≥ 80) pass.",
                "icon": "🚦",
            },
            {
                "step": 6,
                "name": "Kelly Sizing",
                "description": "For qualifying signals, the Kelly Criterion calculates optimal position size: f* = (p − c) / (1 − c), then scaled by a safety fraction (25% Kelly). The result determines how many contracts to buy.",
                "icon": "📐",
            },
            {
                "step": 7,
                "name": "Risk Check",
                "description": "The risk manager enforces position limits, daily loss caps, portfolio concentration rules, max spread, and sports-specific limits (max per game, live vs pregame).",
                "icon": "🛡️",
            },
            {
                "step": 8,
                "name": "EV Ranking",
                "description": "All surviving candidates are ranked by expected value (edge × count × (1 − cost)). Only the top 5 per scan are executed.",
                "icon": "🏆",
            },
            {
                "step": 9,
                "name": "Execution",
                "description": "Winning candidates are sent to the execution engine. In paper mode, they hit the simulator. Every trade is recorded in memory with its full confidence breakdown.",
                "icon": "⚡",
            },
            {
                "step": 10,
                "name": "Learn & Adapt",
                "description": "Outcomes are tracked. The model retrains hourly. Strategy parameters adapt: tighter after losses, looser after wins. Frankenstein evolves every generation.",
                "icon": "🔄",
            },
        ],
        "confidence_factors": [
            {
                "name": "Model Strength",
                "weight": "25%",
                "description": "Uses real ML uncertainty metrics: tree agreement (do individual XGBoost trees agree?), prediction variance (σ), calibration quality (ECE), plus training status and Vegas data availability.",
                "best_case": "Trained model + high tree agreement + well-calibrated + Vegas data → 100",
                "worst_case": "Heuristic only + high variance + no calibration → 10",
            },
            {
                "name": "Edge Quality",
                "weight": "25%",
                "description": "How large is the predicted edge vs the market price? Is the edge larger than the bid-ask spread? What's the potential return relative to cost?",
                "best_case": "Edge > 15%, exceeds spread, high return potential → 95+",
                "worst_case": "Edge < 2%, smaller than spread → 10",
            },
            {
                "name": "Liquidity",
                "weight": "15%",
                "description": "Can we enter and exit easily? Tight spreads and high volume mean lower execution risk.",
                "best_case": "Spread ≤ 3%, volume > 500 → 100",
                "worst_case": "Spread > 15%, volume < 20 → 5",
            },
            {
                "name": "Timing",
                "weight": "15%",
                "description": "Is the time horizon appropriate? Markets 2-48h from expiry are in the sweet spot. Too close risks illiquidity; too far means more uncertainty.",
                "best_case": "2-48h to expiry, regular session → 90",
                "worst_case": "< 30 min to expiry, weekend → 15",
            },
            {
                "name": "Volume Signal",
                "weight": "10%",
                "description": "Does trading volume confirm our direction? High volume moving in our predicted direction adds conviction; volume against us is a warning.",
                "best_case": "2x+ volume surge aligned with our prediction → 95",
                "worst_case": "High volume contradicting our direction → 25",
            },
            {
                "name": "Risk Context",
                "weight": "10%",
                "description": "Current portfolio state: drawdown level, portfolio heat (% deployed), and how close we are to position limits.",
                "best_case": "Low heat, no drawdown, plenty of capacity → 100",
                "worst_case": "High heat + deep drawdown + near capacity → 15",
            },
        ],
        "grade_scale": [
            {"grade": "A+", "min_score": 90, "description": "Excellent — very high conviction, full position"},
            {"grade": "A",  "min_score": 80, "description": "Strong — minimum grade to trade"},
            {"grade": "B+", "min_score": 70, "description": "Good — REJECTED, below A-grade cutoff"},
            {"grade": "B",  "min_score": 60, "description": "Decent — REJECTED"},
            {"grade": "C+", "min_score": 50, "description": "Fair — REJECTED"},
            {"grade": "C",  "min_score": 40, "description": "Marginal — REJECTED"},
            {"grade": "D",  "min_score": 30, "description": "Weak — REJECTED"},
            {"grade": "F",  "min_score": 0,  "description": "Fail — REJECTED"},
        ],
    }
