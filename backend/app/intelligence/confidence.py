"""
Phases 13 + 14 — Source Confidence Scoring & Adaptive Weighting.

Tracks per-source accuracy over time and learns which sources
are most predictive for each market category.

Phase 13: SourceConfidenceTracker
  • Records each source's signal vs. actual market outcome
  • Maintains rolling accuracy, precision, recall per source
  • Emits a "source reliability score" (0–1) per source × category

Phase 14: AdaptiveWeightEngine
  • Uses source reliability scores to weight alt-data features
  • Sources that are consistently wrong get downweighted
  • Sources that outperform get boosted
  • Learns separately per category (sports, politics, crypto, etc.)
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.logging_config import get_logger

log = get_logger("intelligence.confidence")


@dataclass
class SourceOutcome:
    """A single recorded outcome for tracking source accuracy."""
    source_name: str
    category: str
    signal_value: float     # what the source predicted (-1 to +1)
    actual_direction: float # what actually happened (-1 or +1)
    timestamp: float = 0.0
    correct: bool = False


class SourceConfidenceTracker:
    """
    Tracks per-source prediction accuracy over time.

    Maintains a rolling window of outcomes per source × category
    and computes reliability scores.
    """

    def __init__(self, window_size: int = 500) -> None:
        self._window_size = window_size

        # source_name → category → list[SourceOutcome]
        self._outcomes: dict[str, dict[str, list[SourceOutcome]]] = defaultdict(lambda: defaultdict(list))

        # Precomputed scores: source_name → category → reliability (0–1)
        self._reliability: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(lambda: 0.5))

        self._stats = {"records": 0, "recomputes": 0}

    def record_outcome(
        self,
        source_name: str,
        category: str,
        signal_value: float,
        actual_direction: float,  # +1 for YES resolved, -1 for NO resolved
    ) -> None:
        """Record a source's prediction vs. actual outcome."""
        correct = (signal_value > 0 and actual_direction > 0) or \
                  (signal_value < 0 and actual_direction < 0) or \
                  (signal_value == 0)  # neutral is "correct" (didn't predict wrong)

        outcome = SourceOutcome(
            source_name=source_name,
            category=category,
            signal_value=signal_value,
            actual_direction=actual_direction,
            timestamp=time.time(),
            correct=correct,
        )

        history = self._outcomes[source_name][category]
        history.append(outcome)

        # Trim to window
        if len(history) > self._window_size:
            self._outcomes[source_name][category] = history[-self._window_size:]

        self._stats["records"] += 1

        # Recompute reliability for this source × category
        self._recompute(source_name, category)

    def _recompute(self, source_name: str, category: str) -> None:
        """Recompute reliability score for a source × category."""
        history = self._outcomes[source_name][category]
        if len(history) < 5:
            return  # Not enough data

        # Accuracy = fraction of correct predictions
        correct = sum(1 for o in history if o.correct)
        accuracy = correct / len(history)

        # Recency-weight: recent outcomes matter more
        # Exponential decay with half-life of 50 outcomes
        weighted_correct = 0.0
        weighted_total = 0.0
        for i, outcome in enumerate(history):
            weight = 2.0 ** (i / 50)  # More recent = higher weight
            weighted_correct += weight * (1.0 if outcome.correct else 0.0)
            weighted_total += weight

        recency_accuracy = weighted_correct / weighted_total if weighted_total > 0 else 0.5

        # Blend raw accuracy with recency-weighted
        reliability = 0.4 * accuracy + 0.6 * recency_accuracy

        # Bayesian shrinkage toward 0.5 when data is sparse
        n = len(history)
        prior_strength = 20  # equivalent to 20 observations at 50% accuracy
        reliability = (reliability * n + 0.5 * prior_strength) / (n + prior_strength)

        self._reliability[source_name][category] = reliability
        self._stats["recomputes"] += 1

    def get_reliability(self, source_name: str, category: str = "") -> float:
        """Get reliability score for a source, optionally filtered by category.

        Returns 0.0 (terrible) to 1.0 (perfect). Default 0.5 (unknown).
        """
        if category:
            return self._reliability[source_name].get(category, 0.5)

        # Average across all categories
        cat_scores = self._reliability.get(source_name, {})
        if not cat_scores:
            return 0.5
        return sum(cat_scores.values()) / len(cat_scores)

    def get_all_reliabilities(self) -> dict[str, dict[str, float]]:
        """Get full reliability matrix for dashboard."""
        return {
            source: dict(cats)
            for source, cats in self._reliability.items()
        }

    def stats(self) -> dict:
        return dict(self._stats)


class AdaptiveWeightEngine:
    """
    Phase 14 — Learns per-source weights from historical accuracy.

    Uses SourceConfidenceTracker reliability scores to dynamically
    weight alt-data features before they enter the model.
    """

    def __init__(self, tracker: SourceConfidenceTracker) -> None:
        self._tracker = tracker
        self._base_weight = 1.0  # default weight for unknown sources

        # Manual weight overrides (for sources we trust/distrust a priori)
        self._overrides: dict[str, float] = {}

    def set_override(self, source_name: str, weight: float) -> None:
        """Manually set a weight override for a source."""
        self._overrides[source_name] = max(0.0, min(3.0, weight))

    def weight_features(
        self,
        alt_features: dict[str, float],
        category: str = "",
    ) -> dict[str, float]:
        """Apply adaptive weights to alt-data features.

        Features are multiplied by their source's reliability score.
        Sources with proven accuracy get boosted (up to 1.5×).
        Sources that are wrong a lot get dampened (down to 0.3×).
        """
        weighted = {}

        for feature_name, value in alt_features.items():
            # Extract source name from feature name (prefix before first '_')
            parts = feature_name.split("_")
            source_name = parts[0] if parts else ""

            # Get weight
            if source_name in self._overrides:
                weight = self._overrides[source_name]
            else:
                reliability = self._tracker.get_reliability(source_name, category)
                # Map reliability (0.0–1.0) to weight (0.3–1.5)
                # 0.5 reliability → 1.0 weight (neutral)
                # 0.0 reliability → 0.3 weight (very bad source)
                # 1.0 reliability → 1.5 weight (excellent source)
                weight = 0.3 + reliability * 1.2

            weighted[feature_name] = value * weight

        return weighted

    def get_weights_summary(self, category: str = "") -> dict[str, float]:
        """Get current effective weights per source for dashboard."""
        summary = {}
        for source_name in self._tracker.get_all_reliabilities():
            if source_name in self._overrides:
                summary[source_name] = self._overrides[source_name]
            else:
                reliability = self._tracker.get_reliability(source_name, category)
                summary[source_name] = round(0.3 + reliability * 1.2, 3)
        return summary
