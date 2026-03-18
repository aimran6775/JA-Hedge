"""
Phase 8 — FRED Economic Data Feed.

Federal Reserve Economic Data (FRED) — completely free, no API key:
  • Interest rates (Fed Funds, 10Y Treasury)
  • Inflation (CPI, PCE)
  • Employment (unemployment rate, initial claims, NFP)
  • GDP, consumer sentiment, housing starts, etc.

Direct signals for Kalshi economics markets (Fed rate decisions,
jobs numbers, inflation prints, recession probability).
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.intelligence.base import DataSource, DataSourceType, SourceHealth, SourceSignal
from app.logging_config import get_logger

log = get_logger("intelligence.economic")

# FRED API (free, key is optional for basic access)
FRED_BASE = "https://api.stlouisfed.org/fred"

# Key economic series we track
FRED_SERIES = {
    "FEDFUNDS": {"name": "Fed Funds Rate", "category": "rates", "unit": "%"},
    "DGS10": {"name": "10-Year Treasury", "category": "rates", "unit": "%"},
    "DGS2": {"name": "2-Year Treasury", "category": "rates", "unit": "%"},
    "T10Y2Y": {"name": "10Y-2Y Spread", "category": "rates", "unit": "%"},
    "CPIAUCSL": {"name": "CPI (All Urban)", "category": "inflation", "unit": "index"},
    "PCEPILFE": {"name": "Core PCE", "category": "inflation", "unit": "index"},
    "UNRATE": {"name": "Unemployment Rate", "category": "employment", "unit": "%"},
    "ICSA": {"name": "Initial Claims", "category": "employment", "unit": "thousands"},
    "PAYEMS": {"name": "Nonfarm Payrolls", "category": "employment", "unit": "thousands"},
    "GDP": {"name": "Real GDP", "category": "growth", "unit": "billions"},
    "UMCSENT": {"name": "Consumer Sentiment", "category": "sentiment", "unit": "index"},
    "VIXCLS": {"name": "VIX", "category": "volatility", "unit": "index"},
    "DTWEXBGS": {"name": "USD Index (Broad)", "category": "fx", "unit": "index"},
    "MORTGAGE30US": {"name": "30Y Mortgage Rate", "category": "housing", "unit": "%"},
    "HOUST": {"name": "Housing Starts", "category": "housing", "unit": "thousands"},
}

# Alternative: Treasury direct data (no key at all)
TREASURY_URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"


class EconomicDataFeed(DataSource):
    """
    FRED economic data for Kalshi economics/macro markets.
    """

    def __init__(
        self,
        fred_api_key: str = "",
        poll_interval: float = 600.0,  # Every 10 minutes
        enabled: bool = True,
    ) -> None:
        self._fred_key = fred_api_key
        self._poll_interval = poll_interval
        self._enabled = enabled
        self._client: httpx.AsyncClient | None = None

        self._data_cache: dict[str, dict[str, Any]] = {}
        self._history: dict[str, list[tuple[float, float]]] = {}  # series → [(time, value)]
        self._stats = {
            "fetches": 0, "errors": 0, "series_updated": 0, "total_signals": 0,
        }

    @property
    def name(self) -> str:
        return "economic_fred"

    @property
    def source_type(self) -> DataSourceType:
        return DataSourceType.ECONOMIC

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def poll_interval_seconds(self) -> float:
        return self._poll_interval

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
            headers={"Accept": "application/json"},
            follow_redirects=True,
        )
        log.info("economic_feed_started", has_fred_key=bool(self._fred_key))

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch_signals(self, tickers: list[str] | None = None) -> list[SourceSignal]:
        if not self._client:
            return []

        signals: list[SourceSignal] = []

        # Fetch FRED series
        for series_id, info in FRED_SERIES.items():
            try:
                value, prev_value = await self._fetch_fred_series(series_id)
                if value is not None:
                    sig = self._econ_to_signal(series_id, info, value, prev_value)
                    if sig:
                        signals.append(sig)
                        self._stats["series_updated"] += 1
            except Exception as e:
                self._stats["errors"] += 1
                log.debug("fred_series_error", series=series_id, error=str(e))

        # Fetch Treasury debt data (completely free, no key)
        try:
            treasury_sig = await self._fetch_treasury_data()
            if treasury_sig:
                signals.append(treasury_sig)
        except Exception as e:
            log.debug("treasury_error", error=str(e))

        self._stats["total_signals"] += len(signals)
        return signals

    async def _fetch_fred_series(self, series_id: str) -> tuple[float | None, float | None]:
        """Fetch latest value for a FRED series."""
        if not self._client:
            return None, None

        # If we have a FRED key, use official API
        if self._fred_key:
            url = f"{FRED_BASE}/series/observations"
            params = {
                "series_id": series_id,
                "api_key": self._fred_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": "5",
            }
            resp = await self._client.get(url, params=params)
            self._stats["fetches"] += 1

            if resp.status_code != 200:
                self._stats["errors"] += 1
                return None, None

            data = resp.json()
            observations = data.get("observations", [])
            values = []
            for obs in observations:
                val = obs.get("value", ".")
                if val != ".":
                    try:
                        values.append(float(val))
                    except ValueError:
                        pass

            if values:
                current = values[0]
                previous = values[1] if len(values) > 1 else None
                self._data_cache[series_id] = {
                    "value": current,
                    "previous": previous,
                    "timestamp": time.time(),
                }
                return current, previous
        else:
            # No key — try the public FRED website API (limited but works)
            url = f"https://fred.stlouisfed.org/graph/fredgraph.csv"
            params = {"id": series_id}
            try:
                resp = await self._client.get(url, params=params)
                self._stats["fetches"] += 1
                if resp.status_code == 200:
                    lines = resp.text.strip().split("\n")
                    if len(lines) > 1:
                        # CSV: DATE, VALUE
                        values = []
                        for line in lines[-5:]:
                            parts = line.split(",")
                            if len(parts) >= 2 and parts[1].strip() != ".":
                                try:
                                    values.append(float(parts[1].strip()))
                                except ValueError:
                                    pass
                        if values:
                            current = values[-1]
                            previous = values[-2] if len(values) > 1 else None
                            self._data_cache[series_id] = {
                                "value": current,
                                "previous": previous,
                                "timestamp": time.time(),
                            }
                            return current, previous
            except Exception:
                pass

        return None, None

    def _econ_to_signal(
        self,
        series_id: str,
        info: dict,
        value: float,
        prev_value: float | None,
    ) -> SourceSignal | None:
        """Convert economic data point to a signal."""
        change = 0.0
        change_pct = 0.0
        if prev_value is not None and prev_value != 0:
            change = value - prev_value
            change_pct = change / abs(prev_value) * 100

        # Direction signal: positive change = positive signal
        # For things like unemployment and VIX, invert (higher = negative)
        inverted = series_id in {"UNRATE", "ICSA", "VIXCLS"}
        signal_value = -change_pct / 5.0 if inverted else change_pct / 5.0
        signal_value = max(-1.0, min(1.0, signal_value))

        category_map = {
            "rates": "economics",
            "inflation": "economics",
            "employment": "economics",
            "growth": "economics",
            "sentiment": "economics",
            "volatility": "economics",
            "fx": "economics",
            "housing": "economics",
        }

        return SourceSignal(
            source_name=self.name,
            source_type=self.source_type,
            ticker=f"econ:{series_id}",
            signal_value=signal_value,
            confidence=0.90,  # Official government data
            edge_estimate=signal_value * 0.02,
            category=category_map.get(info["category"], "economics"),
            headline=f"{info['name']}: {value:.2f}{info['unit']} ({change_pct:+.2f}%)",
            features={
                f"econ_{series_id.lower()}_value": round(value, 4),
                f"econ_{series_id.lower()}_change": round(change, 4),
                f"econ_{series_id.lower()}_change_pct": round(change_pct, 4),
            },
            raw_data={
                "series_id": series_id,
                "name": info["name"],
                "value": value,
                "previous": prev_value,
                "unit": info["unit"],
            },
        )

    async def _fetch_treasury_data(self) -> SourceSignal | None:
        """Fetch US Treasury debt data (completely free)."""
        if not self._client:
            return None

        url = f"{TREASURY_URL}/v2/accounting/od/debt_to_penny"
        params = {
            "sort": "-record_date",
            "page[size]": "2",
            "format": "json",
        }

        try:
            resp = await self._client.get(url, params=params)
            if resp.status_code != 200:
                return None

            data = resp.json()
            records = data.get("data", [])
            if not records:
                return None

            latest = records[0]
            debt_total = float(latest.get("tot_pub_debt_out_amt", 0))
            debt_trillions = debt_total / 1e12

            return SourceSignal(
                source_name=self.name,
                source_type=self.source_type,
                ticker="econ:national_debt",
                signal_value=0.0,  # Neutral — debt is context, not directional
                confidence=0.95,
                category="economics",
                headline=f"US National Debt: ${debt_trillions:.2f}T",
                features={
                    "econ_national_debt_trillions": round(debt_trillions, 4),
                },
                raw_data=latest,
            )
        except Exception:
            return None

    def get_data(self) -> dict[str, dict]:
        """Get current economic data cache for dashboard."""
        return dict(self._data_cache)

    def health(self) -> SourceHealth:
        return SourceHealth(
            name=self.name,
            source_type=self.source_type,
            enabled=self._enabled,
            healthy=self._stats["errors"] < self._stats["fetches"] + 1,
            total_fetches=self._stats["fetches"],
            total_errors=self._stats["errors"],
            total_signals=self._stats["total_signals"],
        )
