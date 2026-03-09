"""
JA Hedge — SQLAlchemy Async Database Engine.

Provides:
- Async engine with connection pooling
- Async session factory
- Base declarative model
- Database lifecycle management
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings
from app.logging_config import get_logger

log = get_logger("db")


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


# Module-level singletons (initialized in lifespan)
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db() -> None:
    """Initialize the async engine and session factory."""
    global _engine, _session_factory

    settings = get_settings()
    _engine = create_async_engine(
        settings.database_url,
        echo=settings.log_level == "DEBUG",
        pool_size=20,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=3600,
    )
    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    log.info("db_initialized", url=settings.database_url.split("@")[-1])


async def close_db() -> None:
    """Dispose of the engine and all connections."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        log.info("db_closed")
    _engine = None
    _session_factory = None


def get_engine() -> AsyncEngine:
    """Get the async engine (must call init_db first)."""
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get the session factory (must call init_db first)."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _session_factory


async def get_session() -> AsyncSession:
    """
    Dependency for FastAPI — yields an async session.

    Usage in FastAPI:
        @router.get("/example")
        async def example(session: AsyncSession = Depends(get_session)):
            ...
    """
    factory = get_session_factory()
    async with factory() as session:
        yield session  # type: ignore[misc]
