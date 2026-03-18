"""
JA Hedge — Multi-Source Intelligence System.

This package provides the data source framework, individual source
adapters, feature fusion, and health monitoring for all alternative
data that feeds into the Frankenstein prediction model.

Architecture:
  DataSourceHub (registry + orchestrator)
    ├── Source adapters (sports odds, news, twitter, weather, crypto, ...)
    ├── FeatureFusion (merges alt-data features into the 57-feature vector)
    ├── SourceHealthMonitor (tracks freshness, accuracy, uptime per source)
    └── Routes + dashboard data endpoints
"""

from app.intelligence.hub import DataSourceHub, DataSourceStatus
from app.intelligence.base import DataSource, DataSourceType, SourceSignal
from app.intelligence.fusion import FeatureFusionEngine
from app.intelligence.confidence import SourceConfidenceTracker, AdaptiveWeightEngine
from app.intelligence.alerts import AlertPipeline, Alert, AlertType, AlertSeverity
from app.intelligence.backfill import HistoricalBackfillEngine
from app.intelligence.correlation import SourceCorrelationMatrix
from app.intelligence.quality import DataQualityMonitor

__all__ = [
    "DataSourceHub",
    "DataSourceStatus",
    "DataSource",
    "DataSourceType",
    "SourceSignal",
    "FeatureFusionEngine",
    "SourceConfidenceTracker",
    "AdaptiveWeightEngine",
    "AlertPipeline",
    "Alert",
    "AlertType",
    "AlertSeverity",
    "HistoricalBackfillEngine",
    "SourceCorrelationMatrix",
    "DataQualityMonitor",
]
