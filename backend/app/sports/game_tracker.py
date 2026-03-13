"""
JA Hedge — Live Game State Tracking (Phase S4).

Tracks in-progress games using scores from The Odds API:
  - Period / quarter / half / inning
  - Running score
  - Momentum detection (who's on a run?)
  - Game progress estimation
  - Close game / blowout classification
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.logging_config import get_logger

log = get_logger("sports.game_tracker")


@dataclass
class GameState:
    """Full state of a tracked game."""
    game_id: str
    sport_id: str = ""
    home_team: str = ""
    away_team: str = ""
    
    # Score
    home_score: int = 0
    away_score: int = 0
    
    # Period tracking
    period: int = 0              # current period (1 = 1st quarter, etc.)
    period_name: str = ""        # "1st Quarter", "2nd Half", etc.
    is_halftime: bool = False
    is_overtime: bool = False
    
    # Timing
    game_start_time: float = 0.0
    last_update: float = 0.0
    minutes_elapsed: float = 0.0
    progress: float = 0.0       # 0.0 to 1.0
    
    # Momentum
    home_recent_points: int = 0  # points scored in last update window
    away_recent_points: int = 0
    momentum_home: float = 0.0   # positive = home on a run
    
    # Score history (for momentum computation)
    score_history: list[tuple[float, int, int]] = field(default_factory=list)
    
    # Status
    is_complete: bool = False
    is_live: bool = False
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "sport_id": self.sport_id,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "home_score": self.home_score,
            "away_score": self.away_score,
            "period": self.period,
            "period_name": self.period_name,
            "is_halftime": self.is_halftime,
            "is_overtime": self.is_overtime,
            "minutes_elapsed": self.minutes_elapsed,
            "progress": self.progress,
            "momentum_home": self.momentum_home,
            "is_complete": self.is_complete,
            "is_live": self.is_live,
            "score_differential": self.home_score - self.away_score,
        }


class GameTracker:
    """
    Tracks live game state for all active sports games.
    
    Fed by OddsClient.fetch_scores() on a periodic basis.
    """
    
    def __init__(self) -> None:
        self._games: dict[str, GameState] = {}
        self._event_to_game: dict[str, str] = {}  # event_ticker -> game_id mapping
    
    def update_score(
        self,
        game_id: str,
        home_team: str,
        away_team: str,
        home_score: int | None,
        away_score: int | None,
        sport_id: str = "",
        is_completed: bool = False,
    ) -> GameState:
        """Update game state with new score data."""
        if game_id not in self._games:
            self._games[game_id] = GameState(
                game_id=game_id,
                sport_id=sport_id,
                home_team=home_team,
                away_team=away_team,
                game_start_time=time.time(),
            )
        
        state = self._games[game_id]
        now = time.time()
        
        # Update scores
        old_home = state.home_score
        old_away = state.away_score
        
        if home_score is not None:
            state.home_score = home_score
        if away_score is not None:
            state.away_score = away_score
        
        state.is_complete = is_completed
        state.is_live = not is_completed and (home_score is not None or away_score is not None)
        state.last_update = now
        
        # Compute momentum (recent scoring)
        if home_score is not None and away_score is not None:
            home_delta = state.home_score - old_home
            away_delta = state.away_score - old_away
            state.home_recent_points = home_delta
            state.away_recent_points = away_delta
            
            # Momentum: positive = home team scoring more recently
            # Exponentially decay old momentum, add new
            state.momentum_home = state.momentum_home * 0.7 + (home_delta - away_delta) * 0.3
            
            # Record score history
            state.score_history.append((now, state.home_score, state.away_score))
            # Keep last 50 updates
            if len(state.score_history) > 50:
                state.score_history = state.score_history[-50:]
        
        # Estimate period and progress
        self._estimate_period(state)
        
        return state
    
    def _estimate_period(self, state: GameState) -> None:
        """Estimate current game period based on score and elapsed time."""
        if state.game_start_time <= 0 or not state.is_live:
            return
        
        elapsed_min = (time.time() - state.game_start_time) / 60.0
        state.minutes_elapsed = elapsed_min
        
        # Sport-specific period estimation
        sport = state.sport_id
        
        if sport == "nba":
            # 48 min game, 4 quarters of 12 min each
            game_min = 48
            if elapsed_min <= 12:
                state.period = 1
                state.period_name = "1st Quarter"
            elif elapsed_min <= 24:
                state.period = 2
                state.period_name = "2nd Quarter"
            elif elapsed_min <= 36:
                state.period = 3
                state.period_name = "3rd Quarter"
            elif elapsed_min <= 48:
                state.period = 4
                state.period_name = "4th Quarter"
            else:
                state.period = 5
                state.period_name = "Overtime"
                state.is_overtime = True
            state.progress = min(1.0, elapsed_min / game_min)
            
        elif sport == "nfl":
            game_min = 60
            if elapsed_min <= 15:
                state.period = 1
                state.period_name = "1st Quarter"
            elif elapsed_min <= 30:
                state.period = 2
                state.period_name = "2nd Quarter"
            elif elapsed_min <= 45:
                state.period = 3
                state.period_name = "3rd Quarter"
            elif elapsed_min <= 60:
                state.period = 4
                state.period_name = "4th Quarter"
            else:
                state.period = 5
                state.period_name = "Overtime"
                state.is_overtime = True
            state.progress = min(1.0, elapsed_min / game_min)
            
        elif sport in ("mls", "soccer"):
            game_min = 90
            if elapsed_min <= 45:
                state.period = 1
                state.period_name = "1st Half"
            elif elapsed_min <= 50:
                state.is_halftime = True
                state.period_name = "Halftime"
            elif elapsed_min <= 95:
                state.period = 2
                state.period_name = "2nd Half"
                state.is_halftime = False
            else:
                state.period_name = "Extra Time"
            state.progress = min(1.0, elapsed_min / game_min)
            
        elif sport == "nhl":
            game_min = 60
            if elapsed_min <= 20:
                state.period = 1
                state.period_name = "1st Period"
            elif elapsed_min <= 40:
                state.period = 2
                state.period_name = "2nd Period"
            elif elapsed_min <= 60:
                state.period = 3
                state.period_name = "3rd Period"
            else:
                state.period = 4
                state.period_name = "Overtime"
                state.is_overtime = True
            state.progress = min(1.0, elapsed_min / game_min)
            
        elif sport == "mlb":
            # Estimate based on typical time per inning (~20 min)
            total_score = state.home_score + state.away_score
            est_innings = max(1, min(9, int(elapsed_min / 22) + 1))
            state.period = est_innings
            state.period_name = f"{'Top' if est_innings % 2 == 1 else 'Bottom'} {(est_innings + 1) // 2}"
            state.progress = min(1.0, est_innings / 9.0)
            
        elif sport in ("ncaab",):
            game_min = 40
            if elapsed_min <= 20:
                state.period = 1
                state.period_name = "1st Half"
            elif elapsed_min <= 40:
                state.period = 2
                state.period_name = "2nd Half"
            else:
                state.period = 3
                state.period_name = "Overtime"
                state.is_overtime = True
            state.progress = min(1.0, elapsed_min / game_min)
        else:
            # Generic: assume ~2.5 hour game
            state.progress = min(1.0, elapsed_min / 150.0)
    
    def get_state(self, game_id_or_event: str) -> dict[str, Any] | None:
        """Get game state by game_id or event_ticker."""
        # Direct lookup
        state = self._games.get(game_id_or_event)
        if state:
            return state.to_dict()
        
        # Event ticker lookup
        mapped_id = self._event_to_game.get(game_id_or_event)
        if mapped_id:
            state = self._games.get(mapped_id)
            if state:
                return state.to_dict()
        
        return None
    
    def map_event_to_game(self, event_ticker: str, game_id: str) -> None:
        """Map a Kalshi event_ticker to an Odds API game_id."""
        self._event_to_game[event_ticker] = game_id
    
    def get_live_games(self) -> list[GameState]:
        """Get all currently live games."""
        return [g for g in self._games.values() if g.is_live and not g.is_complete]
    
    def get_completed_games(self) -> list[GameState]:
        """Get recently completed games."""
        return [g for g in self._games.values() if g.is_complete]
    
    def cleanup_old(self, max_age_hours: float = 24.0) -> int:
        """Remove old completed games."""
        cutoff = time.time() - (max_age_hours * 3600)
        to_remove = [
            gid for gid, g in self._games.items()
            if g.is_complete and g.last_update < cutoff
        ]
        for gid in to_remove:
            del self._games[gid]
        return len(to_remove)
    
    def stats(self) -> dict[str, Any]:
        live = [g for g in self._games.values() if g.is_live]
        completed = [g for g in self._games.values() if g.is_complete]
        return {
            "total_tracked": len(self._games),
            "live_games": len(live),
            "completed_games": len(completed),
            "event_mappings": len(self._event_to_game),
            "live_details": [
                {
                    "game_id": g.game_id,
                    "teams": f"{g.away_team} @ {g.home_team}",
                    "score": f"{g.away_score}-{g.home_score}",
                    "period": g.period_name,
                    "progress": f"{g.progress:.0%}",
                }
                for g in live
            ],
        }


# Singleton
game_tracker = GameTracker()
