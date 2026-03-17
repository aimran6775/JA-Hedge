"""
Tests for Prediction dataclass and _build_prediction confidence formula.
"""

import math
import pytest

from app.ai.models import Prediction


class TestPrediction:
    """Prediction dataclass tests."""

    def test_raw_prob_field_exists(self):
        p = Prediction(side="yes", confidence=0.5, predicted_prob=0.7, edge=0.1, raw_prob=0.68)
        assert p.raw_prob == 0.68

    def test_raw_prob_defaults_to_zero(self):
        p = Prediction(side="yes", confidence=0.5, predicted_prob=0.7, edge=0.1)
        assert p.raw_prob == 0.0

    def test_uncertainty_fields_default(self):
        p = Prediction(side="yes", confidence=0.5, predicted_prob=0.7, edge=0.1)
        assert p.tree_agreement == 1.0
        assert p.prediction_std == 0.0
        assert p.calibrated_prob is None
        assert p.calibration_error == 0.0
        assert p.is_calibrated is False


class TestConfidenceFormula:
    """Test the entropy-based confidence formula produces sane values."""

    @staticmethod
    def compute_confidence(
        prob: float, market_price: float,
        tree_agreement: float = 0.85, cal_error: float = 0.0,
    ) -> float:
        """Replicate _build_prediction's confidence formula."""
        effective_prob = prob
        effective_edge = effective_prob - market_price

        p_clamped = max(0.01, min(0.99, effective_prob))
        entropy = -(p_clamped * math.log2(p_clamped) +
                     (1 - p_clamped) * math.log2(1 - p_clamped))
        decisiveness = 1.0 - entropy

        edge_signal = min(abs(effective_edge) / 0.20, 1.0)
        cal_penalty = max(0.0, 1.0 - cal_error * 5.0)

        confidence = (
            0.30 * decisiveness +
            0.30 * edge_signal +
            0.25 * tree_agreement +
            0.15 * cal_penalty
        )
        return max(0.05, min(0.99, confidence))

    def test_high_edge_high_agreement_gives_high_confidence(self):
        c = self.compute_confidence(0.90, 0.50, tree_agreement=0.95)
        assert c > 0.70

    def test_low_edge_gives_moderate_confidence(self):
        c = self.compute_confidence(0.55, 0.50, tree_agreement=0.85)
        assert c < 0.50

    def test_no_agreement_reduces_confidence(self):
        high = self.compute_confidence(0.80, 0.50, tree_agreement=0.95)
        low = self.compute_confidence(0.80, 0.50, tree_agreement=0.30)
        assert high > low

    def test_calibration_error_reduces_confidence(self):
        good = self.compute_confidence(0.80, 0.50, cal_error=0.0)
        bad = self.compute_confidence(0.80, 0.50, cal_error=0.15)
        assert good > bad

    def test_confidence_always_in_range(self):
        for prob in [0.01, 0.1, 0.5, 0.9, 0.99]:
            for price in [0.1, 0.5, 0.9]:
                c = self.compute_confidence(prob, price)
                assert 0.05 <= c <= 0.99
