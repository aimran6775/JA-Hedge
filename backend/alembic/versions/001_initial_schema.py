"""
Initial schema — all core tables.

Revision ID: 001
Revises: None
Create Date: 2025-01-01
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Markets ──────────────────────────────────────────────
    op.create_table(
        "markets",
        sa.Column("ticker", sa.String(100), primary_key=True),
        sa.Column("event_ticker", sa.String(100), nullable=False, index=True),
        sa.Column("series_ticker", sa.String(100), index=True),
        sa.Column("title", sa.Text),
        sa.Column("subtitle", sa.Text),
        sa.Column("category", sa.String(100), index=True),
        sa.Column("market_type", sa.String(20), server_default="binary"),
        sa.Column("status", sa.String(20), index=True, server_default="active"),
        sa.Column("yes_bid", sa.Numeric(12, 4)),
        sa.Column("yes_ask", sa.Numeric(12, 4)),
        sa.Column("no_bid", sa.Numeric(12, 4)),
        sa.Column("no_ask", sa.Numeric(12, 4)),
        sa.Column("last_price", sa.Numeric(12, 4)),
        sa.Column("volume", sa.Numeric(18, 4)),
        sa.Column("open_interest", sa.Numeric(18, 4)),
        sa.Column("open_time", sa.DateTime(timezone=True)),
        sa.Column("close_time", sa.DateTime(timezone=True)),
        sa.Column("expiration_time", sa.DateTime(timezone=True)),
        sa.Column("rules_primary", sa.Text),
        sa.Column("extra", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_markets_status_category", "markets", ["status", "category"])
    op.create_index("ix_markets_event_status", "markets", ["event_ticker", "status"])

    # ── Events ───────────────────────────────────────────────
    op.create_table(
        "events",
        sa.Column("event_ticker", sa.String(100), primary_key=True),
        sa.Column("series_ticker", sa.String(100), index=True),
        sa.Column("title", sa.Text),
        sa.Column("subtitle", sa.Text),
        sa.Column("category", sa.String(100)),
        sa.Column("mutually_exclusive", sa.Boolean, server_default="false"),
        sa.Column("extra", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── Price Snapshots (TimescaleDB hypertable) ─────────────
    op.create_table(
        "price_snapshots",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(100), nullable=False, index=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("yes_bid", sa.Numeric(12, 4)),
        sa.Column("yes_ask", sa.Numeric(12, 4)),
        sa.Column("last_price", sa.Numeric(12, 4)),
        sa.Column("volume", sa.Numeric(18, 4)),
        sa.Column("open_interest", sa.Numeric(18, 4)),
        sa.Column("spread", sa.Numeric(12, 4)),
        sa.Column("midpoint", sa.Numeric(12, 4)),
    )
    op.create_index("ix_price_snap_ticker_ts", "price_snapshots", ["ticker", "ts"])

    # Convert to TimescaleDB hypertable
    op.execute("SELECT create_hypertable('price_snapshots', 'ts', if_not_exists => TRUE);")

    # ── Orders ───────────────────────────────────────────────
    op.create_table(
        "orders",
        sa.Column("order_id", sa.String(100), primary_key=True),
        sa.Column("client_order_id", sa.String(100), unique=True, index=True),
        sa.Column("ticker", sa.String(100), nullable=False, index=True),
        sa.Column("event_ticker", sa.String(100), index=True),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("order_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("yes_price_cents", sa.Integer),
        sa.Column("no_price_cents", sa.Integer),
        sa.Column("yes_price_dollars", sa.String(20)),
        sa.Column("no_price_dollars", sa.String(20)),
        sa.Column("count", sa.Integer),
        sa.Column("remaining_count", sa.Integer),
        sa.Column("fill_count", sa.Integer),
        sa.Column("taker_fees_dollars", sa.String(20)),
        sa.Column("maker_fees_dollars", sa.String(20)),
        sa.Column("taker_fill_cost_dollars", sa.String(20)),
        sa.Column("maker_fill_cost_dollars", sa.String(20)),
        sa.Column("strategy_id", sa.String(100), index=True),
        sa.Column("signal_id", sa.BigInteger, index=True),
        sa.Column("extra", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_orders_ticker_status", "orders", ["ticker", "status"])
    op.create_index("ix_orders_strategy_created", "orders", ["strategy_id", "created_at"])

    # ── Fills ────────────────────────────────────────────────
    op.create_table(
        "fills",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("fill_id", sa.String(100), unique=True, index=True),
        sa.Column("order_id", sa.String(100), nullable=False, index=True),
        sa.Column("ticker", sa.String(100), nullable=False, index=True),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("count", sa.Integer),
        sa.Column("yes_price_cents", sa.Integer),
        sa.Column("no_price_cents", sa.Integer),
        sa.Column("yes_price_dollars", sa.String(20)),
        sa.Column("no_price_dollars", sa.String(20)),
        sa.Column("is_taker", sa.Boolean),
        sa.Column("fee_cost_dollars", sa.String(20)),
        sa.Column("filled_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_fills_ticker_filled", "fills", ["ticker", "filled_at"])

    # ── Positions ────────────────────────────────────────────
    op.create_table(
        "positions",
        sa.Column("ticker", sa.String(100), primary_key=True),
        sa.Column("event_ticker", sa.String(100), index=True),
        sa.Column("yes_count", sa.Integer, server_default="0"),
        sa.Column("no_count", sa.Integer, server_default="0"),
        sa.Column("net_contracts", sa.Integer, server_default="0"),
        sa.Column("avg_entry_price", sa.Numeric(12, 4)),
        sa.Column("total_cost", sa.Numeric(14, 4), server_default="0"),
        sa.Column("realized_pnl", sa.Numeric(14, 4), server_default="0"),
        sa.Column("unrealized_pnl", sa.Numeric(14, 4), server_default="0"),
        sa.Column("total_fees", sa.Numeric(14, 4), server_default="0"),
        sa.Column("market_exposure", sa.Numeric(14, 4), server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── AI Signals ───────────────────────────────────────────
    op.create_table(
        "ai_signals",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(100), nullable=False, index=True),
        sa.Column("strategy_id", sa.String(100), nullable=False, index=True),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("model_version", sa.String(50)),
        sa.Column("predicted_side", sa.String(10), nullable=False),
        sa.Column("confidence", sa.Numeric(8, 6), nullable=False),
        sa.Column("predicted_edge", sa.Numeric(12, 6)),
        sa.Column("kelly_fraction", sa.Numeric(8, 6)),
        sa.Column("recommended_count", sa.Integer),
        sa.Column("recommended_price_cents", sa.Integer),
        sa.Column("features", JSONB),
        sa.Column("actual_result", sa.String(10)),
        sa.Column("actual_pnl", sa.Numeric(14, 4)),
        sa.Column("was_correct", sa.Boolean),
        sa.Column("order_id", sa.String(100), index=True),
        sa.Column("was_executed", sa.Boolean, server_default="false"),
        sa.Column("execution_reason", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_signals_ticker_created", "ai_signals", ["ticker", "created_at"])
    op.create_index("ix_signals_strategy_created", "ai_signals", ["strategy_id", "created_at"])

    # ── Strategy Configs ─────────────────────────────────────
    op.create_table(
        "strategy_configs",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("enabled", sa.Boolean, server_default="true", index=True),
        sa.Column("model_name", sa.String(100), server_default="xgboost_v1"),
        sa.Column("min_confidence", sa.Numeric(8, 6), server_default="0.60"),
        sa.Column("min_edge", sa.Numeric(8, 6), server_default="0.05"),
        sa.Column("kelly_fraction", sa.Numeric(8, 6), server_default="0.25"),
        sa.Column("max_position_size", sa.Integer, server_default="10"),
        sa.Column("max_daily_loss", sa.Numeric(14, 4), server_default="50.0"),
        sa.Column("stop_loss_pct", sa.Numeric(8, 4)),
        sa.Column("take_profit_pct", sa.Numeric(8, 4)),
        sa.Column("allowed_categories", JSONB),
        sa.Column("ticker_whitelist", JSONB),
        sa.Column("ticker_blacklist", JSONB),
        sa.Column("min_volume", sa.Integer),
        sa.Column("min_open_interest", sa.Integer),
        sa.Column("max_spread_cents", sa.Integer),
        sa.Column("min_time_to_expiry_hours", sa.Integer),
        sa.Column("max_time_to_expiry_hours", sa.Integer),
        sa.Column("trading_start_hour", sa.Integer),
        sa.Column("trading_end_hour", sa.Integer),
        sa.Column("extra", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── Risk Events ──────────────────────────────────────────
    op.create_table(
        "risk_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String(50), nullable=False, index=True),
        sa.Column("severity", sa.String(20), nullable=False, index=True),
        sa.Column("strategy_id", sa.String(100), index=True),
        sa.Column("ticker", sa.String(100)),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("details", JSONB),
        sa.Column("resolved", sa.Boolean, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("risk_events")
    op.drop_table("strategy_configs")
    op.drop_table("ai_signals")
    op.drop_table("positions")
    op.drop_table("fills")
    op.drop_table("orders")
    op.drop_table("price_snapshots")
    op.drop_table("events")
    op.drop_table("markets")
