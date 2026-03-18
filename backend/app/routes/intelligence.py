"""
JA Hedge — Intelligence API Routes.

Phase 10 + 20: Comprehensive endpoints for the multi-source
data intelligence system dashboard.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.logging_config import get_logger
from app.state import state

log = get_logger("routes.intelligence")
router = APIRouter(prefix="/intelligence", tags=["intelligence"])


# ── Helper ────────────────────────────────────────────────────────────────────

def _hub():
    return getattr(state, "intelligence_hub", None)


def _hub_status_dict() -> dict:
    """Get hub status as a plain dict."""
    hub = _hub()
    if not hub:
        return {}
    s = hub.status()
    return s.to_dict() if hasattr(s, "to_dict") else (s if isinstance(s, dict) else {})


def _fusion():
    return getattr(state, "feature_fusion", None)


def _confidence():
    return getattr(state, "confidence_tracker", None)


def _weights():
    return getattr(state, "adaptive_weights", None)


def _alerts():
    return getattr(state, "alert_pipeline", None)


def _backfill():
    return getattr(state, "backfill_engine", None)


def _correlation():
    return getattr(state, "correlation_matrix", None)


def _quality():
    return getattr(state, "quality_monitor", None)


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/status")
async def intelligence_status():
    """Comprehensive status of the entire intelligence system."""
    hub = _hub()
    if not hub:
        return {"status": "not_initialized", "sources": [], "message": "Intelligence hub not started yet"}

    hub_status = _hub_status_dict()

    # Enrich with subsystem statuses
    result = {
        "status": "active" if hub._running else "stopped",
        "running": hub._running,
        **hub_status,
        "subsystems": {},
    }

    alerts = _alerts()
    if alerts:
        result["subsystems"]["alerts"] = alerts.stats()

    backfill = _backfill()
    if backfill:
        result["subsystems"]["backfill"] = backfill.stats()

    corr = _correlation()
    if corr:
        result["subsystems"]["correlation"] = {
            "source_count": len(corr._history),
            "pairs_computed": len(corr._correlations),
            "last_compute": corr._last_compute,
        }

    quality = _quality()
    if quality:
        result["subsystems"]["quality"] = quality.to_dict()

    confidence = _confidence()
    if confidence:
        result["subsystems"]["confidence"] = confidence.stats()

    return result


# ── Sources ───────────────────────────────────────────────────────────────────

@router.get("/sources")
async def intelligence_sources():
    """Detailed per-source information."""
    hub = _hub()
    if not hub:
        return {"sources": []}

    hub_status = _hub_status_dict()
    sources = hub_status.get("sources", [])

    # Enrich with quality scores and confidence
    quality = _quality()
    quality_scores = quality.get_quality_scores() if quality else {}

    confidence = _confidence()
    reliabilities = confidence.get_all_reliabilities() if confidence else {}

    for src in sources:
        name = src.get("name", "")
        src["quality_score"] = round(quality_scores.get(name, 1.0), 3)
        src["reliability"] = {
            cat: round(val, 3)
            for cat, val in reliabilities.get(name, {}).items()
        }

    return {"sources": sources}


# ── Signals ───────────────────────────────────────────────────────────────────

@router.get("/signals")
async def intelligence_signals(
    ticker: str | None = Query(None, description="Filter by ticker"),
    category: str | None = Query(None, description="Filter by category"),
):
    """Current signals from all sources."""
    hub = _hub()
    if not hub:
        return {"signals": [], "count": 0}

    if ticker:
        signals = hub.get_signals_for_ticker(ticker)
        signal_list = [
            {
                "source": s.source_name,
                "type": s.source_type.value if hasattr(s.source_type, "value") else str(s.source_type),
                "ticker": s.ticker,
                "signal_value": round(s.signal_value, 4),
                "confidence": round(s.confidence, 4),
                "edge_estimate": round(s.edge_estimate, 4) if s.edge_estimate else 0,
                "category": s.category,
                "headline": s.headline,
                "features": dict(s.features) if s.features else {},
            }
            for s in signals
        ]
    else:
        all_signals = hub.get_all_signals()
        signal_list = []
        for source_name, ticker_signals in all_signals.items():
            for tk, s in ticker_signals.items():
                if category and s.category != category:
                    continue
                signal_list.append({
                    "source": s.source_name,
                    "type": s.source_type.value if hasattr(s.source_type, "value") else str(s.source_type),
                    "ticker": tk,
                    "signal_value": round(s.signal_value, 4),
                    "confidence": round(s.confidence, 4),
                    "edge_estimate": round(s.edge_estimate, 4) if s.edge_estimate else 0,
                    "category": s.category,
                    "headline": s.headline,
                    "features": dict(s.features) if s.features else {},
                })

    # Sort by absolute signal value (strongest signals first)
    signal_list.sort(key=lambda s: abs(s["signal_value"]), reverse=True)

    return {"signals": signal_list[:200], "count": len(signal_list)}


# ── Alerts ────────────────────────────────────────────────────────────────────

@router.get("/alerts")
async def intelligence_alerts(
    limit: int = Query(50, ge=1, le=200),
    severity: str | None = Query(None),
    alert_type: str | None = Query(None),
    unacknowledged_only: bool = Query(False),
):
    """Recent alerts from the intelligence pipeline."""
    alerts = _alerts()
    if not alerts:
        return {"alerts": [], "stats": {}}

    return {
        "alerts": alerts.get_alerts(
            limit=limit,
            severity=severity,
            alert_type=alert_type,
            unacknowledged_only=unacknowledged_only,
        ),
        "stats": alerts.stats(),
    }


@router.post("/alerts/acknowledge-all")
async def acknowledge_all_alerts():
    alerts = _alerts()
    if not alerts:
        return {"acknowledged": 0}
    count = alerts.acknowledge_all()
    return {"acknowledged": count}


# ── Features (fused vector) ──────────────────────────────────────────────────

@router.get("/features/{ticker}")
async def intelligence_features(ticker: str):
    """Get the fused feature vector for a specific ticker."""
    fusion = _fusion()
    if not fusion:
        return {"ticker": ticker, "features": {}, "message": "Fusion engine not initialized"}

    fused = fusion.fuse(ticker)
    return {
        "ticker": ticker,
        "alt_features": dict(fused.alt_features),
        "source_count": fused.source_count,
        "meta_features": fused.meta_features,
        "vector_length": len(fused.to_full_vector([0.0] * 57)),
    }


# ── Correlation ───────────────────────────────────────────────────────────────

@router.get("/correlation")
async def intelligence_correlation():
    """Source correlation matrix."""
    corr = _correlation()
    if not corr:
        return {"matrix": {}, "message": "Correlation matrix not initialized"}
    return corr.to_dict()


# ── Timeline ──────────────────────────────────────────────────────────────────

@router.get("/timeline")
async def intelligence_timeline(
    hours: float = Query(1.0, ge=0.1, le=24.0),
    source: str | None = Query(None),
    category: str | None = Query(None),
    max_points: int = Query(100, ge=10, le=500),
):
    """Time-series of signal values for charting."""
    backfill = _backfill()
    if not backfill:
        return {"timeline": [], "message": "Backfill engine not initialized"}

    return {
        "timeline": backfill.get_timeline(
            source_name=source,
            category=category,
            hours=hours,
            max_points=max_points,
        ),
        "hours": hours,
    }


# ── Quality ───────────────────────────────────────────────────────────────────

@router.get("/quality")
async def intelligence_quality():
    """Data quality metrics."""
    quality = _quality()
    if not quality:
        return {"overall_quality": 1.0, "source_scores": {}, "issues": []}
    return quality.to_dict()


# ── Weights ───────────────────────────────────────────────────────────────────

@router.get("/weights")
async def intelligence_weights(category: str | None = Query(None)):
    """Current adaptive source weights."""
    weights = _weights()
    if not weights:
        return {"weights": {}, "message": "Adaptive weight engine not initialized"}
    return {"weights": weights.get_weights_summary(category or "")}


# ── Dashboard summary (single call for the frontend) ─────────────────────────

@router.get("/dashboard")
async def intelligence_dashboard():
    """Single endpoint that returns everything the dashboard needs."""
    hub = _hub()
    if not hub:
        return {
            "initialized": False,
            "message": "Intelligence system not initialized. It will start automatically with the backend.",
        }

    hub_status = _hub_status_dict()
    sources = hub_status.get("sources", [])

    # Quality scores
    quality = _quality()
    quality_scores = quality.get_quality_scores() if quality else {}
    overall_quality = quality.get_overall_quality() if quality else 1.0

    # Confidence / reliability
    confidence = _confidence()
    reliabilities = confidence.get_all_reliabilities() if confidence else {}

    # Alerts
    alerts = _alerts()
    alert_stats = alerts.stats() if alerts else {}
    recent_alerts = alerts.get_alerts(limit=10) if alerts else []

    # Weights
    weights = _weights()
    weight_summary = weights.get_weights_summary() if weights else {}

    # Signals summary
    all_signals = hub.get_all_signals()
    total_signals = sum(len(ts) for ts in all_signals.values())
    by_category: dict[str, int] = {}
    for source_signals in all_signals.values():
        for sig in source_signals.values():
            cat = sig.category or "general"
            by_category[cat] = by_category.get(cat, 0) + 1

    # Source details enriched
    enriched_sources = []
    for src in sources:
        name = src.get("name", "")
        enriched_sources.append({
            **src,
            "quality_score": round(quality_scores.get(name, 1.0), 3),
            "weight": round(weight_summary.get(name, 1.0), 3),
            "reliability": {
                cat: round(val, 3)
                for cat, val in reliabilities.get(name, {}).items()
            },
        })

    return {
        "initialized": True,
        "status": "active" if hub._running else "stopped",
        "sources": enriched_sources,
        "summary": {
            "total_sources": len(sources),
            "active_sources": sum(1 for s in sources if s.get("healthy")),
            "total_signals": total_signals,
            "signals_by_category": by_category,
            "overall_quality": round(overall_quality, 3),
        },
        "alerts": {
            "stats": alert_stats,
            "recent": recent_alerts,
        },
    }
