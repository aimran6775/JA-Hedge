"""
JA Hedge — Database Models.

TimescaleDB-optimized schema for:
- Markets & Events (market data cache)
- Orders & Fills (execution history)
- Positions (portfolio state)
- Price snapshots (time-series for AI features)
- AI predictions & signals
- Trading strategy configs
- Risk events & alerts

Design principles:
- Hypertables for time-series data (price_snapshots, fills)
- JSONB for flexible metadata
- Indexes on hot query paths
- Decimal precision for financial data
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum as SAEnum,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.engine import Base


# ── Markets ───────────────────────────────────────────────────────────────────


class MarketRecord(Base):
    """Cached Kalshi market data — refreshed by the data pipeline."""

    __tablename__ = "markets"

    ticker: Mapped[str] = mapped_column(String(100), primary_key=True)
    event_ticker: Mapped[str] = mapped_column(String(100), index=True)
    series_ticker: Mapped[str | None] = mapped_column(String(100), index=True)
    title: Mapped[str | None] = mapped_column(Text)
    subtitle: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(100), index=True)
    market_type: Mapped[str] = mapped_column(String(20), default="binary")
    status: Mapped[str] = mapped_column(String(20), index=True, default="active")

    # Current prices
    yes_bid: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    yes_ask: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    no_bid: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    no_ask: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    last_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    open_interest: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))

    # Metadata
    open_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expiration_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rules_primary: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Housekeeping
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    price_snapshots: Mapped[list["PriceSnapshot"]] = relationship(
        back_populates="market", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_markets_status_category", "status", "category"),
        Index("ix_markets_event_status", "event_ticker", "status"),
    )


class EventRecord(Base):
    """Cached Kalshi event data."""

    __tablename__ = "events"

    event_ticker: Mapped[str] = mapped_column(String(100), primary_key=True)
    series_ticker: Mapped[str | None] = mapped_column(String(100), index=True)
    title: Mapped[str | None] = mapped_column(Text)
    subtitle: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(100))
    mutually_exclusive: Mapped[bool] = mapped_column(Boolean, default=False)
    extra: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ── Price Snapshots (TimescaleDB Hypertable) ──────────────────────────────────


class PriceSnapshot(Base):
    """
    Time-series price snapshots for AI feature engineering.

    This table should be converted to a TimescaleDB hypertable:
        SELECT create_hypertable('price_snapshots', 'ts');
    """

    __tablename__ = "price_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(100), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    yes_bid: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    yes_ask: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    last_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    open_interest: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))

    # Computed at snapshot time
    spread: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    midpoint: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    # Relationship
    market: Mapped[MarketRecord | None] = relationship(
        back_populates="price_snapshots",
        foreign_keys=[ticker],
        primaryjoin="PriceSnapshot.ticker == MarketRecord.ticker",
    )

    __table_args__ = (
        Index("ix_price_snap_ticker_ts", "ticker", "ts"),
    )


# ── Orders ────────────────────────────────────────────────────────────────────


class OrderRecord(Base):
    """Local copy of every order submitted through JA Hedge."""

    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    client_order_id: Mapped[str | None] = mapped_column(String(100), unique=True, index=True)
    ticker: Mapped[str] = mapped_column(String(100), index=True)
    event_ticker: Mapped[str | None] = mapped_column(String(100), index=True)
    side: Mapped[str] = mapped_column(String(10))  # yes / no
    action: Mapped[str] = mapped_column(String(10))  # buy / sell
    order_type: Mapped[str] = mapped_column(String(20))  # limit / market
    status: Mapped[str] = mapped_column(String(20), index=True)

    # Pricing
    yes_price_cents: Mapped[int | None] = mapped_column(Integer)
    no_price_cents: Mapped[int | None] = mapped_column(Integer)
    yes_price_dollars: Mapped[str | None] = mapped_column(String(20))
    no_price_dollars: Mapped[str | None] = mapped_column(String(20))

    # Counts
    count: Mapped[int | None] = mapped_column(Integer)
    remaining_count: Mapped[int | None] = mapped_column(Integer)
    fill_count: Mapped[int | None] = mapped_column(Integer)

    # Costs & Fees
    taker_fees_dollars: Mapped[str | None] = mapped_column(String(20))
    maker_fees_dollars: Mapped[str | None] = mapped_column(String(20))
    taker_fill_cost_dollars: Mapped[str | None] = mapped_column(String(20))
    maker_fill_cost_dollars: Mapped[str | None] = mapped_column(String(20))

    # Strategy linkage
    strategy_id: Mapped[str | None] = mapped_column(String(100), index=True)
    signal_id: Mapped[int | None] = mapped_column(BigInteger, index=True)

    # Metadata
    extra: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    fills: Mapped[list["FillRecord"]] = relationship(back_populates="order")

    __table_args__ = (
        Index("ix_orders_ticker_status", "ticker", "status"),
        Index("ix_orders_strategy_created", "strategy_id", "created_at"),
    )


# ── Fills ─────────────────────────────────────────────────────────────────────


class FillRecord(Base):
    """Trade fill records — one fill per partial/full execution."""

    __tablename__ = "fills"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fill_id: Mapped[str | None] = mapped_column(String(100), unique=True, index=True)
    order_id: Mapped[str] = mapped_column(String(100), index=True)
    ticker: Mapped[str] = mapped_column(String(100), index=True)
    side: Mapped[str] = mapped_column(String(10))
    action: Mapped[str] = mapped_column(String(10))
    count: Mapped[int | None] = mapped_column(Integer)
    yes_price_cents: Mapped[int | None] = mapped_column(Integer)
    no_price_cents: Mapped[int | None] = mapped_column(Integer)
    yes_price_dollars: Mapped[str | None] = mapped_column(String(20))
    no_price_dollars: Mapped[str | None] = mapped_column(String(20))
    is_taker: Mapped[bool | None] = mapped_column(Boolean)
    fee_cost_dollars: Mapped[str | None] = mapped_column(String(20))

    filled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationship
    order: Mapped[OrderRecord | None] = relationship(
        back_populates="fills",
        foreign_keys=[order_id],
        primaryjoin="FillRecord.order_id == OrderRecord.order_id",
    )

    __table_args__ = (
        Index("ix_fills_ticker_filled", "ticker", "filled_at"),
    )


# ── Positions ─────────────────────────────────────────────────────────────────


class PositionRecord(Base):
    """Computed position state per market — updated on every fill."""

    __tablename__ = "positions"

    ticker: Mapped[str] = mapped_column(String(100), primary_key=True)
    event_ticker: Mapped[str | None] = mapped_column(String(100), index=True)

    # Net position
    yes_count: Mapped[int] = mapped_column(Integer, default=0)
    no_count: Mapped[int] = mapped_column(Integer, default=0)
    net_contracts: Mapped[int] = mapped_column(Integer, default=0)  # yes - no
    avg_entry_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    # P&L
    total_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0)
    total_fees: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0)

    # Market exposure
    market_exposure: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ── AI Signals ────────────────────────────────────────────────────────────────


class AISignal(Base):
    """
    AI-generated trading signal.

    Every prediction the model makes gets logged here, along with
    confidence, features used, and eventual outcome for retraining.
    """

    __tablename__ = "ai_signals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(100), index=True)
    strategy_id: Mapped[str] = mapped_column(String(100), index=True)
    model_name: Mapped[str] = mapped_column(String(100))
    model_version: Mapped[str | None] = mapped_column(String(50))

    # Prediction
    predicted_side: Mapped[str] = mapped_column(String(10))  # yes / no
    confidence: Mapped[Decimal] = mapped_column(Numeric(8, 6))  # 0.0 - 1.0
    predicted_edge: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))  # expected edge
    kelly_fraction: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))

    # Position sizing
    recommended_count: Mapped[int | None] = mapped_column(Integer)
    recommended_price_cents: Mapped[int | None] = mapped_column(Integer)

    # Features snapshot
    features: Mapped[dict | None] = mapped_column(JSONB)

    # Outcome (filled in after settlement)
    actual_result: Mapped[str | None] = mapped_column(String(10))  # yes / no / void
    actual_pnl: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    was_correct: Mapped[bool | None] = mapped_column(Boolean)

    # Execution linkage
    order_id: Mapped[str | None] = mapped_column(String(100), index=True)
    was_executed: Mapped[bool] = mapped_column(Boolean, default=False)
    execution_reason: Mapped[str | None] = mapped_column(String(200))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_signals_ticker_created", "ticker", "created_at"),
        Index("ix_signals_strategy_created", "strategy_id", "created_at"),
    )


# ── Strategy Configs ──────────────────────────────────────────────────────────


class StrategyConfig(Base):
    """
    User-defined trading strategy configuration.

    Stores all the knobs the user sets in the dashboard:
    stop-loss, take-profit, kelly fraction, model selection, filters, etc.
    """

    __tablename__ = "strategy_configs"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    # Trading parameters
    model_name: Mapped[str] = mapped_column(String(100), default="xgboost_v1")
    min_confidence: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=Decimal("0.60"))
    min_edge: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=Decimal("0.05"))
    kelly_fraction: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=Decimal("0.25"))

    # Risk limits
    max_position_size: Mapped[int] = mapped_column(Integer, default=10)
    max_daily_loss: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("50.0"))
    stop_loss_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))  # e.g., 0.20 = 20%
    take_profit_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))

    # Filters
    allowed_categories: Mapped[list | None] = mapped_column(JSONB)  # ["politics", "crypto"]
    ticker_whitelist: Mapped[list | None] = mapped_column(JSONB)
    ticker_blacklist: Mapped[list | None] = mapped_column(JSONB)
    min_volume: Mapped[int | None] = mapped_column(Integer)
    min_open_interest: Mapped[int | None] = mapped_column(Integer)
    max_spread_cents: Mapped[int | None] = mapped_column(Integer)

    # Time constraints
    min_time_to_expiry_hours: Mapped[int | None] = mapped_column(Integer)
    max_time_to_expiry_hours: Mapped[int | None] = mapped_column(Integer)
    trading_start_hour: Mapped[int | None] = mapped_column(Integer)  # UTC
    trading_end_hour: Mapped[int | None] = mapped_column(Integer)  # UTC

    # Full config JSON (for arbitrary extra params)
    extra: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ── Risk Events ───────────────────────────────────────────────────────────────


class RiskEvent(Base):
    """
    Risk management event log.

    Records every risk-related action: kill switch triggers,
    position limit breaches, daily loss warnings, etc.
    """

    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)  # info, warning, critical
    strategy_id: Mapped[str | None] = mapped_column(String(100), index=True)
    ticker: Mapped[str | None] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(JSONB)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
