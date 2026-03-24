"""
JA Hedge — Autonomous Trading Agent Framework.

Multi-agent architecture where specialized agents handle different
market domains. Each agent has its own:
  - Strategy (edge detection method)
  - Confidence requirements (min grade, min edge)
  - Position limits (max positions, max exposure)
  - Scan behavior (frequency, market filter)
  - Performance tracking (per-agent win rate, PnL)

Frankenstein is the orchestrator. Agents are the specialists.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.ai.features import MarketFeatures
from app.ai.models import Prediction
from app.kalshi.models import Market
from app.logging_config import get_logger

log = get_logger("agents.base")


@dataclass
class AgentConfig:
    """Configuration for a trading agent."""
    name: str = "base_agent"
    enabled: bool = True
    
    # Quality gates — these are the KEY profit lever
    min_edge: float = 0.05           # 5% minimum edge
    min_confidence: float = 0.50     # 50% minimum confidence
    min_grade: str = "B"             # B minimum grade
    
    # Position limits
    max_positions: int = 15          # per-agent
    max_exposure_cents: int = 1000_00  # $1000 per agent
    max_per_trade_cents: int = 200_00  # $200 max single trade
    
    # Scan behavior
    scan_interval: float = 30.0      # seconds between scans
    
    # Category filter — which markets this agent handles
    categories: list[str] = field(default_factory=list)  # empty = all
    
    # Performance-based auto-disable
    min_win_rate: float = 0.25       # disable if below 25% after 20 trades
    min_trades_for_eval: int = 20    # need 20 trades before evaluation
    
    # Sizing
    kelly_fraction: float = 0.25     # conservative Kelly
    max_position_size: int = 10      # max contracts per trade


@dataclass
class AgentPerformance:
    """Live performance stats for an agent."""
    trades: int = 0
    wins: int = 0
    losses: int = 0
    expired: int = 0
    total_pnl_cents: int = 0
    total_cost_cents: int = 0
    best_trade_cents: int = 0
    worst_trade_cents: int = 0
    consecutive_losses: int = 0
    max_consecutive_losses: int = 0
    last_trade_time: float = 0.0
    
    @property
    def win_rate(self) -> float:
        resolved = self.wins + self.losses
        return self.wins / resolved if resolved > 0 else 0.0
    
    @property
    def resolved(self) -> int:
        return self.wins + self.losses
    
    @property
    def avg_pnl_cents(self) -> float:
        return self.total_pnl_cents / self.resolved if self.resolved > 0 else 0.0
    
    @property
    def profit_factor(self) -> float:
        gross_profit = max(self.best_trade_cents, 0)  # simplified
        gross_loss = abs(min(self.worst_trade_cents, 0))
        return gross_profit / max(gross_loss, 1)
    
    def record_win(self, pnl_cents: int):
        self.wins += 1
        self.trades += 1
        self.total_pnl_cents += pnl_cents
        self.best_trade_cents = max(self.best_trade_cents, pnl_cents)
        self.consecutive_losses = 0
        self.last_trade_time = time.time()
    
    def record_loss(self, pnl_cents: int):
        self.losses += 1
        self.trades += 1
        self.total_pnl_cents += pnl_cents
        self.worst_trade_cents = min(self.worst_trade_cents, pnl_cents)
        self.consecutive_losses += 1
        self.max_consecutive_losses = max(
            self.max_consecutive_losses, self.consecutive_losses
        )
        self.last_trade_time = time.time()
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": f"{self.win_rate:.1%}",
            "total_pnl": f"${self.total_pnl_cents/100:+.2f}",
            "avg_pnl": f"${self.avg_pnl_cents/100:+.2f}",
            "best": f"${self.best_trade_cents/100:+.2f}",
            "worst": f"${self.worst_trade_cents/100:+.2f}",
            "consec_losses": self.consecutive_losses,
            "max_consec_losses": self.max_consecutive_losses,
        }


@dataclass
class AgentSignal:
    """A trade signal from an agent."""
    agent_name: str
    ticker: str
    side: str              # "yes" or "no"
    confidence: float      # 0-1
    edge: float            # expected edge
    size_contracts: int    # recommended size
    price_cents: int       # recommended price
    urgency: float = 0.5   # 0=patient, 1=urgent
    reason: str = ""
    features: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    
    @property
    def ev_cents(self) -> float:
        """Expected value in cents."""
        return self.edge * self.size_contracts * 100


class TradingAgent(ABC):
    """Base class for all trading agents."""
    
    def __init__(self, config: AgentConfig):
        self.config = config
        self.perf = AgentPerformance()
        self._active_positions: dict[str, dict] = {}  # ticker → position info
        self._last_scan: float = 0.0
        self._disabled_reason: str = ""
    
    @property
    def name(self) -> str:
        return self.config.name
    
    @property
    def is_enabled(self) -> bool:
        if not self.config.enabled:
            return False
        # Auto-disable if performance is bad
        if self.perf.resolved >= self.config.min_trades_for_eval:
            if self.perf.win_rate < self.config.min_win_rate:
                self._disabled_reason = (
                    f"win_rate_{self.perf.win_rate:.1%}_below_{self.config.min_win_rate:.1%}"
                )
                return False
        # Auto-disable on consecutive losses
        if self.perf.consecutive_losses >= 8:
            self._disabled_reason = f"consec_losses_{self.perf.consecutive_losses}"
            return False
        return True
    
    @property
    def can_scan(self) -> bool:
        return (
            self.is_enabled
            and time.time() - self._last_scan >= self.config.scan_interval
            and len(self._active_positions) < self.config.max_positions
        )
    
    def accepts_market(self, market: Market, category: str) -> bool:
        """Does this agent handle this market category?"""
        if not self.config.categories:
            return True  # empty = all categories
        return category in self.config.categories
    
    @abstractmethod
    def evaluate(
        self,
        market: Market,
        features: MarketFeatures,
        prediction: Prediction,
        category: str,
    ) -> AgentSignal | None:
        """Evaluate a market and return a signal (or None to skip)."""
        ...
    
    @abstractmethod
    def should_exit(
        self,
        market: Market,
        features: MarketFeatures,
        prediction: Prediction,
        entry_price: float,
        unrealized_pnl_pct: float,
    ) -> tuple[bool, str]:
        """Should we exit this position? Returns (should_exit, reason)."""
        ...
    
    def record_entry(self, ticker: str, side: str, count: int, price_cents: int):
        self._active_positions[ticker] = {
            "side": side, "count": count, "price_cents": price_cents,
            "time": time.time(),
        }
        self.perf.total_cost_cents += count * price_cents
    
    def record_exit(self, ticker: str):
        self._active_positions.pop(ticker, None)
    
    def record_outcome(self, ticker: str, won: bool, pnl_cents: int):
        if won:
            self.perf.record_win(pnl_cents)
        else:
            self.perf.record_loss(pnl_cents)
        self._active_positions.pop(ticker, None)
    
    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.is_enabled,
            "disabled_reason": self._disabled_reason,
            "positions": len(self._active_positions),
            "max_positions": self.config.max_positions,
            "performance": self.perf.to_dict(),
        }


# ═══════════════════════════════════════════════════════════════════
# CONCRETE AGENTS
# ═══════════════════════════════════════════════════════════════════

class VegasSportsAgent(TradingAgent):
    """
    Agent 1: Vegas-Kalshi Arbitrage
    
    ONLY trades sports when Vegas data is available.
    Exploits the gap between professional bookmaker odds and Kalshi prices.
    This is our strongest edge — Vegas lines are priced by sharp money.
    """
    
    def __init__(self):
        super().__init__(AgentConfig(
            name="vegas_sports",
            categories=["sports"],
            min_edge=0.05,           # 5% edge minimum (Vegas-backed)
            min_confidence=0.55,
            min_grade="B",
            max_positions=20,
            max_exposure_cents=1500_00,
            kelly_fraction=0.30,
            max_position_size=15,
            scan_interval=15.0,      # fast scan for sports
            min_win_rate=0.35,       # sports should win >35%
        ))
    
    def evaluate(self, market, features, prediction, category) -> AgentSignal | None:
        # ONLY trade if this signal came from Vegas baseline
        if prediction.model_name not in ("naive_vegas_baseline", "sports_xgb"):
            return None  # No Vegas data → skip entirely
        
        if abs(prediction.edge) < self.config.min_edge:
            return None
        
        if prediction.confidence < self.config.min_confidence:
            return None
        
        # Size based on confidence and edge
        size = max(1, int(self.config.kelly_fraction * self.config.max_position_size * prediction.confidence))
        size = min(size, self.config.max_position_size)
        
        price_cents = int(features.midpoint * 100)
        if prediction.side == "yes":
            price_cents = max(2, min(price_cents + 1, 97))
        else:
            price_cents = max(2, min(100 - price_cents + 1, 97))
        
        return AgentSignal(
            agent_name=self.name,
            ticker=market.ticker,
            side=prediction.side,
            confidence=prediction.confidence,
            edge=prediction.edge,
            size_contracts=size,
            price_cents=price_cents,
            urgency=0.7,
            reason=f"Vegas arb: edge={prediction.edge:.1%}, conf={prediction.confidence:.2f}",
        )
    
    def should_exit(self, market, features, prediction, entry_price, unrealized_pnl_pct):
        hrs = features.hours_to_expiry
        # Tight stops for sports (fast-moving)
        stop = 0.20
        if hrs < 1:
            stop = 0.10  # very tight near expiry
        elif hrs < 4:
            stop = 0.15
        
        if unrealized_pnl_pct < -stop:
            return True, f"stop_loss_{unrealized_pnl_pct:.1%}"
        
        # Take profit: earlier near expiry
        tp = 0.15 if hrs < 2 else 0.25
        if unrealized_pnl_pct > tp:
            return True, f"take_profit_{unrealized_pnl_pct:.1%}"
        
        return False, ""


class LiveGameAgent(TradingAgent):
    """
    Agent 2: Live In-Game Trading
    
    Trades during live sports events using real-time game state.
    Exploits:
    - Score-based mispricing (blowouts where Kalshi hasn't adjusted)
    - Momentum runs (scoring streaks)
    - Garbage time (late scoring in blowouts is meaningless)
    - Halftime overreaction (reversion to home advantage)
    
    This is the volatile, fast money.
    """
    
    def __init__(self):
        super().__init__(AgentConfig(
            name="live_game",
            categories=["sports"],
            min_edge=0.04,           # Lower edge OK for live (structural)
            min_confidence=0.45,
            min_grade="C+",
            max_positions=10,
            max_exposure_cents=800_00,
            kelly_fraction=0.20,     # smaller sizing (volatile)
            max_position_size=8,
            scan_interval=10.0,      # very fast for live
            min_win_rate=0.30,
        ))
        self._live_engine = None  # injected
    
    def set_live_engine(self, engine):
        self._live_engine = engine
    
    def evaluate(self, market, features, prediction, category) -> AgentSignal | None:
        if not self._live_engine:
            return None
        
        # Only live markets
        if features.hours_to_expiry > 4:  # if >4h to expiry, probably not live
            return None
        
        # Check for live signals
        signals = self._live_engine.get_pending_signals(max_age_seconds=60)
        for sig in signals:
            if sig.ticker == market.ticker:
                # Map live signal to agent signal
                if sig.strength < 0.3:
                    continue
                
                size = max(1, int(sig.strength * self.config.max_position_size))
                price_cents = int(features.midpoint * 100)
                if sig.side == "yes":
                    price_cents = max(2, min(price_cents + 2, 97))  # cross spread for speed
                else:
                    price_cents = max(2, min(100 - price_cents + 2, 97))
                
                return AgentSignal(
                    agent_name=self.name,
                    ticker=market.ticker,
                    side=sig.side,
                    confidence=sig.strength,
                    edge=sig.strength * 0.10,  # estimate edge from signal strength
                    size_contracts=size,
                    price_cents=price_cents,
                    urgency=sig.urgency,
                    reason=f"Live: {sig.signal_type} — {sig.reason}",
                )
        
        return None
    
    def should_exit(self, market, features, prediction, entry_price, unrealized_pnl_pct):
        # Very tight stops for live trading
        if unrealized_pnl_pct < -0.12:
            return True, f"live_stop_{unrealized_pnl_pct:.1%}"
        # Quick take-profit
        if unrealized_pnl_pct > 0.10:
            return True, f"live_profit_{unrealized_pnl_pct:.1%}"
        return False, ""


class ContrarianAgent(TradingAgent):
    """
    Agent 3: Contrarian/Mean-Reversion
    
    Detects overreactions and trades against them.
    Works especially well in volatile markets (live sports, crypto).
    
    Logic: If price moved >15% from recent average, bet on reversion.
    """
    
    def __init__(self):
        super().__init__(AgentConfig(
            name="contrarian",
            categories=["sports", "crypto", "politics"],
            min_edge=0.06,
            min_confidence=0.50,
            min_grade="B",
            max_positions=12,
            max_exposure_cents=1000_00,
            kelly_fraction=0.20,
            max_position_size=8,
            scan_interval=20.0,
            min_win_rate=0.30,
        ))
    
    def evaluate(self, market, features, prediction, category) -> AgentSignal | None:
        mid = features.midpoint
        
        # Need some volume to confirm the move is real
        if features.volume < 50:
            return None
        
        # Only trade extremes (strong mean-reversion targets)
        # Market at <20¢ or >80¢ suggests potential overreaction
        if 0.10 < mid < 0.25:
            # Market is saying "very unlikely" — contrarian says "maybe"
            # Only if there's enough time for reversion
            if features.hours_to_expiry < 2:
                return None
            edge = 0.50 - mid  # distance from 50/50
            if edge < 0.15:
                return None
            
            size = max(1, min(5, int(edge * 20)))
            return AgentSignal(
                agent_name=self.name,
                ticker=market.ticker,
                side="yes",
                confidence=min(0.60, 0.40 + edge * 0.5),
                edge=edge * 0.3,  # discount edge (contrarian is risky)
                size_contracts=size,
                price_cents=max(2, int(mid * 100) + 1),
                urgency=0.4,
                reason=f"Contrarian: price={mid:.0%} too low, expect reversion",
            )
        
        elif 0.75 < mid < 0.90:
            if features.hours_to_expiry < 2:
                return None
            edge = mid - 0.50
            if edge < 0.15:
                return None
            
            size = max(1, min(5, int(edge * 20)))
            return AgentSignal(
                agent_name=self.name,
                ticker=market.ticker,
                side="no",
                confidence=min(0.60, 0.40 + edge * 0.5),
                edge=edge * 0.3,
                size_contracts=size,
                price_cents=max(2, int((1 - mid) * 100) + 1),
                urgency=0.4,
                reason=f"Contrarian: price={mid:.0%} too high, expect reversion",
            )
        
        return None
    
    def should_exit(self, market, features, prediction, entry_price, unrealized_pnl_pct):
        if unrealized_pnl_pct < -0.18:
            return True, f"contrarian_stop_{unrealized_pnl_pct:.1%}"
        if unrealized_pnl_pct > 0.20:
            return True, f"contrarian_profit_{unrealized_pnl_pct:.1%}"
        return False, ""


class CryptoAgent(TradingAgent):
    """
    Agent 4: Crypto Specialist
    
    Crypto was our best category (+$4.94, 16.7% WR).
    This agent focuses exclusively on crypto markets with
    higher aggression since we have demonstrated edge.
    """
    
    def __init__(self):
        super().__init__(AgentConfig(
            name="crypto",
            categories=["crypto"],
            min_edge=0.04,           # lower bar (proven edge)
            min_confidence=0.45,
            min_grade="C+",
            max_positions=15,
            max_exposure_cents=1200_00,
            kelly_fraction=0.30,     # more aggressive
            max_position_size=12,
            scan_interval=20.0,
            min_win_rate=0.20,       # crypto is volatile, 20% OK
        ))
    
    def evaluate(self, market, features, prediction, category) -> AgentSignal | None:
        if abs(prediction.edge) < self.config.min_edge:
            return None
        if prediction.confidence < self.config.min_confidence:
            return None
        
        # Crypto-specific: boost on high volume (crowd wisdom)
        vol_boost = 1.0
        if features.volume > 500:
            vol_boost = 1.3
        elif features.volume > 200:
            vol_boost = 1.15
        
        adjusted_edge = prediction.edge * vol_boost
        size = max(1, int(
            self.config.kelly_fraction * self.config.max_position_size
            * prediction.confidence * vol_boost
        ))
        size = min(size, self.config.max_position_size)
        
        price_cents = int(features.midpoint * 100)
        if prediction.side == "yes":
            price_cents = max(2, min(price_cents, 97))
        else:
            price_cents = max(2, min(100 - price_cents, 97))
        
        return AgentSignal(
            agent_name=self.name,
            ticker=market.ticker,
            side=prediction.side,
            confidence=prediction.confidence,
            edge=adjusted_edge,
            size_contracts=size,
            price_cents=price_cents,
            urgency=0.5,
            reason=f"Crypto: edge={adjusted_edge:.1%}, vol={features.volume:.0f}",
        )
    
    def should_exit(self, market, features, prediction, entry_price, unrealized_pnl_pct):
        if unrealized_pnl_pct < -0.20:
            return True, f"crypto_stop_{unrealized_pnl_pct:.1%}"
        if unrealized_pnl_pct > 0.25:
            return True, f"crypto_profit_{unrealized_pnl_pct:.1%}"
        # Edge reversal
        if prediction.side != ("yes" if unrealized_pnl_pct > 0 else "no"):
            if prediction.confidence > 0.65:
                return True, f"crypto_reversal_{prediction.side}@{prediction.confidence:.2f}"
        return False, ""


class WeatherAgent(TradingAgent):
    """
    Agent 5: Weather Specialist
    
    Weather was marginally profitable (+$0.79).
    Conservative agent that only trades high-confidence weather signals.
    """
    
    def __init__(self):
        super().__init__(AgentConfig(
            name="weather",
            categories=["weather"],
            min_edge=0.05,
            min_confidence=0.55,
            min_grade="B",
            max_positions=8,
            max_exposure_cents=500_00,
            kelly_fraction=0.20,
            max_position_size=6,
            scan_interval=60.0,       # weather moves slowly
            min_win_rate=0.25,
        ))
    
    def evaluate(self, market, features, prediction, category) -> AgentSignal | None:
        if abs(prediction.edge) < self.config.min_edge:
            return None
        if prediction.confidence < self.config.min_confidence:
            return None
        
        size = max(1, int(
            self.config.kelly_fraction * self.config.max_position_size
            * prediction.confidence
        ))
        size = min(size, self.config.max_position_size)
        
        price_cents = int(features.midpoint * 100)
        if prediction.side == "yes":
            price_cents = max(2, min(price_cents, 97))
        else:
            price_cents = max(2, min(100 - price_cents, 97))
        
        return AgentSignal(
            agent_name=self.name,
            ticker=market.ticker,
            side=prediction.side,
            confidence=prediction.confidence,
            edge=prediction.edge,
            size_contracts=size,
            price_cents=price_cents,
            urgency=0.3,
            reason=f"Weather: edge={prediction.edge:.1%}",
        )
    
    def should_exit(self, market, features, prediction, entry_price, unrealized_pnl_pct):
        if unrealized_pnl_pct < -0.15:
            return True, f"weather_stop_{unrealized_pnl_pct:.1%}"
        if unrealized_pnl_pct > 0.20:
            return True, f"weather_profit_{unrealized_pnl_pct:.1%}"
        return False, ""


class NearExpirySniper(TradingAgent):
    """
    Agent 6: Near-Expiry Sniper
    
    Trades markets within 1 hour of expiry where the outcome
    is nearly certain but the price hasn't fully adjusted.
    Very high hit rate when it works.
    """
    
    def __init__(self):
        super().__init__(AgentConfig(
            name="near_expiry",
            categories=[],  # any category
            min_edge=0.08,           # needs big edge (near expiry = high risk)
            min_confidence=0.65,
            min_grade="B+",
            max_positions=8,
            max_exposure_cents=600_00,
            kelly_fraction=0.35,     # aggressive (high confidence)
            max_position_size=10,
            scan_interval=10.0,      # fast scan near expiry
            min_win_rate=0.40,       # should be high hit rate
        ))
    
    def evaluate(self, market, features, prediction, category) -> AgentSignal | None:
        # Only near-expiry markets
        if features.hours_to_expiry > 1.0:
            return None
        if features.hours_to_expiry < 0.05:  # too close, might not fill
            return None
        
        mid = features.midpoint
        # Only trade when price is extreme (high certainty)
        if 0.15 < mid < 0.85:
            return None  # too uncertain for near-expiry
        
        if abs(prediction.edge) < self.config.min_edge:
            return None
        
        # Near expiry with extreme price = high confidence
        size = max(1, int(self.config.kelly_fraction * self.config.max_position_size))
        
        price_cents = int(mid * 100) if prediction.side == "yes" else int((1 - mid) * 100)
        price_cents = max(2, min(price_cents + 2, 97))  # cross spread for fill
        
        return AgentSignal(
            agent_name=self.name,
            ticker=market.ticker,
            side=prediction.side,
            confidence=prediction.confidence,
            edge=prediction.edge,
            size_contracts=size,
            price_cents=price_cents,
            urgency=0.9,  # urgent — expiring soon
            reason=f"NearExpiry: {features.hours_to_expiry:.1f}h, mid={mid:.0%}, edge={prediction.edge:.1%}",
        )
    
    def should_exit(self, market, features, prediction, entry_price, unrealized_pnl_pct):
        # Very tight stops (near expiry moves fast)
        if unrealized_pnl_pct < -0.08:
            return True, f"expiry_stop_{unrealized_pnl_pct:.1%}"
        if unrealized_pnl_pct > 0.12:
            return True, f"expiry_profit_{unrealized_pnl_pct:.1%}"
        return False, ""


class HighVolumeAgent(TradingAgent):
    """
    Agent 7: High Volume / Crowd Wisdom
    
    Only trades markets with very high volume (>500).
    High volume = better price discovery = model predictions more reliable.
    """
    
    def __init__(self):
        super().__init__(AgentConfig(
            name="high_volume",
            categories=[],  # any category
            min_edge=0.04,
            min_confidence=0.50,
            min_grade="B",
            max_positions=15,
            max_exposure_cents=1200_00,
            kelly_fraction=0.25,
            max_position_size=10,
            scan_interval=30.0,
            min_win_rate=0.30,
        ))
    
    def evaluate(self, market, features, prediction, category) -> AgentSignal | None:
        # Require high volume
        if features.volume < 500:
            return None
        
        # Require tight spread (well-priced market)
        if features.spread > 0.05:
            return None
        
        if abs(prediction.edge) < self.config.min_edge:
            return None
        if prediction.confidence < self.config.min_confidence:
            return None
        
        size = max(1, int(
            self.config.kelly_fraction * self.config.max_position_size
            * prediction.confidence
        ))
        size = min(size, self.config.max_position_size)
        
        price_cents = int(features.midpoint * 100)
        if prediction.side == "yes":
            price_cents = max(2, min(price_cents, 97))
        else:
            price_cents = max(2, min(100 - price_cents, 97))
        
        return AgentSignal(
            agent_name=self.name,
            ticker=market.ticker,
            side=prediction.side,
            confidence=prediction.confidence,
            edge=prediction.edge,
            size_contracts=size,
            price_cents=price_cents,
            urgency=0.5,
            reason=f"HighVol: vol={features.volume:.0f}, spread={features.spread:.0%}, edge={prediction.edge:.1%}",
        )
    
    def should_exit(self, market, features, prediction, entry_price, unrealized_pnl_pct):
        if unrealized_pnl_pct < -0.15:
            return True, f"highvol_stop_{unrealized_pnl_pct:.1%}"
        if unrealized_pnl_pct > 0.20:
            return True, f"highvol_profit_{unrealized_pnl_pct:.1%}"
        return False, ""


# ═══════════════════════════════════════════════════════════════════
# AGENT ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════

class AgentOrchestrator:
    """
    Manages all trading agents. Frankenstein delegates to this.
    
    Responsibilities:
    - Route markets to appropriate agents
    - Collect and rank signals across agents
    - Track per-agent performance
    - Auto-disable failing agents
    - Report aggregate status
    """
    
    def __init__(self):
        self.agents: list[TradingAgent] = [
            VegasSportsAgent(),
            LiveGameAgent(),
            ContrarianAgent(),
            CryptoAgent(),
            WeatherAgent(),
            NearExpirySniper(),
            HighVolumeAgent(),
        ]
        self._agent_map: dict[str, TradingAgent] = {
            a.name: a for a in self.agents
        }
        self._total_signals = 0
        self._total_trades = 0
        log.info("agent_orchestrator_initialized", agents=len(self.agents))
    
    def get_agent(self, name: str) -> TradingAgent | None:
        return self._agent_map.get(name)
    
    def evaluate_market(
        self,
        market: Market,
        features: MarketFeatures,
        prediction: Prediction,
        category: str,
    ) -> list[AgentSignal]:
        """
        Route a market to all applicable agents.
        Returns signals sorted by EV (best first).
        """
        signals = []
        
        for agent in self.agents:
            if not agent.is_enabled:
                continue
            if not agent.accepts_market(market, category):
                continue
            
            try:
                signal = agent.evaluate(market, features, prediction, category)
                if signal:
                    signals.append(signal)
                    self._total_signals += 1
            except Exception as e:
                log.debug("agent_eval_error", agent=agent.name, 
                         ticker=market.ticker, error=str(e))
        
        # Sort by EV (highest first)
        signals.sort(key=lambda s: s.ev_cents, reverse=True)
        return signals
    
    def record_outcome(self, ticker: str, agent_name: str, won: bool, pnl_cents: int):
        """Record a trade outcome for the responsible agent."""
        agent = self._agent_map.get(agent_name)
        if agent:
            agent.record_outcome(ticker, won, pnl_cents)
    
    def status(self) -> dict[str, Any]:
        return {
            "total_agents": len(self.agents),
            "active_agents": sum(1 for a in self.agents if a.is_enabled),
            "total_signals": self._total_signals,
            "agents": {a.name: a.status() for a in self.agents},
        }
    
    def inject_live_engine(self, engine):
        """Wire the live trading engine into the LiveGameAgent."""
        for agent in self.agents:
            if isinstance(agent, LiveGameAgent):
                agent.set_live_engine(engine)
                log.info("live_engine_injected", agent=agent.name)
