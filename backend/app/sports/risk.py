"""
JA Hedge — Sports Risk Management (Phase S7).

Sports-specific risk rules layered on top of AdvancedRiskManager:
  - Max exposure per game
  - Correlation between markets in same game
  - Tighter stop-losses for live positions
  - Sport-specific position limits
  - Live game position management
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.logging_config import get_logger

log = get_logger("sports.risk")


@dataclass
class SportsRiskLimits:
    """Sports-specific risk constraints."""
    max_exposure_per_game_cents: int = 100_00     # $100 max per game
    max_live_positions: int = 10                    # max live in-game positions
    max_pregame_positions: int = 20                 # max pre-game positions
    max_positions_per_sport: int = 15               # max per sport type
    
    # Tighter stop-losses for live positions
    live_stop_loss_pct: float = 0.15               # 15% stop-loss for live
    pregame_stop_loss_pct: float = 0.20            # 20% for pre-game
    
    # Live trading limits
    max_live_position_size: int = 5                 # max contracts for live bets
    min_live_edge: float = 0.07                     # require more edge for live bets
    
    # Correlation penalty
    correlated_game_discount: float = 0.50         # reduce size 50% for correlated bets


class SportsRiskManager:
    """
    Sports-specific risk management.
    
    Checks BEFORE Frankenstein places a sports trade.
    """
    
    def __init__(self, limits: SportsRiskLimits | None = None):
        self._limits = limits or SportsRiskLimits()
        
        # Track active sports positions
        self._game_exposure: dict[str, int] = {}     # event_ticker -> total_cost_cents
        self._sport_positions: dict[str, int] = {}   # sport_id -> count
        self._live_positions: int = 0
        self._pregame_positions: int = 0
        self._positions: dict[str, dict] = {}        # ticker -> position info
    
    def check(
        self,
        ticker: str,
        event_ticker: str,
        sport_id: str,
        count: int,
        price_cents: int,
        is_live: bool = False,
        edge: float = 0.0,
    ) -> tuple[bool, str | None]:
        """
        Sports-specific risk check.
        
        Returns (passed, rejection_reason).
        """
        new_cost = count * price_cents
        
        # 1. Game exposure limit
        current_game = self._game_exposure.get(event_ticker, 0)
        if current_game + new_cost > self._limits.max_exposure_per_game_cents:
            return False, f"Game exposure limit: ${(current_game + new_cost) / 100:.2f} > ${self._limits.max_exposure_per_game_cents / 100:.2f}"
        
        # 2. Live position limit
        if is_live and self._live_positions >= self._limits.max_live_positions:
            return False, f"Max live positions: {self._live_positions}/{self._limits.max_live_positions}"
        
        # 3. Pre-game position limit
        if not is_live and self._pregame_positions >= self._limits.max_pregame_positions:
            return False, f"Max pregame positions: {self._pregame_positions}/{self._limits.max_pregame_positions}"
        
        # 4. Sport-specific limit
        sport_count = self._sport_positions.get(sport_id, 0)
        if sport_count >= self._limits.max_positions_per_sport:
            return False, f"Max positions for {sport_id}: {sport_count}/{self._limits.max_positions_per_sport}"
        
        # 5. Live position size limit
        if is_live and count > self._limits.max_live_position_size:
            return False, f"Live position too large: {count} > {self._limits.max_live_position_size}"
        
        # 6. Edge requirement for live bets (stricter)
        if is_live and abs(edge) < self._limits.min_live_edge:
            return False, f"Insufficient live edge: {abs(edge):.3f} < {self._limits.min_live_edge}"
        
        return True, None
    
    def adjusted_size(
        self,
        count: int,
        event_ticker: str,
        is_live: bool = False,
    ) -> int:
        """
        Adjust position size based on sports risk factors.
        
        Reduces size for:
        - Correlated positions (same game)
        - Live positions
        """
        adjusted = count
        
        # Correlation discount: reduce if already have positions in same game
        if event_ticker in self._game_exposure:
            existing = self._game_exposure[event_ticker]
            if existing > 0:
                adjusted = max(1, int(adjusted * self._limits.correlated_game_discount))
        
        # Live positions: cap at max_live_position_size
        if is_live:
            adjusted = min(adjusted, self._limits.max_live_position_size)
        
        return adjusted
    
    def get_stop_loss(self, is_live: bool) -> float:
        """Get appropriate stop-loss percentage."""
        if is_live:
            return self._limits.live_stop_loss_pct
        return self._limits.pregame_stop_loss_pct
    
    def register_position(
        self,
        ticker: str,
        event_ticker: str,
        sport_id: str,
        cost_cents: int,
        is_live: bool = False,
    ) -> None:
        """Register a new sports position."""
        self._positions[ticker] = {
            "event_ticker": event_ticker,
            "sport_id": sport_id,
            "cost_cents": cost_cents,
            "is_live": is_live,
            "timestamp": time.time(),
        }
        
        self._game_exposure[event_ticker] = self._game_exposure.get(event_ticker, 0) + cost_cents
        self._sport_positions[sport_id] = self._sport_positions.get(sport_id, 0) + 1
        
        if is_live:
            self._live_positions += 1
        else:
            self._pregame_positions += 1
    
    def remove_position(self, ticker: str) -> None:
        """Remove a closed sports position."""
        pos = self._positions.pop(ticker, None)
        if not pos:
            return
        
        event = pos["event_ticker"]
        sport = pos["sport_id"]
        cost = pos["cost_cents"]
        
        if event in self._game_exposure:
            self._game_exposure[event] = max(0, self._game_exposure[event] - cost)
            if self._game_exposure[event] == 0:
                del self._game_exposure[event]
        
        if sport in self._sport_positions:
            self._sport_positions[sport] = max(0, self._sport_positions[sport] - 1)
            if self._sport_positions[sport] == 0:
                del self._sport_positions[sport]
        
        if pos.get("is_live"):
            self._live_positions = max(0, self._live_positions - 1)
        else:
            self._pregame_positions = max(0, self._pregame_positions - 1)
    
    def summary(self) -> dict[str, Any]:
        total_exposure = sum(self._game_exposure.values())
        return {
            "total_sports_positions": len(self._positions),
            "live_positions": self._live_positions,
            "pregame_positions": self._pregame_positions,
            "total_exposure": f"${total_exposure / 100:.2f}",
            "by_sport": dict(self._sport_positions),
            "by_game": {k: f"${v / 100:.2f}" for k, v in self._game_exposure.items()},
            "limits": {
                "max_per_game": f"${self._limits.max_exposure_per_game_cents / 100:.2f}",
                "max_live": self._limits.max_live_positions,
                "max_pregame": self._limits.max_pregame_positions,
                "live_stop_loss": f"{self._limits.live_stop_loss_pct:.0%}",
            },
        }


# Singleton
sports_risk = SportsRiskManager()
