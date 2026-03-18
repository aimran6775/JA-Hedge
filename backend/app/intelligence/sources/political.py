"""
Phase 11 — Congressional & Political Data.

Free political data sources:
  • Congress.gov API (free, no key) — bills, votes, floor actions
  • ProPublica Congress API (free tier) — member data, votes
  • White House briefing room RSS (free)
  • Federal Register API (free) — executive orders, rules

Direct signals for Kalshi political markets (legislation, appointments,
executive orders, government shutdown, etc.).
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from app.intelligence.base import DataSource, DataSourceType, SourceHealth, SourceSignal
from app.logging_config import get_logger

log = get_logger("intelligence.political")

CONGRESS_API = "https://api.congress.gov/v3"
FED_REGISTER_API = "https://www.federalregister.gov/api/v1"
WH_RSS = "https://www.whitehouse.gov/feed/"


class PoliticalDataFeed(DataSource):
    """
    Congressional and political data for Kalshi political markets.
    """

    def __init__(
        self,
        congress_api_key: str = "",
        propublica_key: str = "",
        poll_interval: float = 300.0,
        enabled: bool = True,
    ) -> None:
        self._congress_key = congress_api_key
        self._propublica_key = propublica_key
        self._poll_interval = poll_interval
        self._enabled = enabled
        self._client: httpx.AsyncClient | None = None

        self._bills_cache: list[dict] = []
        self._votes_cache: list[dict] = []
        self._executive_orders: list[dict] = []
        self._stats = {
            "fetches": 0, "errors": 0, "bills_tracked": 0,
            "votes_tracked": 0, "eo_tracked": 0, "total_signals": 0,
        }

    @property
    def name(self) -> str:
        return "political_congress"

    @property
    def source_type(self) -> DataSourceType:
        return DataSourceType.POLITICAL

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
        log.info("political_feed_started", has_congress_key=bool(self._congress_key))

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch_signals(self, tickers: list[str] | None = None) -> list[SourceSignal]:
        if not self._client:
            return []

        signals: list[SourceSignal] = []

        # Fetch recent bills
        try:
            bill_signals = await self._fetch_recent_bills()
            signals.extend(bill_signals)
        except Exception as e:
            self._stats["errors"] += 1
            log.debug("bills_error", error=str(e))

        # Fetch executive orders from Federal Register
        try:
            eo_signals = await self._fetch_executive_orders()
            signals.extend(eo_signals)
        except Exception as e:
            self._stats["errors"] += 1
            log.debug("eo_error", error=str(e))

        # Fetch White House briefing room
        try:
            wh_signals = await self._fetch_whitehouse_rss()
            signals.extend(wh_signals)
        except Exception as e:
            self._stats["errors"] += 1
            log.debug("wh_error", error=str(e))

        self._stats["total_signals"] += len(signals)
        return signals

    async def _fetch_recent_bills(self) -> list[SourceSignal]:
        """Fetch recently active bills from Congress.gov."""
        if not self._client:
            return []

        signals: list[SourceSignal] = []

        try:
            url = f"{CONGRESS_API}/bill"
            params: dict[str, str] = {
                "limit": "20",
                "sort": "updateDate+desc",
                "format": "json",
            }
            if self._congress_key:
                params["api_key"] = self._congress_key

            resp = await self._client.get(url, params=params)
            self._stats["fetches"] += 1

            if resp.status_code != 200:
                self._stats["errors"] += 1
                return []

            data = resp.json()
            bills = data.get("bills", [])

            self._bills_cache = []
            for bill in bills[:20]:
                title = bill.get("title", "")
                bill_type = bill.get("type", "")
                number = bill.get("number", "")
                action = bill.get("latestAction", {}).get("text", "")
                action_date = bill.get("latestAction", {}).get("actionDate", "")

                if not title:
                    continue

                self._bills_cache.append({
                    "title": title,
                    "type": bill_type,
                    "number": number,
                    "action": action,
                    "action_date": action_date,
                })
                self._stats["bills_tracked"] += 1

                # Generate signal based on bill progression
                progress = self._bill_progress_score(action)

                signals.append(SourceSignal(
                    source_name=self.name,
                    source_type=self.source_type,
                    ticker=f"political:bill:{bill_type}{number}",
                    signal_value=progress,
                    confidence=0.70,
                    category="politics",
                    headline=f"{bill_type}.{number}: {title[:150]}",
                    features={
                        "bill_progress": progress,
                        "bill_type": hash(bill_type) % 10,
                    },
                    raw_data={
                        "title": title,
                        "type": bill_type,
                        "number": number,
                        "action": action,
                    },
                ))

        except Exception as e:
            self._stats["errors"] += 1
            log.debug("congress_api_error", error=str(e))

        return signals

    async def _fetch_executive_orders(self) -> list[SourceSignal]:
        """Fetch recent executive orders from Federal Register."""
        if not self._client:
            return []

        signals: list[SourceSignal] = []

        try:
            url = f"{FED_REGISTER_API}/documents.json"
            params = {
                "conditions[presidential_document_type]": "executive_order",
                "conditions[type][]": "PRESDOCU",
                "per_page": "10",
                "order": "newest",
            }
            resp = await self._client.get(url, params=params)
            self._stats["fetches"] += 1

            if resp.status_code != 200:
                return []

            data = resp.json()
            results = data.get("results", [])

            self._executive_orders = []
            for eo in results:
                title = eo.get("title", "")
                eo_number = eo.get("executive_order_number", "")
                pub_date = eo.get("publication_date", "")
                abstract = eo.get("abstract", "") or ""

                self._executive_orders.append({
                    "title": title,
                    "number": eo_number,
                    "date": pub_date,
                    "abstract": abstract[:300],
                })
                self._stats["eo_tracked"] += 1

                signals.append(SourceSignal(
                    source_name=self.name,
                    source_type=self.source_type,
                    ticker=f"political:eo:{eo_number or pub_date}",
                    signal_value=0.5,  # EOs are always notable
                    confidence=0.85,
                    category="politics",
                    headline=f"Executive Order: {title[:150]}",
                    features={
                        "is_executive_order": 1.0,
                    },
                    raw_data={"title": title, "number": eo_number},
                ))

        except Exception as e:
            log.debug("fed_register_error", error=str(e))

        return signals

    async def _fetch_whitehouse_rss(self) -> list[SourceSignal]:
        """Fetch White House briefing room RSS."""
        if not self._client:
            return []

        signals: list[SourceSignal] = []

        try:
            resp = await self._client.get(WH_RSS)
            self._stats["fetches"] += 1

            if resp.status_code != 200:
                return []

            root = ET.fromstring(resp.text)
            items = root.findall(".//item")

            for item in items[:10]:
                title_el = item.find("title")
                title = (title_el.text or "").strip() if title_el is not None else ""
                if not title:
                    continue

                from app.intelligence.sources.news_sentiment import NewsSentimentEngine
                sentiment = NewsSentimentEngine._score_sentiment(title)

                signals.append(SourceSignal(
                    source_name=self.name,
                    source_type=self.source_type,
                    ticker="political:whitehouse",
                    signal_value=sentiment,
                    confidence=0.75,
                    category="politics",
                    headline=title[:200],
                    features={
                        "wh_sentiment": round(sentiment, 4),
                        "is_whitehouse": 1.0,
                    },
                ))

        except Exception as e:
            log.debug("whitehouse_rss_error", error=str(e))

        return signals

    @staticmethod
    def _bill_progress_score(action_text: str) -> float:
        """Score how far a bill has progressed (0.0 = introduced, 1.0 = signed)."""
        action = action_text.lower()
        if "signed by president" in action or "became public law" in action:
            return 1.0
        if "passed" in action and "senate" in action and "house" in action:
            return 0.9
        if "passed" in action:
            return 0.7
        if "reported" in action or "committee" in action:
            return 0.4
        if "referred" in action:
            return 0.2
        if "introduced" in action:
            return 0.1
        return 0.15  # default — some action taken

    def get_activity(self) -> dict:
        """Get recent political activity for dashboard."""
        return {
            "recent_bills": self._bills_cache[:10],
            "executive_orders": self._executive_orders[:5],
            "stats": dict(self._stats),
        }

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
