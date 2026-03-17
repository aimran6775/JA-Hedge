"""
Pytest configuration and shared fixtures for JA Hedge tests.
"""

from __future__ import annotations

import pytest
import numpy as np

from app.ai.models import Prediction, CalibrationTracker, XGBoostPredictor
from app.ai.features import MarketFeatures
from app.frankenstein.memory import TradeMemory, TradeRecord, TradeOutcome
from app.frankenstein.strategy import StrategyParams, AdaptiveStrategy


@pytest.fixture
def calibration_tracker() -> CalibrationTracker:
    """Fresh CalibrationTracker."""
    return CalibrationTracker()


@pytest.fixture
def calibration_tracker_ready() -> CalibrationTracker:
    """CalibrationTracker with 40 samples (above MIN_TOTAL_SAMPLES=30)."""
    ct = CalibrationTracker()
    # Fill bin 7 (0.7-0.8) with 20 samples, 70% positive
    for i in range(20):
        ct.record(0.75, 1 if i < 14 else 0)
    # Fill bin 5 (0.5-0.6) with 20 samples, 50% positive
    for i in range(20):
        ct.record(0.55, 1 if i < 10 else 0)
    return ct


@pytest.fixture
def sample_prediction() -> Prediction:
    return Prediction(
        side="yes",
        confidence=0.45,
        raw_prob=0.72,
        predicted_prob=0.73,
        edge=0.08,
        model_name="xgboost_v1",
        model_version="test-v1",
        tree_agreement=0.85,
        prediction_std=0.03,
    )


@pytest.fixture
def trade_memory(tmp_path) -> TradeMemory:
    return TradeMemory(
        max_trades=1000,
        persist_path=str(tmp_path / "test_memory.json"),
    )


@pytest.fixture
def strategy_params() -> StrategyParams:
    return StrategyParams()
