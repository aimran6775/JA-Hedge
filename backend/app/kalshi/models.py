"""
JA Hedge — Kalshi API Pydantic Models.

Typed models matching the Kalshi OpenAPI v3.8.0 schema.
Uses FixedPoint types (Decimal) for precision.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────────────


class MarketStatus(str, Enum):
    INITIALIZED = "initialized"
    INACTIVE = "inactive"
    ACTIVE = "active"
    CLOSED = "closed"
    DETERMINED = "determined"
    DISPUTED = "disputed"
    AMENDED = "amended"
    FINALIZED = "finalized"


class MarketType(str, Enum):
    BINARY = "binary"
    SCALAR = "scalar"


class OrderSide(str, Enum):
    YES = "yes"
    NO = "no"


class OrderAction(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    LIMIT = "limit"
    MARKET = "market"


class OrderStatus(str, Enum):
    RESTING = "resting"
    CANCELED = "canceled"
    EXECUTED = "executed"
    PENDING = "pending"


class TimeInForce(str, Enum):
    GTC = "good_till_canceled"
    FOK = "fill_or_kill"
    IOC = "immediate_or_cancel"


class SelfTradePrevention(str, Enum):
    TAKER_AT_CROSS = "taker_at_cross"
    MAKER = "maker"


class MarketResult(str, Enum):
    YES = "yes"
    NO = "no"
    SCALAR = "scalar"
    VOID = "void"


class StrikeType(str, Enum):
    GREATER = "greater"
    LESS = "less"
    BETWEEN = "between"
    FUNCTIONAL = "functional"
    CUSTOM = "custom"
    STRUCTURED = "structured"


# ── Shared / Helper Models ────────────────────────────────────────────────────


class PriceRange(BaseModel):
    start: Decimal
    end: Decimal
    step: Decimal


class CandlestickOHLC(BaseModel):
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    close: Decimal | None = None


class CandlestickPriceOHLC(CandlestickOHLC):
    mean: Decimal | None = None
    previous: Decimal | None = None


# ── Market Models ─────────────────────────────────────────────────────────────


class Market(BaseModel):
    """A single Kalshi market (binary or scalar contract)."""

    ticker: str
    event_ticker: str
    series_ticker: str | None = None
    market_type: MarketType = MarketType.BINARY
    status: MarketStatus = MarketStatus.ACTIVE

    # Prices (FixedPointDollars)
    yes_bid: Decimal | None = Field(None, alias="yes_bid_dollars")
    yes_ask: Decimal | None = Field(None, alias="yes_ask_dollars")
    no_bid: Decimal | None = Field(None, alias="no_bid_dollars")
    no_ask: Decimal | None = Field(None, alias="no_ask_dollars")
    last_price: Decimal | None = Field(None, alias="last_price_dollars")

    # Legacy cent-based (still present in some responses)
    yes_bid_cents: int | None = Field(None, alias="yes_bid")
    yes_ask_cents: int | None = Field(None, alias="yes_ask")
    no_bid_cents: int | None = Field(None, alias="no_bid")
    no_ask_cents: int | None = Field(None, alias="no_ask")
    last_price_cents: int | None = Field(None, alias="last_price")

    # Volume
    volume: Decimal | None = Field(None, alias="volume_fp")
    volume_int: int | None = Field(None, alias="volume")
    open_interest: Decimal | None = Field(None, alias="open_interest_fp")

    # Strike info
    strike_type: StrikeType | None = None
    floor_strike: Decimal | None = None
    cap_strike: Decimal | None = None

    # Rules
    rules_primary: str | None = None
    rules_secondary: str | None = None

    # Metadata
    title: str | None = None
    subtitle: str | None = None
    category: str | None = None
    can_close_early: bool = False
    fractional_trading_enabled: bool = False
    price_ranges: list[PriceRange] = Field(default_factory=list)

    # Timestamps
    open_time: datetime | None = None
    close_time: datetime | None = None
    expiration_time: datetime | None = None

    model_config = {"populate_by_name": True}

    @property
    def midpoint(self) -> Decimal | None:
        """Calculate bid-ask midpoint for YES side."""
        if self.yes_bid is not None and self.yes_ask is not None:
            return (self.yes_bid + self.yes_ask) / 2
        return self.last_price

    @property
    def spread(self) -> Decimal | None:
        """Bid-ask spread in dollars."""
        if self.yes_bid is not None and self.yes_ask is not None:
            return self.yes_ask - self.yes_bid
        return None


class Event(BaseModel):
    """A Kalshi event (collection of markets)."""

    event_ticker: str
    series_ticker: str | None = None
    title: str | None = None
    subtitle: str | None = None
    category: str | None = None
    markets: list[Market] = Field(default_factory=list)
    mutually_exclusive: bool = False

    model_config = {"populate_by_name": True}


class Series(BaseModel):
    """A Kalshi series (template for recurring events)."""

    series_ticker: str
    title: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


# ── Order Models ──────────────────────────────────────────────────────────────


class CreateOrderRequest(BaseModel):
    """Request body for creating an order on Kalshi."""

    ticker: str
    side: OrderSide
    action: OrderAction
    type: OrderType = OrderType.LIMIT
    count: int | None = None
    count_fp: str | None = None  # FixedPointCount as string
    yes_price: int | None = None  # Legacy cents
    no_price: int | None = None  # Legacy cents
    yes_price_dollars: str | None = None  # FixedPointDollars
    no_price_dollars: str | None = None  # FixedPointDollars
    client_order_id: str | None = None  # UUID
    expiration_ts: int | None = None
    time_in_force: TimeInForce = TimeInForce.GTC
    buy_max_cost: int | None = None  # Safety: max cost in cents
    buy_max_cost_dollars: str | None = None  # FixedPointDollars
    self_trade_prevention_type: SelfTradePrevention = SelfTradePrevention.MAKER
    order_group_id: str | None = None
    cancel_order_on_pause: bool = False
    subaccount: int | None = None

    model_config = {"populate_by_name": True}


class Order(BaseModel):
    """An order on Kalshi (response model)."""

    order_id: str
    client_order_id: str | None = None
    ticker: str
    side: OrderSide
    action: OrderAction
    type: OrderType
    status: OrderStatus

    # Prices
    yes_price: int | None = None  # cents
    no_price: int | None = None  # cents
    yes_price_dollars: str | None = None
    no_price_dollars: str | None = None

    # Counts
    count: int | None = None
    count_fp: str | None = None
    initial_count: int | None = None
    initial_count_fp: str | None = None
    remaining_count: int | None = None
    remaining_count_fp: str | None = None
    fill_count: int | None = None
    fill_count_fp: str | None = None

    # Fees & costs
    taker_fees: int | None = None
    taker_fees_dollars: str | None = None
    maker_fees: int | None = None
    maker_fees_dollars: str | None = None
    taker_fill_cost: int | None = None
    taker_fill_cost_dollars: str | None = None
    maker_fill_cost: int | None = None
    maker_fill_cost_dollars: str | None = None

    # Metadata
    order_group_id: str | None = None
    subaccount_number: int | None = None
    time_in_force: TimeInForce | None = None
    self_trade_prevention_type: SelfTradePrevention | None = None

    # Timestamps
    created_time: datetime | None = None
    updated_time: datetime | None = None
    expiration_time: datetime | None = None

    model_config = {"populate_by_name": True}


# ── Fill Models ───────────────────────────────────────────────────────────────


class Fill(BaseModel):
    """A trade fill on Kalshi."""

    fill_id: str | None = None
    order_id: str
    client_order_id: str | None = None
    ticker: str
    side: OrderSide
    action: OrderAction
    count: int | None = None
    count_fp: str | None = None
    yes_price: int | None = None
    no_price: int | None = None
    yes_price_dollars: str | None = None
    no_price_dollars: str | None = None
    is_taker: bool | None = None
    fee_cost: int | None = None
    fee_cost_dollars: str | None = None
    created_time: datetime | None = None

    model_config = {"populate_by_name": True}


# ── Position Models ───────────────────────────────────────────────────────────


class MarketPosition(BaseModel):
    """Position in a single market."""

    ticker: str
    position: int | None = None  # Legacy: positive=YES, negative=NO
    position_fp: str | None = None  # FixedPointCount
    market_exposure: int | None = None
    market_exposure_dollars: str | None = None
    realized_pnl: int | None = None
    realized_pnl_dollars: str | None = None
    fees_paid: int | None = None
    fees_paid_dollars: str | None = None

    model_config = {"populate_by_name": True}


class EventPosition(BaseModel):
    """Aggregate position across an event."""

    event_ticker: str
    total_cost: int | None = None
    total_cost_dollars: str | None = None
    event_exposure: int | None = None
    event_exposure_dollars: str | None = None
    realized_pnl: int | None = None
    realized_pnl_dollars: str | None = None

    model_config = {"populate_by_name": True}


# ── Portfolio Models ──────────────────────────────────────────────────────────


class Balance(BaseModel):
    """Account balance."""

    balance: int | None = None  # cents
    balance_dollars: str | None = None  # FixedPointDollars
    payout: int | None = None
    payout_dollars: str | None = None
    bonus_balance: int | None = None
    bonus_balance_dollars: str | None = None

    model_config = {"populate_by_name": True}


class Settlement(BaseModel):
    """Market settlement record."""

    ticker: str
    event_ticker: str | None = None
    market_result: MarketResult | None = None
    yes_count: int | None = None
    yes_count_fp: str | None = None
    no_count: int | None = None
    no_count_fp: str | None = None
    revenue: int | None = None
    revenue_dollars: str | None = None
    fee_cost: int | None = None
    fee_cost_dollars: str | None = None
    settled_time: datetime | None = None

    model_config = {"populate_by_name": True}


# ── Orderbook Models ─────────────────────────────────────────────────────────


class OrderbookLevel(BaseModel):
    """Single level in the orderbook."""

    price: int | None = None  # cents
    price_dollars: str | None = None
    count: int | None = None
    count_fp: str | None = None


class Orderbook(BaseModel):
    """Full orderbook for a market."""

    ticker: str
    yes_bids: list[OrderbookLevel] = Field(default_factory=list)
    no_bids: list[OrderbookLevel] = Field(default_factory=list)

    # New format
    yes_bids_dollars: list[list[str]] = Field(default_factory=list)
    no_bids_dollars: list[list[str]] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


# ── Candlestick Models ───────────────────────────────────────────────────────


class Candlestick(BaseModel):
    """Single candlestick data point."""

    end_period_ts: int | None = None
    yes_bid: CandlestickOHLC = Field(default_factory=CandlestickOHLC)
    yes_ask: CandlestickOHLC = Field(default_factory=CandlestickOHLC)
    price: CandlestickPriceOHLC = Field(default_factory=CandlestickPriceOHLC)
    volume: int | None = None
    volume_fp: str | None = None
    open_interest: int | None = None
    open_interest_fp: str | None = None

    model_config = {"populate_by_name": True}


# ── Exchange Models ───────────────────────────────────────────────────────────


class ExchangeStatus(BaseModel):
    """Kalshi exchange status."""

    exchange_active: bool = False
    trading_active: bool = False

    model_config = {"populate_by_name": True}


class ExchangeSchedule(BaseModel):
    """Exchange schedule entry."""

    day_of_week: str | None = None
    open_time: str | None = None
    close_time: str | None = None
    maintenance_windows: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


# ── Paginated Response Wrapper ────────────────────────────────────────────────


class PaginatedResponse(BaseModel):
    """Generic paginated response from Kalshi."""

    cursor: str | None = None
    limit: int | None = None

    model_config = {"populate_by_name": True}
