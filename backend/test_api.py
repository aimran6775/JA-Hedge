"""Test Kalshi API authentication for reads and writes."""
import asyncio

async def test():
    from app.kalshi.api import KalshiAPI
    from app.config import get_settings

    s = get_settings()
    api = KalshiAPI.from_settings(s)
    async with api:
        # Test read — balance
        b = await api.portfolio.get_balance()
        print(f"Balance: {b.balance} cents")

        # Test read — exchange status
        st = await api.exchange.get_status()
        print(f"Exchange active: {st.exchange_active}")

        # Test read — markets
        markets, _ = await api.markets.list_markets(limit=3)
        print(f"Markets: {len(markets)} loaded")
        for m in markets:
            print(f"  {m.ticker}: {m.title}")

        # Test write — order placement
        if markets:
            try:
                from app.kalshi.models import OrderSide, OrderAction, OrderType
                result = await api.portfolio.create_order(
                    ticker=markets[0].ticker,
                    side=OrderSide.YES,
                    action=OrderAction.BUY,
                    count=1,
                    type=OrderType.LIMIT,
                    yes_price=1,
                )
                print(f"Order placed: {result}")
            except Exception as e:
                print(f"Order error: {e}")
                print("  (This is expected if demo account has $0 balance)")

asyncio.run(test())
