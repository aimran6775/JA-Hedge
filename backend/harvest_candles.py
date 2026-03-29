#!/usr/bin/env python3
"""
Focused candle harvester — uses raw aiohttp for speed (no rate limiter overhead).
Hits production Kalshi API directly for public candlestick data.

Usage: python harvest_candles.py
"""
import asyncio
import aiohttp
import sqlite3
import sys
import os
import time
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).parent / "data" / "historical.db"
BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
DELAY_BETWEEN_REQUESTS = 0.20   # 5 req/sec — safe for production
CONCURRENT_LIMIT = 3             # parallel requests
PROGRESS_INTERVAL = 100          # log every N markets


async def fetch_candles(session: aiohttp.ClientSession, sem: asyncio.Semaphore,
                        series_ticker: str, ticker: str,
                        start_ts: int, end_ts: int) -> list[dict]:
    """Fetch 1-min candles for a single market."""
    url = f"{BASE_URL}/series/{series_ticker}/markets/{ticker}/candlesticks"
    params = {"period_interval": 1, "start_ts": start_ts, "end_ts": end_ts}
    
    async with sem:
        for attempt in range(3):
            try:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 429:
                        retry_after = float(resp.headers.get("Retry-After", "2"))
                        await asyncio.sleep(retry_after)
                        continue
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    return data.get("candlesticks", [])
            except Exception:
                await asyncio.sleep(1)
        return []


async def main():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    # Get markets needing candles (15M series only)
    rows = conn.execute("""
        SELECT ticker, series_ticker, open_time,
               COALESCE(close_time, expiration_time) AS end_time
        FROM markets
        WHERE candles_fetched = 0 AND result IS NOT NULL
          AND series_ticker IN ('KXBTC15M', 'KXETH15M')
        ORDER BY series_ticker, ticker
    """).fetchall()

    total = len(rows)
    print(f"[{time.strftime('%H:%M:%S')}] Candle harvest: {total} markets to fetch")
    print(f"  Rate: {1/DELAY_BETWEEN_REQUESTS:.0f} req/sec, concurrency: {CONCURRENT_LIMIT}")

    sem = asyncio.Semaphore(CONCURRENT_LIMIT)
    done = 0
    total_candles = 0
    start_time = time.time()

    async with aiohttp.ClientSession() as session:
        for ticker, series_ticker, open_time_str, end_time_str in rows:
            # Parse time range — use close_time (actual market end), NOT expiration_time
            try:
                if open_time_str:
                    ot = datetime.fromisoformat(open_time_str.replace("Z", "+00:00"))
                    start_ts = int(ot.timestamp())
                else:
                    start_ts = 0
                if end_time_str:
                    et = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
                    end_ts = int(et.timestamp()) + 60  # +1 min buffer
                else:
                    continue

                if start_ts == 0:
                    start_ts = end_ts - 3600  # 1h fallback for 15M markets
            except Exception:
                done += 1
                continue

            candles = await fetch_candles(session, sem, series_ticker, ticker, start_ts, end_ts)

            if candles:
                # Insert candles — map raw JSON keys to DB schema
                for c in candles:
                    price = c.get("price") or {}
                    yes_bid = c.get("yes_bid") or {}
                    yes_ask = c.get("yes_ask") or {}

                    def _f(d, key):
                        """Extract float from dict, trying _dollars suffix first."""
                        v = d.get(f"{key}_dollars") or d.get(key)
                        if v is None:
                            return None
                        try:
                            return float(v)
                        except (ValueError, TypeError):
                            return None

                    conn.execute("""
                        INSERT OR IGNORE INTO candles
                            (market_ticker, end_period_ts,
                             price_open, price_high, price_low, price_close,
                             price_mean, price_previous,
                             bid_open, bid_high, bid_low, bid_close,
                             ask_open, ask_high, ask_low, ask_close,
                             volume, open_interest)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        ticker,
                        c.get("end_period_ts", 0),
                        _f(price, "open"),
                        _f(price, "high"),
                        _f(price, "low"),
                        _f(price, "close"),
                        _f(price, "mean"),
                        _f(price, "previous"),
                        _f(yes_bid, "open"),
                        _f(yes_bid, "high"),
                        _f(yes_bid, "low"),
                        _f(yes_bid, "close"),
                        _f(yes_ask, "open"),
                        _f(yes_ask, "high"),
                        _f(yes_ask, "low"),
                        _f(yes_ask, "close"),
                        int(float(c.get("volume_fp") or c.get("volume") or 0)),
                        int(float(c.get("open_interest_fp") or c.get("open_interest") or 0)),
                    ))
                total_candles += len(candles)

            # Mark as fetched regardless (some markets may have no candle data)
            conn.execute("UPDATE markets SET candles_fetched = 1 WHERE ticker = ?", (ticker,))

            done += 1
            if done % 50 == 0:
                conn.commit()

            if done % PROGRESS_INTERVAL == 0:
                elapsed = time.time() - start_time
                rate = done / elapsed
                eta = (total - done) / rate / 60 if rate > 0 else 0
                print(f"  [{time.strftime('%H:%M:%S')}] {done:,}/{total:,} markets "
                      f"({done/total*100:.1f}%) | {total_candles:,} candles | "
                      f"{rate:.1f} mkt/s | ETA: {eta:.0f} min")

            await asyncio.sleep(DELAY_BETWEEN_REQUESTS)

    conn.commit()
    conn.close()

    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"CANDLE HARVEST COMPLETE")
    print(f"{'='*60}")
    print(f"  Markets processed: {done:,}")
    print(f"  Total candles: {total_candles:,}")
    print(f"  Elapsed: {elapsed/60:.1f} min")
    print(f"  Rate: {done/elapsed:.1f} markets/sec")


if __name__ == "__main__":
    asyncio.run(main())
