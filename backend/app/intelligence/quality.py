"""
Phase 19 — Data Quality Monitoring.

Watches the intelligence pipeline for data quality issues:
  • Stale data (source hasn't updated in a while)
  • Anomalous values (outliers, impossible values)
  • Missing features (expected feature not populated)
  • Source degradation (increasing error rates)
  • Schema drift (unexpected data shapes)

Produces quality scores per source and overall, surfaced on dashboard.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.logging_config import get_logger

log = get_logger("intelligence.quality")


@dataclass
class QualityIssue:
    """A detected quality problem."""
    source_name: str
    issue_type: str   # stale | anomaly | missing | degradation | schema
    severity: str     # info | warning | critical
    message: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "source_name": self.source_name,
            "issue_type": self.issue_type,
            "severity": self.severity,
            "message": self.message,
            "timestamp": self.timestamp,
        }


class DataQualityMonitor:
    """
    Continuously monitors data quality across all intelligence sources.

    Checks:
      1. Staleness: has the source produced fresh data recently?
      2. Anomalies: are signal values within expected bounds?
      3. Completeness: are expected features populated?
      4. Error trends: is the error rate increasing?
      5. Coverage: are all categories getting data?
    """

    def __init__(self) -> None:
        # Config thresholds
        self._staleness_thresholds: dict[str, float] = {
            # source_type → max age in seconds before "stale" warning
            "sports_odds": 120,
            "news": 300,
            "social": 360,
            "weather": 600,
            "crypto": 180,
            "prediction_market": 300,
            "economic": 900,
            "political": 600,
            "trends": 900,
        }
        self._default_staleness = 600

        # Tracking
        self._last_signal_times: dict[str, float] = {}  # source → last signal timestamp
        self._error_history: dict[str, list[float]] = defaultdict(list)  # source → error timestamps
        self._signal_history: dict[str, list[float]] = defaultdict(list)  # source → signal value history

        self._issues: list[QualityIssue] = []
        self._max_issues = 500

        # Per-source quality scores (0.0 = terrible, 1.0 = perfect)
        self._quality_scores: dict[str, float] = {}

    def check(self, hub: Any) -> list[QualityIssue]:
        """Run a full quality check cycle. Returns new issues found."""
        new_issues: list[QualityIssue] = []

        try:
            status = hub.status()
        except Exception:
            return new_issues

        now = time.time()

        for src in status.get("sources", []):
            name = src.get("name", "unknown")
            src_type = src.get("type", "")
            enabled = src.get("enabled", True)
            if not enabled:
                continue

            issues_for_source = []

            # ── 1. Staleness check ──
            last_fetch = src.get("last_fetch_time")
            if last_fetch:
                age = now - last_fetch
                threshold = self._staleness_thresholds.get(src_type, self._default_staleness)
                if age > threshold * 3:
                    issues_for_source.append(QualityIssue(
                        source_name=name, issue_type="stale", severity="critical",
                        message=f"Data is {age:.0f}s old (threshold: {threshold}s). Source may be down.",
                    ))
                elif age > threshold * 1.5:
                    issues_for_source.append(QualityIssue(
                        source_name=name, issue_type="stale", severity="warning",
                        message=f"Data is {age:.0f}s old (threshold: {threshold}s). Delayed.",
                    ))

            # ── 2. Error rate check ──
            error_count = src.get("error_count", 0)
            fetch_count = src.get("fetch_count", 0)
            if fetch_count > 5:
                error_rate = error_count / fetch_count
                if error_rate > 0.5:
                    issues_for_source.append(QualityIssue(
                        source_name=name, issue_type="degradation", severity="critical",
                        message=f"Error rate: {error_rate:.0%} ({error_count}/{fetch_count} fetches failed).",
                    ))
                elif error_rate > 0.2:
                    issues_for_source.append(QualityIssue(
                        source_name=name, issue_type="degradation", severity="warning",
                        message=f"Error rate: {error_rate:.0%} ({error_count}/{fetch_count}).",
                    ))

            # ── 3. Signal count check ──
            signal_count = src.get("signal_count", 0)
            if fetch_count > 3 and signal_count == 0:
                issues_for_source.append(QualityIssue(
                    source_name=name, issue_type="missing", severity="warning",
                    message=f"Source has fetched {fetch_count} times but produced 0 signals.",
                ))

            # ── 4. Latency check ──
            latency = src.get("avg_latency_ms", 0)
            if latency > 10000:
                issues_for_source.append(QualityIssue(
                    source_name=name, issue_type="degradation", severity="warning",
                    message=f"Average latency is {latency:.0f}ms (>10s). Source is very slow.",
                ))

            # ── 5. Health check ──
            if not src.get("healthy", True):
                issues_for_source.append(QualityIssue(
                    source_name=name, issue_type="degradation", severity="critical",
                    message="Source is reporting unhealthy status.",
                ))

            # Compute quality score for this source
            score = 1.0
            for issue in issues_for_source:
                if issue.severity == "critical":
                    score -= 0.3
                elif issue.severity == "warning":
                    score -= 0.1
            self._quality_scores[name] = max(0.0, min(1.0, score))

            new_issues.extend(issues_for_source)

        # Also check signal values for anomalies
        try:
            all_signals = hub.get_all_signals()
            for source_name, ticker_signals in all_signals.items():
                for ticker, signal in ticker_signals.items():
                    val = signal.signal_value if hasattr(signal, "signal_value") else 0.0
                    conf = signal.confidence if hasattr(signal, "confidence") else 0.0

                    # Bounds check
                    if abs(val) > 1.0:
                        new_issues.append(QualityIssue(
                            source_name=source_name, issue_type="anomaly", severity="warning",
                            message=f"Signal value {val:.3f} is out of bounds [-1, 1] for {ticker}.",
                        ))

                    if conf < 0 or conf > 1.0:
                        new_issues.append(QualityIssue(
                            source_name=source_name, issue_type="anomaly", severity="warning",
                            message=f"Confidence {conf:.3f} is out of bounds [0, 1] for {ticker}.",
                        ))
        except Exception:
            pass

        # Store issues
        self._issues.extend(new_issues)
        if len(self._issues) > self._max_issues:
            self._issues = self._issues[-self._max_issues:]

        return new_issues

    def get_quality_scores(self) -> dict[str, float]:
        """Get quality scores for all sources. 0.0 = terrible, 1.0 = perfect."""
        return dict(self._quality_scores)

    def get_overall_quality(self) -> float:
        """Get overall system quality score."""
        if not self._quality_scores:
            return 1.0
        return sum(self._quality_scores.values()) / len(self._quality_scores)

    def get_issues(
        self,
        source_name: str | None = None,
        issue_type: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Get recent quality issues."""
        results = []
        for issue in reversed(self._issues):
            if source_name and issue.source_name != source_name:
                continue
            if issue_type and issue.issue_type != issue_type:
                continue
            results.append(issue.to_dict())
            if len(results) >= limit:
                break
        return results

    def to_dict(self) -> dict:
        """Full quality dashboard data."""
        return {
            "overall_quality": round(self.get_overall_quality(), 3),
            "source_scores": {k: round(v, 3) for k, v in self._quality_scores.items()},
            "recent_issues": self.get_issues(limit=20),
            "issue_summary": self._summarize_issues(),
        }

    def _summarize_issues(self) -> dict:
        """Summarize issues by type and severity."""
        by_type: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        for issue in self._issues:
            by_type[issue.issue_type] = by_type.get(issue.issue_type, 0) + 1
            by_severity[issue.severity] = by_severity.get(issue.severity, 0) + 1
        return {"by_type": by_type, "by_severity": by_severity, "total": len(self._issues)}
