"""
Tests for TradeMemory save/load round-trip and _by_outcome rebuild.
"""

import pytest
import numpy as np

from app.ai.models import Prediction
from app.ai.features import MarketFeatures
from app.frankenstein.memory import TradeMemory, TradeRecord, TradeOutcome


def _pred(prob: float = 0.75, side: str = "yes", edge: float = 0.1, raw_prob: float = 0.72) -> Prediction:
    return Prediction(
        side=side, confidence=0.5, predicted_prob=prob, edge=edge,
        raw_prob=raw_prob, model_name="test", model_version="test-v1",
    )


def _feat() -> MarketFeatures:
    from datetime import datetime, timezone
    return MarketFeatures(
        ticker="TEST",
        timestamp=datetime.now(timezone.utc),
        midpoint=0.525,
        spread=0.05,
        volume=100.0,
        open_interest=500.0,
        hours_to_expiry=24.0,
    )


class TestTradeMemorySaveLoad:
    """Verify save/load round-trip and outcome counter rebuild."""

    def test_record_and_retrieve(self, trade_memory):
        record = trade_memory.record_trade("TEST-TICK", _pred(), _feat(), "buy", 1, 50)
        recent = trade_memory.get_recent_trades(1)
        assert len(recent) == 1
        assert recent[0].ticker == "TEST-TICK"

    def test_pending_counter_increments(self, trade_memory):
        trade_memory.record_trade("T1", _pred(prob=0.6), _feat(), "buy", 1, 40)
        s = trade_memory.stats()
        assert s["outcomes"]["pending"] >= 1

    def test_resolve_updates_outcome_counters(self, trade_memory):
        record = trade_memory.record_trade("T1", _pred(prob=0.6), _feat(), "buy", 1, 40)
        trade_memory.resolve_trade(record.trade_id, TradeOutcome.WIN, pnl_cents=50)
        s = trade_memory.stats()
        assert s["outcomes"]["win"] >= 1

    def test_save_load_round_trip(self, trade_memory, tmp_path):
        path = str(tmp_path / "mem.json")
        r1 = trade_memory.record_trade("A", _pred(prob=0.7), _feat(), "buy", 1, 55)
        r2 = trade_memory.record_trade("B", _pred(prob=0.3, side="no"), _feat(), "buy", 1, 30)
        trade_memory.resolve_trade(r1.trade_id, TradeOutcome.WIN, pnl_cents=100)
        trade_memory.save(path)

        # Load into fresh memory (auto-loads from persist_path)
        new_mem = TradeMemory(max_trades=1000, persist_path=path)
        assert len(new_mem.get_recent_trades(10)) == 2
        assert new_mem.total_wins == 1

    def test_by_outcome_rebuilt_on_load(self, trade_memory, tmp_path):
        """Critical: _by_outcome must be rebuilt from loaded records (Fix #7)."""
        path = str(tmp_path / "mem.json")
        r1 = trade_memory.record_trade("A", _pred(prob=0.7), _feat(), "buy", 1, 55)
        r2 = trade_memory.record_trade("B", _pred(prob=0.6), _feat(), "buy", 1, 45)
        trade_memory.resolve_trade(r1.trade_id, TradeOutcome.WIN, pnl_cents=50)
        trade_memory.save(path)

        # Fresh load — counters must be rebuilt
        fresh = TradeMemory(max_trades=1000, persist_path=path)
        s = fresh.stats()
        assert s["outcomes"]["win"] >= 1
        assert s["outcomes"]["pending"] >= 1

    def test_clear_resets_everything(self, trade_memory):
        trade_memory.record_trade("X", _pred(prob=0.5), _feat(), "buy", 1, 50)
        trade_memory.clear()
        assert len(trade_memory.get_recent_trades(10)) == 0
        assert trade_memory.total_recorded == 0

    def test_raw_predicted_prob_preserved(self, trade_memory, tmp_path):
        """Ensure raw_predicted_prob survives serialization."""
        path = str(tmp_path / "mem.json")
        trade_memory.record_trade("CAL", _pred(prob=0.78, raw_prob=0.72), _feat(), "buy", 1, 50)
        trade_memory.save(path)

        fresh = TradeMemory(max_trades=1000, persist_path=path)
        loaded = fresh.get_recent_trades(1)[0]
        assert loaded.raw_predicted_prob == pytest.approx(0.72, abs=0.01)
