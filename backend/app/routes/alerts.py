"""
JA Hedge — Alerts API routes.

GET  /api/alerts           — List recent alerts
POST /api/alerts/read      — Mark alert(s) as read
GET  /api/alerts/unread    — Get unread count
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.alerts import alert_manager, AlertCategory, AlertLevel

router = APIRouter(prefix="/alerts", tags=["Alerts"])


class AlertResponse(BaseModel):
    id: str
    level: str
    category: str
    title: str
    message: str
    timestamp: float
    iso_time: str
    data: dict
    read: bool


@router.get("", response_model=list[AlertResponse])
async def list_alerts(
    limit: int = Query(50, ge=1, le=200),
    category: str | None = None,
    level: str | None = None,
) -> list[dict]:
    """Get recent alerts with optional filtering."""
    cat = AlertCategory(category) if category else None
    lvl = AlertLevel(level) if level else None
    alerts = alert_manager.get_recent(limit=limit, category=cat, level=lvl)
    return [a.to_dict() for a in reversed(alerts)]  # newest first


@router.get("/unread")
async def unread_count() -> dict:
    return {"unread": alert_manager.unread_count}


@router.post("/read")
async def mark_read(alert_id: str | None = None, all: bool = False) -> dict:
    """Mark one or all alerts as read."""
    if all:
        count = alert_manager.mark_all_read()
        return {"marked": count}
    if alert_id:
        found = alert_manager.mark_read(alert_id)
        return {"found": found, "alert_id": alert_id}
    return {"error": "Provide alert_id or all=true"}
