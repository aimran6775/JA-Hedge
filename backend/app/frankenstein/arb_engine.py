"""
Frankenstein — Cross-Platform Arbitrage Engine. 🧟💰

Phase 31: Direct arbitrage detection between external sources and Kalshi.

When Polymarket says 73% and Kalshi says 65%, that's an 8% edge that
should be traded IMMEDIATELY — no ML model needed. This module bypasses
XGBoost entirely for high-confidence arb signals.

Sources:
- Polymarket (prediction market, most liquid)
- Vegas odds (sports)
- FRED economic data (rate/CPI markets)
- Crypto spot prices (Bitcoin/Ethereum price targets)

Architecture:
    IntelligenceHub → ArbScanner.scan() → ArbSignal[]
    ArbSignal → scanner.py (injected as override prediction)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.logging_config import get_logger

log = get_logger("frankenstein.arb_engine")


@dataclass
class ArbSignal:
    """A detected arbitrage opportunity."""
    ticker: str
    source: str           # "polymarket", "vegas", "crypto", "economic"
    external_prob: float  # probability from external source
    kalshi_prob: float    # current Kalshi midpoint
    edge: float           # external_prob - kalshi_prob (signed)
    side: str             # "yes" or "no"
    confidence: float     # 0.0-1.0, how much we trust the external source
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    @property
    def abs_edge(self) -> float:
        return abs(self.edge)


class ArbScanner:
    """
    Scans for cross-platform arbitrage opportunities.

    Called each scan cycle by MarketScanner. Returns a list of ArbSignals
    that override ML predictions when the edge is large and the source
    is reliable.
    """

    # Minimum edge thresholds per source (lower = more trusted)
    MIN_EDGE = {
        "polymarket": 0.06,    # 6% edge — Polymarket is liquid and efficient
        "vegas": 0.05,         # 5% — Vegas lines are gold standard for sports
        "crypto": 0.08,        # 8% — crypto prices are noisy
        "economic": 0.07,      # 7% — FRED data is lagged
    }

    # Confidence weights per source
    SOURCE_CONFIDENCE = {
        "polymarket": 0.85,
        "vegas": 0.90,
        "crypto": 0.75,
        "economic": 0.70,
    }

    # Maximum age of external signal before it's considered stale
    MAX_SIGNAL_AGE_SECONDS = 300  # 5 minutes

    def __init__(self) -> None:
        self._stats = {
            "scans": 0,
            "signals_found": 0,
            "trades_triggered": 0,
            "by_source": {},
        }
        self._last_signals: dict[str, ArbSignal] = {}

    def scan(
        self,
        candidates: list[Any],  # list[Market]
        features_list: list[Any],  # list[MarketFeatures]
    ) -> dict[str, ArbSignal]:
        """
        Scan all candidates for arb opportunities.

        Returns dict of ticker → ArbSignal for markets where external
        source disagrees with Kalshi by more than the threshold.
        """
        self._stats["scans"] += 1
        signals: dict[str, ArbSignal] = {}

        try:
            from app.state import state as _st
            hub = _st.intelligence_hub
            if not hub or not hub._running:
                return signals

            from app.intelligence.ticker_mapper import TickerMapper
            mapper = getattr(self, "_mapper", None)
            if mapper is None:
                mapper = TickerMapper()
                self._mapper = mapper

            now = time.time()

            for market, feat in zip(candidates, features_list):
                try:
                    kalshi_mid = feat.midpoint
                    if kalshi_mid <= 0.02 or kalshi_mid >= 0.98:
                        continue  # Already near-certain, no arb

                    mapping = mapper.map(
                        market.ticker,
                        title=getattr(market, "title", "") or "",
                        category_hint=getattr(market, "category", "") or "",
                    )

                    best_signal: ArbSignal | None = None

                    for key in mapping.intelligence_keys:
                        for sig in hub.get_signals_for_ticker(key):
                            # Check freshness
                            sig_age = now - getattr(sig, "timestamp", 0)
                            if sig_age > self.MAX_SIGNAL_AGE_SECONDS:
                                continue

                            ext_prob = self._extract_probability(
                                sig, mapping.underlying or "",
                                getattr(mapping, "strike_price", None),
                            )
                            if ext_prob is None or ext_prob <= 0.01 or ext_prob >= 0.99:
                                continue

                            source_type = sig.source_type.value
                            min_edge = self.MIN_EDGE.get(source_type, 0.10)
                            source_conf = self.SOURCE_CONFIDENCE.get(source_type, 0.50)

                            # Edge: how much external disagrees with Kalshi
                            edge = ext_prob - kalshi_mid

                            if abs(edge) < min_edge:
                                continue

                            # Determine side
                            side = "yes" if edge > 0 else "no"

                            arb = ArbSignal(
                                ticker=market.ticker,
                                source=source_type,
                                external_prob=ext_prob,
                                kalshi_prob=kalshi_mid,
                                edge=edge,
                                side=side,
                                confidence=source_conf,
                                details={
                                    "intel_key": key,
                                    "signal_age_s": round(sig_age, 1),
                                    "mapping_category": mapping.category,
                                },
                            )

                            # Keep the strongest signal per ticker
                            if best_signal is None or arb.abs_edge > best_signal.abs_edge:
                                best_signal = arb

                    if best_signal:
                        signals[market.ticker] = best_signal
                        self._stats["signals_found"] += 1
                        src = best_signal.source
                        self._stats["by_source"][src] = self._stats["by_source"].get(src, 0) + 1

                except Exception:
                    continue

        except Exception as e:
            log.debug("arb_scan_error", error=str(e))

        self._last_signals = signals
        return signals

    def _extract_probability(
        self, sig: Any, underlying: str, strike_price: float | None,
    ) -> float | None:
        """Extract probability from an intelligence signal."""
        sf = sig.features
        source_type = sig.source_type.value

        if source_type == "prediction_market":
            # Polymarket
            poly_prob = sf.get("poly_price", sig.signal_value)
            if 0.01 < poly_prob < 0.99:
                return poly_prob

        elif source_type == "sports_odds":
            # Vegas — use home/away prob
            home_prob = sf.get("home_prob", 0)
            away_prob = sf.get("away_prob", 0)
            if home_prob > 0.01:
                return home_prob  # Simplification: use home prob
            if away_prob > 0.01:
                return away_prob

        elif source_type == "crypto":
            # Crypto price relative to strike
            crypto_price = sf.get("crypto_price", 0)
            if crypto_price > 0 and strike_price:
                dist = (crypto_price - strike_price) / strike_price
                # Convert distance to probability using sigmoid-like mapping
                import math
                prob = 1.0 / (1.0 + math.exp(-dist * 10))
                return max(0.02, min(0.98, prob))

        elif source_type == "economic":
            # Economic data — check if underlying value vs strike
            series_val = sf.get(f"{underlying}_value", 0) if underlying else 0
            if series_val and strike_price:
                dist = (series_val - strike_price) / max(0.01, abs(strike_price))
                import math
                prob = 1.0 / (1.0 + math.exp(-dist * 5))
                return max(0.02, min(0.98, prob))

        return None

    def on_trade_executed(self, ticker: str) -> None:
        """Track that an arb signal was acted on."""
        if ticker in self._last_signals:
            self._stats["trades_triggered"] += 1

    def status(self) -> dict[str, Any]:
        return {
            **self._stats,
            "active_signals": len(self._last_signals),
            "top_signals": [
                {
                    "ticker": s.ticker,
                    "source": s.source,
                    "edge": f"{s.edge:+.1%}",
                    "side": s.side,
                    "external_prob": round(s.external_prob, 3),
                    "kalshi_prob": round(s.kalshi_prob, 3),
                }
                for s in sorted(self._last_signals.values(),
                                key=lambda x: x.abs_edge, reverse=True)[:5]
            ],
        }


# Singleton
arb_scanner = ArbScanner()
