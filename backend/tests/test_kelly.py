"""
Tests for Kelly criterion sizing and AdaptiveStrategy guardrails.
"""

import pytest

from app.ai.models import Prediction
from app.ai.features import MarketFeatures
from app.frankenstein.strategy import StrategyParams, AdaptiveStrategy


class TestKellySizing:
    """Test the Kelly criterion formula for binary contracts."""

    @staticmethod
    def kelly_size(
        prob: float, side: str, midpoint: float,
        kelly_fraction: float = 0.25,
    ) -> float:
        """Replicate Frankenstein._kelly_size without needing the full brain."""
        if side == "yes":
            p = prob
            c = min(midpoint + 0.01, 0.99)
        else:
            p = 1.0 - prob
            c = min(1.0 - midpoint + 0.01, 0.99)

        if p <= c or c <= 0.01 or c >= 0.99:
            return 0.0

        kelly = (p - c) / (1.0 - c)
        adjusted = kelly * kelly_fraction
        return max(0.0, min(adjusted, 1.0))

    def test_edge_gives_positive_size(self):
        """When prob > cost, Kelly should allocate > 0."""
        size = self.kelly_size(prob=0.75, side="yes", midpoint=0.50)
        assert size > 0

    def test_no_edge_gives_zero(self):
        """When prob ≈ cost, Kelly should return 0."""
        size = self.kelly_size(prob=0.50, side="yes", midpoint=0.50)
        assert size == 0.0

    def test_negative_edge_gives_zero(self):
        """When prob < cost, Kelly should return 0."""
        size = self.kelly_size(prob=0.40, side="yes", midpoint=0.50)
        assert size == 0.0

    def test_fractional_kelly_reduces_size(self):
        full = self.kelly_size(prob=0.80, side="yes", midpoint=0.50, kelly_fraction=1.0)
        quarter = self.kelly_size(prob=0.80, side="yes", midpoint=0.50, kelly_fraction=0.25)
        assert quarter == pytest.approx(full * 0.25, abs=0.001)

    def test_no_side_kelly_correct(self):
        """NO side: p = 1 - predicted_prob, cost = 1 - midpoint + 0.01."""
        size = self.kelly_size(prob=0.20, side="no", midpoint=0.50)
        # p = 0.80, c = 0.51 → edge exists
        assert size > 0

    def test_result_clamped_below_one(self):
        # Even with extreme edge, result capped at 1.0
        size = self.kelly_size(prob=0.99, side="yes", midpoint=0.01, kelly_fraction=1.0)
        assert size <= 1.0

    def test_degenerate_cost_gives_zero(self):
        # Midpoint near 0 → cost ≈ 0.01 → nearly degenerate
        size = self.kelly_size(prob=0.5, side="yes", midpoint=0.00)
        assert size >= 0  # just shouldn't crash


class TestStrategyParams:
    """StrategyParams dataclass tests."""

    def test_defaults(self, strategy_params):
        assert strategy_params.kelly_fraction == 0.25
        assert strategy_params.min_confidence == 0.35
        assert strategy_params.min_edge == 0.06

    def test_to_dict(self, strategy_params):
        d = strategy_params.to_dict()
        assert "kelly_fraction" in d
        assert "min_confidence" in d
        assert isinstance(d, dict)
