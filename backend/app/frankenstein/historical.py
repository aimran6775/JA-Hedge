"""
Frankenstein — Historical Data Harvester (Phase 1).

Downloads ALL settled Kalshi markets and their 1-minute candlestick data
into a local SQLite database for pre-training the prediction model.

Capabilities:
  - Paginate all settled markets for target series (KXBTC15M, KXETH15M, etc.)
  - Fetch 1-min OHLC + bid/ask + volume + OI candlestick data per market
  - Store everything in SQLite (data/historical.db)
  - Resume-safe: skips markets already fully fetched
  - Rate-limit aware: configurable delay between API calls
  - Runnable as standalone script OR importable module

Usage (standalone):
    python -m app.frankenstein.historical

Usage (from code):
    from app.frankenstein.historical import HistoricalHarvester
    harvester = HistoricalHarvester()
    await harvester.run()
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.logging_config import get_logger

log = get_logger("frankenstein.historical")

# ── Default target series ─────────────────────────────────────────
# These have the most settled markets and are ideal for pre-training.
DEFAULT_SERIES = [
    "KXBTC15M",   # Bitcoin 15-min (largest, ~9,800 settled)
    "KXETH15M",   # Ethereum 15-min (~9,800 settled)
    "KXBTCD",     # Bitcoin daily
    "KXETHD",     # Ethereum daily
    "KXBTC",      # Bitcoin price levels
    "KXETH",      # Ethereum price levels
    "KXSOL",      # Solana
    "KXNAS100",   # Nasdaq 100 (finance)
    "KXSP500",    # S&P 500 (finance)
]

# Respect PERSIST_DIR env var (set to /data on Railway volume mount)
_PERSIST_DIR = Path(os.environ.get("PERSIST_DIR", 
    str(Path(__file__).resolve().parent.parent.parent / "data")))
DB_PATH = _PERSIST_DIR / "historical.db"


def _init_db(db_path: Path | str) -> sqlite3.Connection:
    """Create the historical database schema."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS markets (
            ticker           TEXT PRIMARY KEY,
            series_ticker    TEXT NOT NULL,
            event_ticker     TEXT,
            title            TEXT,
            result           TEXT,           -- 'yes', 'no', 'void', NULL
            market_type      TEXT DEFAULT 'binary',
            volume           REAL DEFAULT 0,
            open_interest    REAL DEFAULT 0,
            open_time        TEXT,           -- ISO 8601
            close_time       TEXT,           -- ISO 8601
            expiration_time  TEXT,           -- ISO 8601
            floor_strike     REAL,
            cap_strike       REAL,
            last_price       REAL,
            yes_bid          REAL,
            yes_ask          REAL,
            fetched_at       TEXT DEFAULT (datetime('now')),
            candles_fetched  INTEGER DEFAULT 0  -- 1 = candles downloaded
        );

        CREATE TABLE IF NOT EXISTS candles (
            market_ticker    TEXT NOT NULL,
            end_period_ts    INTEGER NOT NULL,
            -- Price OHLC (cents or dollars depending on API era)
            price_open       REAL,
            price_high       REAL,
            price_low        REAL,
            price_close      REAL,
            price_mean       REAL,
            price_previous   REAL,
            -- Yes bid OHLC
            bid_open         REAL,
            bid_high         REAL,
            bid_low          REAL,
            bid_close        REAL,
            -- Yes ask OHLC
            ask_open         REAL,
            ask_high         REAL,
            ask_low          REAL,
            ask_close        REAL,
            -- Volume & OI
            volume           INTEGER DEFAULT 0,
            open_interest    INTEGER DEFAULT 0,
            PRIMARY KEY (market_ticker, end_period_ts)
        );

        CREATE INDEX IF NOT EXISTS idx_markets_series
            ON markets(series_ticker);
        CREATE INDEX IF NOT EXISTS idx_markets_result
            ON markets(result);
        CREATE INDEX IF NOT EXISTS idx_candles_market
            ON candles(market_ticker);
        CREATE INDEX IF NOT EXISTS idx_markets_candles_fetched
            ON markets(candles_fetched);
    """)
    conn.commit()
    return conn


class HistoricalHarvester:
    """
    Async harvester for Kalshi historical data.

    Fetches all settled markets for configured series and downloads
    1-minute candlestick data for each market.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        series: list[str] | None = None,
        api_delay: float = 0.15,        # seconds between API calls
        candle_delay: float = 0.10,      # seconds between candle fetches
        max_markets_per_series: int = 0,  # 0 = unlimited
        skip_candles: bool = False,       # set True to only fetch market metadata
    ):
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.series = series or DEFAULT_SERIES
        self.api_delay = api_delay
        self.candle_delay = candle_delay
        self.max_markets = max_markets_per_series
        self.skip_candles = skip_candles

        self._conn: sqlite3.Connection | None = None
        self._stats: dict[str, Any] = {
            "markets_fetched": 0,
            "markets_skipped": 0,
            "candles_fetched": 0,
            "candle_batches": 0,
            "errors": 0,
            "series_completed": [],
        }

    # ── Public API ────────────────────────────────────────────────────

    async def run(self) -> dict[str, Any]:
        """Run the full harvest: markets + candles for all series."""
        from app.kalshi.api import KalshiAPI

        self._conn = _init_db(self.db_path)
        log.info("historical_harvest_start",
                 series=self.series, db=str(self.db_path))

        try:
            async with KalshiAPI.from_settings() as api:
                for series_ticker in self.series:
                    try:
                        await self._harvest_series(api, series_ticker)
                        self._stats["series_completed"].append(series_ticker)
                    except Exception as e:
                        log.error("series_harvest_failed",
                                  series=series_ticker, error=str(e))
                        self._stats["errors"] += 1

                if not self.skip_candles:
                    await self._harvest_all_candles(api)
        finally:
            if self._conn:
                self._conn.close()

        log.info("historical_harvest_complete", **self._stats)
        return self._stats

    async def run_candles_only(self) -> dict[str, Any]:
        """Only fetch candles for markets that don't have them yet."""
        from app.kalshi.api import KalshiAPI

        self._conn = _init_db(self.db_path)
        log.info("candle_harvest_start", db=str(self.db_path))

        try:
            async with KalshiAPI.from_settings() as api:
                await self._harvest_all_candles(api)
        finally:
            if self._conn:
                self._conn.close()

        log.info("candle_harvest_complete", **self._stats)
        return self._stats

    # ── Internal: Market Fetching ─────────────────────────────────────

    async def _harvest_series(self, api: Any, series_ticker: str) -> None:
        """Fetch all settled markets for a single series."""
        from app.kalshi.models import MarketStatus

        log.info("harvesting_series", series=series_ticker)
        cursor = None
        total = 0
        new = 0

        while True:
            try:
                markets, next_cursor = await api.markets.list_markets(
                    series_ticker=series_ticker,
                    status=MarketStatus.SETTLED,
                    limit=200,
                    cursor=cursor,
                )
            except Exception as e:
                log.error("market_list_error",
                          series=series_ticker, error=str(e))
                self._stats["errors"] += 1
                break

            if not markets:
                break

            for m in markets:
                total += 1
                if self._market_exists(m.ticker):
                    self._stats["markets_skipped"] += 1
                    continue

                self._save_market(m, series_ticker)
                new += 1
                self._stats["markets_fetched"] += 1

            if self.max_markets and total >= self.max_markets:
                break

            if not next_cursor:
                break
            cursor = next_cursor
            await asyncio.sleep(self.api_delay)

        log.info("series_complete",
                 series=series_ticker, total=total, new=new)

    def _market_exists(self, ticker: str) -> bool:
        """Check if a market is already in the database."""
        assert self._conn
        row = self._conn.execute(
            "SELECT 1 FROM markets WHERE ticker = ?", (ticker,)
        ).fetchone()
        return row is not None

    def _save_market(self, m: Any, series_ticker: str) -> None:
        """Insert a market record into the database."""
        assert self._conn

        def _dt(v: Any) -> str | None:
            if v is None:
                return None
            if isinstance(v, datetime):
                return v.isoformat()
            return str(v)

        self._conn.execute("""
            INSERT OR IGNORE INTO markets
                (ticker, series_ticker, event_ticker, title, result,
                 market_type, volume, open_interest,
                 open_time, close_time, expiration_time,
                 floor_strike, cap_strike, last_price,
                 yes_bid, yes_ask)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            m.ticker,
            series_ticker or getattr(m, 'series_ticker', None),
            getattr(m, 'event_ticker', None),
            getattr(m, 'title', None),
            getattr(m, 'result', None),
            getattr(m, 'market_type', 'binary'),
            float(m.volume or 0) if m.volume is not None else 0,
            float(m.open_interest or 0) if m.open_interest is not None else 0,
            _dt(getattr(m, 'open_time', None)),
            _dt(getattr(m, 'close_time', None)),
            _dt(getattr(m, 'expiration_time', None)),
            float(m.floor_strike) if getattr(m, 'floor_strike', None) else None,
            float(m.cap_strike) if getattr(m, 'cap_strike', None) else None,
            float(m.last_price) if getattr(m, 'last_price', None) else None,
            float(m.yes_bid) if getattr(m, 'yes_bid', None) else None,
            float(m.yes_ask) if getattr(m, 'yes_ask', None) else None,
        ))
        self._conn.commit()

    # ── Internal: Candle Fetching ─────────────────────────────────────

    async def _harvest_all_candles(self, api: Any) -> None:
        """Fetch candles for all markets that don't have them yet."""
        assert self._conn

        # If specific series were configured, only fetch candles for those
        if self.series:
            placeholders = ",".join("?" for _ in self.series)
            rows = self._conn.execute(f"""
                SELECT ticker, series_ticker, open_time,
                       COALESCE(close_time, expiration_time) AS end_time
                FROM markets
                WHERE candles_fetched = 0 AND result IS NOT NULL
                  AND series_ticker IN ({placeholders})
                ORDER BY series_ticker, ticker
            """, self.series).fetchall()
        else:
            rows = self._conn.execute("""
                SELECT ticker, series_ticker, open_time,
                       COALESCE(close_time, expiration_time) AS end_time
                FROM markets
                WHERE candles_fetched = 0 AND result IS NOT NULL
                ORDER BY series_ticker, ticker
            """).fetchall()

        log.info("candle_harvest_queued", markets=len(rows))

        for i, (ticker, series_ticker, open_time_str, end_time_str) in enumerate(rows):
            if not series_ticker:
                continue
            try:
                await self._fetch_candles_for_market(
                    api, ticker, series_ticker,
                    open_time_str, end_time_str,
                )
                # Mark as fetched
                self._conn.execute(
                    "UPDATE markets SET candles_fetched = 1 WHERE ticker = ?",
                    (ticker,),
                )
                self._conn.commit()
                self._stats["candle_batches"] += 1

                if (i + 1) % 100 == 0:
                    log.info("candle_progress",
                             done=i + 1, total=len(rows),
                             candles=self._stats["candles_fetched"])
            except Exception as e:
                log.debug("candle_fetch_error",
                          ticker=ticker, error=str(e))
                self._stats["errors"] += 1

            await asyncio.sleep(self.candle_delay)

    async def _fetch_candles_for_market(
        self,
        api: Any,
        ticker: str,
        series_ticker: str,
        open_time_str: str | None,
        end_time_str: str | None,
    ) -> None:
        """Fetch 1-minute candles for a single market.
        
        end_time_str should be close_time (when trading ends), NOT
        expiration_time (which can be days/weeks later for settlement).
        """
        # Determine time range
        if open_time_str:
            try:
                open_dt = datetime.fromisoformat(open_time_str.replace("Z", "+00:00"))
                start_ts = int(open_dt.timestamp())
            except Exception:
                start_ts = 0
        else:
            start_ts = 0

        if end_time_str:
            try:
                end_dt = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
                end_ts = int(end_dt.timestamp())
            except Exception:
                end_ts = int(time.time())
        else:
            end_ts = int(time.time())

        # If no open_time, use end - 1h as approximation for 15M markets
        if start_ts == 0 and end_ts > 0:
            start_ts = end_ts - 3600

        # Fetch candles — the Kalshi API may limit to certain window sizes,
        # so we chunk into 6-hour windows for 1-min candles.
        CHUNK_SECONDS = 6 * 3600  # 6 hours per request
        all_candles = []

        ts = start_ts
        while ts < end_ts:
            chunk_end = min(ts + CHUNK_SECONDS, end_ts)
            try:
                candles = await api.historical.get_candlesticks(
                    series_ticker=series_ticker,
                    market_ticker=ticker,
                    start_ts=ts,
                    end_ts=chunk_end,
                    period_interval=1,  # 1-minute candles
                )
                if candles:
                    all_candles.extend(candles)
            except Exception:
                pass  # Some chunks may have no data

            ts = chunk_end
            if ts < end_ts:
                await asyncio.sleep(self.candle_delay)

        # Persist candles
        if all_candles:
            self._save_candles(ticker, all_candles)
            self._stats["candles_fetched"] += len(all_candles)

    def _save_candles(self, ticker: str, candles: list[Any]) -> None:
        """Batch insert candles into the database."""
        assert self._conn
        rows = []
        for c in candles:
            rows.append((
                ticker,
                c.end_period_ts or 0,
                float(c.price.open) if c.price and c.price.open is not None else None,
                float(c.price.high) if c.price and c.price.high is not None else None,
                float(c.price.low) if c.price and c.price.low is not None else None,
                float(c.price.close) if c.price and c.price.close is not None else None,
                float(c.price.mean) if c.price and getattr(c.price, 'mean', None) is not None else None,
                float(c.price.previous) if c.price and getattr(c.price, 'previous', None) is not None else None,
                float(c.yes_bid.open) if c.yes_bid and c.yes_bid.open is not None else None,
                float(c.yes_bid.high) if c.yes_bid and c.yes_bid.high is not None else None,
                float(c.yes_bid.low) if c.yes_bid and c.yes_bid.low is not None else None,
                float(c.yes_bid.close) if c.yes_bid and c.yes_bid.close is not None else None,
                float(c.yes_ask.open) if c.yes_ask and c.yes_ask.open is not None else None,
                float(c.yes_ask.high) if c.yes_ask and c.yes_ask.high is not None else None,
                float(c.yes_ask.low) if c.yes_ask and c.yes_ask.low is not None else None,
                float(c.yes_ask.close) if c.yes_ask and c.yes_ask.close is not None else None,
                int(c.volume or 0),
                int(c.open_interest or 0),
            ))

        self._conn.executemany("""
            INSERT OR IGNORE INTO candles
                (market_ticker, end_period_ts,
                 price_open, price_high, price_low, price_close,
                 price_mean, price_previous,
                 bid_open, bid_high, bid_low, bid_close,
                 ask_open, ask_high, ask_low, ask_close,
                 volume, open_interest)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        self._conn.commit()

    # ── Query Helpers (used by feature engineering) ───────────────────

    @staticmethod
    def get_db(db_path: str | Path | None = None) -> sqlite3.Connection:
        """Open the historical database for reading."""
        path = Path(db_path) if db_path else DB_PATH
        if not path.exists():
            raise FileNotFoundError(f"Historical database not found: {path}")
        conn = sqlite3.connect(str(path), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def count_markets(db_path: str | Path | None = None) -> dict[str, int]:
        """Count markets by series and result status."""
        conn = HistoricalHarvester.get_db(db_path)
        try:
            rows = conn.execute("""
                SELECT series_ticker,
                       COUNT(*) as total,
                       SUM(CASE WHEN result = 'yes' THEN 1 ELSE 0 END) as yes_count,
                       SUM(CASE WHEN result = 'no' THEN 1 ELSE 0 END) as no_count,
                       SUM(CASE WHEN candles_fetched = 1 THEN 1 ELSE 0 END) as with_candles
                FROM markets
                WHERE result IS NOT NULL
                GROUP BY series_ticker
                ORDER BY total DESC
            """).fetchall()
            return {
                row["series_ticker"]: {
                    "total": row["total"],
                    "yes": row["yes_count"],
                    "no": row["no_count"],
                    "with_candles": row["with_candles"],
                }
                for row in rows
            }
        finally:
            conn.close()

    @staticmethod
    def get_markets_with_candles(
        db_path: str | Path | None = None,
        series: list[str] | None = None,
        min_candles: int = 10,
    ) -> list[dict[str, Any]]:
        """Get all markets that have candle data, optionally filtered by series."""
        conn = HistoricalHarvester.get_db(db_path)
        try:
            query = """
                SELECT m.ticker, m.series_ticker, m.result,
                       m.volume, m.open_time, m.expiration_time,
                       m.floor_strike, m.cap_strike,
                       COUNT(c.end_period_ts) as candle_count
                FROM markets m
                JOIN candles c ON c.market_ticker = m.ticker
                WHERE m.result IN ('yes', 'no')
                  AND m.candles_fetched = 1
            """
            params: list[Any] = []
            if series:
                placeholders = ",".join("?" * len(series))
                query += f" AND m.series_ticker IN ({placeholders})"
                params.extend(series)
            query += f"""
                GROUP BY m.ticker
                HAVING candle_count >= ?
                ORDER BY m.expiration_time
            """
            params.append(min_candles)

            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    @staticmethod
    def get_candles_for_market(
        ticker: str,
        db_path: str | Path | None = None,
    ) -> list[dict[str, Any]]:
        """Get all candles for a specific market, ordered by time."""
        conn = HistoricalHarvester.get_db(db_path)
        try:
            rows = conn.execute("""
                SELECT * FROM candles
                WHERE market_ticker = ?
                ORDER BY end_period_ts ASC
            """, (ticker,)).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()


# ── Standalone execution ──────────────────────────────────────────────

async def _main() -> None:
    """Run the historical harvester from command line."""
    import argparse

    parser = argparse.ArgumentParser(description="Frankenstein Historical Data Harvester")
    parser.add_argument("--series", nargs="+", default=None,
                        help="Series tickers to harvest (default: all)")
    parser.add_argument("--db", default=None,
                        help="Database path (default: data/historical.db)")
    parser.add_argument("--candles-only", action="store_true",
                        help="Only fetch candles for existing markets")
    parser.add_argument("--markets-only", action="store_true",
                        help="Only fetch market metadata, no candles")
    parser.add_argument("--delay", type=float, default=0.15,
                        help="Delay between API calls in seconds")
    parser.add_argument("--max-per-series", type=int, default=0,
                        help="Max markets per series (0=unlimited)")
    parser.add_argument("--stats", action="store_true",
                        help="Print database statistics and exit")
    args = parser.parse_args()

    if args.stats:
        try:
            counts = HistoricalHarvester.count_markets(args.db)
            total = sum(v["total"] for v in counts.values())
            with_candles = sum(v["with_candles"] for v in counts.values())
            print(f"\n{'Series':<15} {'Total':>8} {'Yes':>8} {'No':>8} {'Candles':>8}")
            print("-" * 55)
            for series, data in counts.items():
                print(f"{series:<15} {data['total']:>8} {data['yes']:>8} {data['no']:>8} {data['with_candles']:>8}")
            print("-" * 55)
            print(f"{'TOTAL':<15} {total:>8} {'':>8} {'':>8} {with_candles:>8}")
        except FileNotFoundError:
            print("No historical database found. Run harvester first.")
        return

    harvester = HistoricalHarvester(
        db_path=args.db,
        series=args.series,
        api_delay=args.delay,
        max_markets_per_series=args.max_per_series,
        skip_candles=args.markets_only,
    )

    if args.candles_only:
        stats = await harvester.run_candles_only()
    else:
        stats = await harvester.run()

    print(f"\n✅ Harvest complete!")
    print(f"   Markets fetched: {stats['markets_fetched']}")
    print(f"   Markets skipped: {stats['markets_skipped']}")
    print(f"   Candles fetched: {stats['candles_fetched']}")
    print(f"   Errors: {stats['errors']}")
    print(f"   Series: {', '.join(stats['series_completed'])}")


if __name__ == "__main__":
    asyncio.run(_main())
