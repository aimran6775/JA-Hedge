"""
JA Hedge — Central Configuration.

All settings loaded from environment variables / .env file.
Pydantic Settings gives us typed, validated config with sensible defaults.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppMode(str, Enum):
    DEMO = "demo"
    PRODUCTION = "production"


# ── Kalshi URL constants ──────────────────────────────────────────────────────

_KALSHI_URLS = {
    AppMode.DEMO: {
        "rest": "https://demo-api.kalshi.co/trade-api/v2",
        "ws": "wss://demo-api.kalshi.co/trade-api/ws/v2",
    },
    AppMode.PRODUCTION: {
        "rest": "https://api.elections.kalshi.com/trade-api/v2",
        "ws": "wss://api.elections.kalshi.com/trade-api/ws/v2",
    },
}


def _find_env_file() -> str | Path:
    """Find .env file — check CWD first, then parent (for running from backend/)."""
    cwd = Path.cwd()
    if (cwd / ".env").exists():
        return cwd / ".env"
    if (cwd.parent / ".env").exists():
        return cwd.parent / ".env"
    return ".env"  # fallback: let pydantic handle it


class Settings(BaseSettings):
    """Application settings — single source of truth."""

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=_find_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Mode ──────────────────────────────────────────────
    jahedge_mode: AppMode = AppMode.DEMO

    # ── Kalshi API ────────────────────────────────────────
    kalshi_api_key_id: str = ""
    kalshi_private_key_path: str = "./keys/kalshi.pem"
    kalshi_rest_base_url: str | None = None
    kalshi_ws_base_url: str | None = None
    kalshi_timeout: float = Field(default=10.0, description="HTTP request timeout in seconds")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def kalshi_rest_url(self) -> str:
        """Resolved REST URL — override or auto from mode."""
        return self.kalshi_rest_base_url or _KALSHI_URLS[self.jahedge_mode]["rest"]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def kalshi_ws_url(self) -> str:
        """Resolved WebSocket URL — override or auto from mode."""
        return self.kalshi_ws_base_url or _KALSHI_URLS[self.jahedge_mode]["ws"]

    @property
    def has_api_keys(self) -> bool:
        """Check if API keys are configured."""
        return bool(self.kalshi_api_key_id) and self.resolved_key_path.exists()

    @property
    def resolved_key_path(self) -> Path:
        """Resolve key path — try CWD first, then project root (parent of backend/)."""
        p = Path(self.kalshi_private_key_path)
        if p.is_absolute() or p.exists():
            return p
        # Try project root (parent of CWD when running from backend/)
        alt = Path.cwd().parent / p
        if alt.exists():
            return alt
        return p  # fallback to original

    # ── Database ──────────────────────────────────────────
    postgres_user: str = "jahedge"
    postgres_password: str = "jahedge_dev_2026"
    postgres_db: str = "jahedge"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url_sync(self) -> str:
        """Sync URL for Alembic migrations."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ── Redis ─────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── Backend Server ────────────────────────────────────
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    port: int = 8000  # Railway injects PORT
    log_level: str = "INFO"
    log_format: str = "json"  # "json" or "console"

    # ── Risk Defaults ─────────────────────────────────────
    risk_max_daily_loss: float = 50.0
    risk_max_position_size: int = 10
    risk_max_portfolio_exposure: float = 500.0
    kill_switch_enabled: bool = True
    # ── Paper Trading ─────────────────────────────────────────────
    paper_trading: bool = True  # Use simulated balance (fake money)
    paper_trading_balance: int = 10_000_00  # Starting balance in cents ($10,000)
    # ── Strategy Defaults ─────────────────────────────────
    strategy_min_confidence: float = 0.60
    strategy_min_edge: float = 0.05
    strategy_kelly_fraction: float = 0.25
    strategy_scan_interval: float = 30.0

    # ── Sports Trading ────────────────────────────────────
    the_odds_api_key: str = ""                # The Odds API v4 key
    sports_only_mode: bool = True              # Only trade sports markets
    sports_scan_interval_live: float = 15.0    # Faster scan during live games
    sports_odds_cache_ttl: float = 300.0       # 5 min cache for odds
    sports_min_vegas_discrepancy: float = 0.05 # 5% minimum edge to trade

    # ── Celery ────────────────────────────────────────────
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ── Rate Limiting ─────────────────────────────────────
    rate_limit_read_per_sec: int = Field(default=20, description="Read requests per second")
    rate_limit_write_per_sec: int = Field(default=10, description="Write requests per second")


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
