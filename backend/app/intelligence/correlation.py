"""
Phase 17 — Source Correlation Matrix.

Analyzes how intelligence sources correlate with each other:
  • Which sources move together?
  • Which sources are independent (high diversification value)?
  • Which source pairs provide the most joint predictive power?

This is valuable for:
  1. Avoiding double-counting correlated signals
  2. Finding the minimal set of sources that covers all information
  3. Detecting source redundancy
  4. Weighting independent sources more heavily
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from app.logging_config import get_logger

log = get_logger("intelligence.correlation")


@dataclass
class CorrelationPair:
    source_a: str
    source_b: str
    correlation: float  # -1 to +1
    sample_count: int
    category: str = ""


class SourceCorrelationMatrix:
    """
    Computes pairwise correlations between intelligence sources.

    Uses signal history to calculate Pearson correlation coefficients
    between each pair of sources, both globally and per-category.
    """

    def __init__(self, min_samples: int = 20) -> None:
        self._min_samples = min_samples

        # Rolling signal values: source_name → list[(timestamp, signal_value, category)]
        self._history: dict[str, list[tuple[float, float, str]]] = defaultdict(list)
        self._max_history = 2000

        # Cached correlations
        self._correlations: dict[tuple[str, str], float] = {}
        self._category_correlations: dict[str, dict[tuple[str, str], float]] = {}
        self._last_compute = 0.0

    def record_signals(self, all_signals: dict[str, dict[str, Any]]) -> None:
        """Record current signal values from the hub for correlation analysis.

        all_signals: source_name → ticker → signal object
        """
        now = time.time()

        for source_name, ticker_signals in all_signals.items():
            for ticker, signal in ticker_signals.items():
                val = signal.signal_value if hasattr(signal, "signal_value") else 0.0
                cat = signal.category if hasattr(signal, "category") else ""
                self._history[source_name].append((now, val, cat))

                # Trim
                if len(self._history[source_name]) > self._max_history:
                    self._history[source_name] = self._history[source_name][-self._max_history:]

    def compute(self) -> None:
        """Recompute all pairwise correlations."""
        sources = list(self._history.keys())
        if len(sources) < 2:
            return

        self._correlations.clear()
        self._category_correlations.clear()

        for i, src_a in enumerate(sources):
            for src_b in sources[i + 1:]:
                # Global correlation
                corr = self._pearson(src_a, src_b)
                if corr is not None:
                    self._correlations[(src_a, src_b)] = corr

                # Per-category correlations
                categories = set()
                for _, _, cat in self._history[src_a]:
                    if cat:
                        categories.add(cat)
                for _, _, cat in self._history[src_b]:
                    if cat:
                        categories.add(cat)

                for cat in categories:
                    corr_cat = self._pearson(src_a, src_b, category=cat)
                    if corr_cat is not None:
                        if cat not in self._category_correlations:
                            self._category_correlations[cat] = {}
                        self._category_correlations[cat][(src_a, src_b)] = corr_cat

        self._last_compute = time.time()
        log.info("correlation_matrix_computed", pairs=len(self._correlations), sources=len(sources))

    def _pearson(self, src_a: str, src_b: str, category: str = "") -> float | None:
        """Compute Pearson correlation between two sources."""
        hist_a = self._history.get(src_a, [])
        hist_b = self._history.get(src_b, [])

        if not hist_a or not hist_b:
            return None

        # Filter by category if specified
        if category:
            hist_a = [(t, v, c) for t, v, c in hist_a if c == category]
            hist_b = [(t, v, c) for t, v, c in hist_b if c == category]

        # Align by nearest timestamps (within 120s window)
        vals_a = []
        vals_b = []

        b_times = [(t, v) for t, v, _ in hist_b]
        for t_a, v_a, _ in hist_a:
            # Find nearest B within window
            best_b = None
            best_delta = 120.0
            for t_b, v_b in b_times:
                delta = abs(t_a - t_b)
                if delta < best_delta:
                    best_delta = delta
                    best_b = v_b

            if best_b is not None:
                vals_a.append(v_a)
                vals_b.append(best_b)

        if len(vals_a) < self._min_samples:
            return None

        # Pearson correlation
        n = len(vals_a)
        mean_a = sum(vals_a) / n
        mean_b = sum(vals_b) / n

        cov = sum((a - mean_a) * (b - mean_b) for a, b in zip(vals_a, vals_b)) / n
        std_a = math.sqrt(sum((a - mean_a) ** 2 for a in vals_a) / n)
        std_b = math.sqrt(sum((b - mean_b) ** 2 for b in vals_b) / n)

        if std_a < 1e-10 or std_b < 1e-10:
            return 0.0

        return cov / (std_a * std_b)

    def get_matrix(self) -> dict[str, dict[str, float]]:
        """Get the full correlation matrix as a nested dict for dashboard."""
        sources = sorted(set(
            s for pair in self._correlations for s in pair
        ))

        matrix: dict[str, dict[str, float]] = {}
        for src in sources:
            matrix[src] = {}
            for other in sources:
                if src == other:
                    matrix[src][other] = 1.0
                else:
                    key = (min(src, other), max(src, other))
                    matrix[src][other] = round(self._correlations.get(key, 0.0), 3)

        return matrix

    def get_independent_sources(self, threshold: float = 0.3) -> list[str]:
        """Find sources with low correlation to others (high diversification value)."""
        sources = set(s for pair in self._correlations for s in pair)
        avg_corr: dict[str, float] = {}

        for src in sources:
            corrs = []
            for pair, val in self._correlations.items():
                if src in pair:
                    corrs.append(abs(val))
            avg_corr[src] = sum(corrs) / len(corrs) if corrs else 0.0

        return [src for src, avg in sorted(avg_corr.items(), key=lambda x: x[1])
                if avg < threshold]

    def get_redundant_pairs(self, threshold: float = 0.8) -> list[CorrelationPair]:
        """Find pairs of sources that are highly correlated (potentially redundant)."""
        pairs = []
        for (src_a, src_b), corr in self._correlations.items():
            if abs(corr) >= threshold:
                # Count samples
                count = min(len(self._history.get(src_a, [])), len(self._history.get(src_b, [])))
                pairs.append(CorrelationPair(
                    source_a=src_a, source_b=src_b,
                    correlation=round(corr, 3), sample_count=count,
                ))
        return sorted(pairs, key=lambda p: abs(p.correlation), reverse=True)

    def to_dict(self) -> dict:
        """Full status for dashboard."""
        return {
            "matrix": self.get_matrix(),
            "independent_sources": self.get_independent_sources(),
            "redundant_pairs": [
                {"a": p.source_a, "b": p.source_b, "correlation": p.correlation, "samples": p.sample_count}
                for p in self.get_redundant_pairs()
            ],
            "last_compute": self._last_compute,
            "source_count": len(self._history),
            "total_observations": sum(len(v) for v in self._history.values()),
        }
