"""
Frankenstein — Chat Engine. 🧟💬

A conversational interface to Frankenstein's brain. Users can ask about
trading strategies, market analysis, performance, and system state.
Frankenstein responds like an expert Kalshi trader with full access to
its own memory, performance metrics, strategy parameters, and market data.

No external LLM required — Frankenstein generates responses from its
own data, logic, and domain expertise built into this module.
"""

from __future__ import annotations

import random
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from app.logging_config import get_logger

if TYPE_CHECKING:
    from app.frankenstein.brain import Frankenstein

log = get_logger("frankenstein.chat")


# ── Data Structures ──────────────────────────────────────────────────────

@dataclass
class ChatMessage:
    """A single message in the chat."""
    role: str          # "user" or "frankenstein"
    content: str
    timestamp: float = field(default_factory=time.time)
    data: dict[str, Any] | None = None   # Optional structured data attached

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "time_human": datetime.fromtimestamp(
                self.timestamp, tz=timezone.utc
            ).strftime("%I:%M %p"),
            "data": self.data,
        }


@dataclass
class ChatSession:
    """A chat session with message history."""
    messages: deque[ChatMessage] = field(
        default_factory=lambda: deque(maxlen=200)
    )
    created_at: float = field(default_factory=time.time)
    message_count: int = 0

    def add(self, msg: ChatMessage) -> None:
        self.messages.append(msg)
        self.message_count += 1


# ── Intent Classification ────────────────────────────────────────────────

INTENT_KEYWORDS: dict[str, list[str]] = {
    "status": [
        "status", "how are you", "state", "alive", "awake",
        "running", "health", "doing", "up",
    ],
    "performance": [
        "performance", "pnl", "p&l", "profit", "loss", "win rate",
        "sharpe", "returns", "drawdown", "how much", "making money",
        "losing", "earning", "results", "track record",
    ],
    "strategy": [
        "strategy", "strategies", "approach", "how do you trade", "method",
        "technique", "plan", "thinking", "logic", "algorithm",
        "kelly", "sizing", "confidence", "edge", "threshold",
        "parameters", "config", "settings", "aggressive", "conservative",
        "trading", "trade style",
    ],
    "markets": [
        "market", "markets", "opportunity", "opportunities",
        "looking at", "watching", "scanning", "candidates",
        "kalshi", "events", "categories", "ticker",
    ],
    "memory": [
        "memory", "memories", "trades", "history", "recent", "last trade",
        "past trades", "trade log", "experience", "remember",
        "pending", "open trades", "positions",
    ],
    "learning": [
        "learning", "model", "retrain", "training", "evolving",
        "generation", "xgboost", "features", "importance",
        "champion", "challenger", "accuracy", "improving",
        "getting better", "smarter",
    ],
    "regime": [
        "regime", "market condition", "volatile", "trending",
        "quiet", "mean revert", "conditions", "environment",
        "sentiment",
    ],
    "risk": [
        "risk", "risks", "risky", "danger", "drawdown", "max loss", "stop loss",
        "careful", "safe", "exposure", "pause", "kill switch",
        "degrading",
    ],
    "explain": [
        "explain", "why", "how does", "what is", "tell me about",
        "describe", "help", "teach", "understand",
    ],
    "capabilities": [
        "what can you do", "capabilities", "abilities", "features",
        "help me", "commands", "options", "menu",
    ],
    "greeting": [
        "hello", "hi", "hey", "sup", "yo", "whats up",
        "good morning", "good evening", "greetings",
    ],
    "identity": [
        "who are you", "what are you", "your name", "about you",
        "introduce", "frankenstein",
    ],
    "deployed": [
        "deployed", "production", "railway", "live", "what we have",
        "current system", "infrastructure", "architecture",
        "tech stack", "built with",
    ],
}


def classify_intent(text: str) -> list[str]:
    """Classify user message into one or more intents."""
    import re
    text_lower = text.lower().strip()
    matches: list[tuple[str, int]] = []

    for intent, keywords in INTENT_KEYWORDS.items():
        score = 0
        for kw in keywords:
            # Use word boundary matching for short keywords to avoid false positives
            if len(kw) <= 3:
                if re.search(r'\b' + re.escape(kw) + r'\b', text_lower):
                    score += 1
            else:
                if kw in text_lower:
                    score += 1
        if score > 0:
            matches.append((intent, score))

    matches.sort(key=lambda x: -x[1])

    if not matches:
        return ["general"]

    # Return top intents (max 3)
    return [m[0] for m in matches[:3]]


# ── The Chat Engine ──────────────────────────────────────────────────────

class FrankensteinChat:
    """
    Frankenstein's conversational interface.

    Generates intelligent responses about trading strategies,
    performance, and system state by pulling live data from
    the Frankenstein brain.
    """

    def __init__(self, brain: Frankenstein):
        self.brain = brain
        self.session = ChatSession()

        # Personality traits
        self._greetings = [
            "🧟⚡ I'm alive and ready to talk trading.",
            "🧟 Frankenstein here. What do you want to know?",
            "🧟⚡ The brain is online. Ask me anything about our trades.",
        ]

        log.info("frankenstein_chat_initialized")

    # ── Public API ────────────────────────────────────────────────────

    def chat(self, user_message: str) -> ChatMessage:
        """
        Process a user message and return Frankenstein's response.

        Returns a ChatMessage with the response text and optional
        structured data for the frontend to render.
        """
        # Record user message
        user_msg = ChatMessage(role="user", content=user_message)
        self.session.add(user_msg)

        # Classify intent
        intents = classify_intent(user_message)
        log.debug("chat_intent", message=user_message[:80], intents=intents)

        # Generate response based on intent
        response_text, response_data = self._generate_response(intents, user_message)

        # Record Frankenstein's response
        frank_msg = ChatMessage(
            role="frankenstein",
            content=response_text,
            data=response_data,
        )
        self.session.add(frank_msg)

        return frank_msg

    def get_history(self, n: int = 50) -> list[dict]:
        """Get recent chat history."""
        messages = list(self.session.messages)[-n:]
        return [m.to_dict() for m in messages]

    def get_welcome(self) -> ChatMessage:
        """Generate a welcome message when chat opens."""
        brain = self.brain
        s = brain._state

        if s.is_alive:
            status_line = "I'm **awake and active**."
            if s.is_paused:
                status_line = f"I'm awake but **paused** — {s.pause_reason}."
            elif s.is_trading:
                status_line = "I'm **awake and actively trading**."
        else:
            status_line = "I'm currently **sleeping**. Wake me up with `/awaken`."

        snap = brain.performance.compute_snapshot()
        memory_size = brain.memory.size

        lines = [
            f"🧟⚡ **Frankenstein Online** — Generation {s.generation}",
            "",
            status_line,
            "",
        ]

        if memory_size > 0:
            lines.extend([
                f"📊 **{memory_size}** trades in memory | "
                f"**{snap.win_rate:.0%}** win rate | "
                f"**${snap.total_pnl:.2f}** total P&L",
                "",
            ])

        lines.extend([
            "Ask me about my **strategy**, **performance**, **markets**, or anything else.",
            "I'm the brain behind JA Hedge — I know everything about our trading system.",
        ])

        msg = ChatMessage(
            role="frankenstein",
            content="\n".join(lines),
            data={"type": "welcome", "generation": s.generation, "alive": s.is_alive},
        )
        self.session.add(msg)
        return msg

    # ── Response Generator ────────────────────────────────────────────

    def _generate_response(
        self, intents: list[str], raw_message: str
    ) -> tuple[str, dict[str, Any] | None]:
        """Generate response text and optional data based on intents."""

        primary = intents[0] if intents else "general"

        handlers = {
            "greeting": self._handle_greeting,
            "identity": self._handle_identity,
            "status": self._handle_status,
            "performance": self._handle_performance,
            "strategy": self._handle_strategy,
            "markets": self._handle_markets,
            "memory": self._handle_memory,
            "learning": self._handle_learning,
            "regime": self._handle_regime,
            "risk": self._handle_risk,
            "explain": self._handle_explain,
            "capabilities": self._handle_capabilities,
            "deployed": self._handle_deployed,
        }

        handler = handlers.get(primary, self._handle_general)
        return handler(raw_message, intents)

    # ── Intent Handlers ───────────────────────────────────────────────

    def _handle_greeting(self, msg: str, intents: list[str]) -> tuple[str, dict | None]:
        return random.choice(self._greetings), {"type": "greeting"}

    def _handle_identity(self, msg: str, intents: list[str]) -> tuple[str, dict | None]:
        s = self.brain._state
        text = (
            "🧟 I'm **Frankenstein** — the self-evolving AI brain behind JA Hedge.\n\n"
            "I'm not just a simple trading bot. I'm a unified intelligence that:\n"
            "- 🔍 **Scans** hundreds of Kalshi markets every cycle\n"
            "- 🧠 **Predicts** outcomes using XGBoost ML models\n"
            "- 📐 **Sizes** positions with Kelly criterion for optimal risk/reward\n"
            "- ⚡ **Executes** trades through risk-managed pipelines\n"
            "- 🧬 **Learns** from every trade outcome — win or loss\n"
            "- 🔄 **Retrains** my model hourly with new data\n"
            "- 🎛️ **Adapts** strategy parameters to market conditions\n"
            "- 🛡️ **Monitors** my own health and pauses when degrading\n\n"
            f"Currently on **Generation {s.generation}** "
            f"(model version: `{s.model_version}`).\n"
            f"I've executed **{s.total_trades_executed}** trades and "
            f"scanned markets **{s.total_scans}** times."
        )
        return text, {"type": "identity", "generation": s.generation}

    def _handle_status(self, msg: str, intents: list[str]) -> tuple[str, dict | None]:
        status = self.brain.status()
        s = self.brain._state

        alive_str = "⚡ **ALIVE**" if s.is_alive else "💤 **SLEEPING**"
        trading_str = ""
        if s.is_alive:
            if s.is_paused:
                trading_str = f" | ⏸️ **PAUSED** ({s.pause_reason})"
            elif s.is_trading:
                trading_str = " | 📈 **ACTIVELY TRADING**"

        text = (
            f"🧟 Frankenstein Status: {alive_str}{trading_str}\n\n"
            f"**Generation:** {s.generation} | **Model:** `{s.model_version}`\n"
            f"**Uptime:** {status['uptime_human']}\n\n"
            f"📊 **Activity:**\n"
            f"- Scans: {s.total_scans}\n"
            f"- Signals found: {s.total_signals}\n"
            f"- Trades executed: {s.total_trades_executed}\n"
            f"- Trades rejected: {s.total_trades_rejected}\n"
            f"- Last scan: {s.current_scan_time_ms:.0f}ms\n\n"
            f"🧠 **Memory:** {status['memory']['total_trades']} trades stored\n"
            f"📈 **Scheduler:** {status['scheduler']['total_tasks']} background tasks"
        )

        return text, {"type": "status", "status": status}

    def _handle_performance(self, msg: str, intents: list[str]) -> tuple[str, dict | None]:
        snap = self.brain.performance.compute_snapshot()
        should_pause, pause_reason = self.brain.performance.should_pause_trading()
        degrading = self.brain.performance.is_model_degrading()

        # Build commentary
        if snap.total_trades == 0:
            text = (
                "📊 **No trades yet!** I haven't executed any trades, "
                "so there's no performance data to show.\n\n"
                "Wake me up and let me scan some markets, then ask again."
            )
            return text, {"type": "performance", "snapshot": snap.to_dict()}

        health = "🟢 **Healthy**"
        if degrading:
            health = "🟡 **Model degrading** — considering retraining"
        if should_pause:
            health = f"🔴 **Should pause** — {pause_reason}"

        # Win/loss commentary
        if snap.win_rate > 0.60:
            wr_comment = "Solid win rate — we're making good calls."
        elif snap.win_rate > 0.50:
            wr_comment = "Above breakeven. The edge is there."
        elif snap.win_rate > 0.40:
            wr_comment = "Below 50% — need to tighten entry criteria."
        else:
            wr_comment = "Win rate is low. Time to retrain or pause."

        # Sharpe commentary
        if snap.sharpe_ratio > 2.0:
            sharpe_comment = "Excellent risk-adjusted returns."
        elif snap.sharpe_ratio > 1.0:
            sharpe_comment = "Decent Sharpe. Room to improve."
        elif snap.sharpe_ratio > 0:
            sharpe_comment = "Positive but mediocre risk-adjustment."
        else:
            sharpe_comment = "Negative Sharpe — losing money on a risk-adjusted basis."

        text = (
            f"📊 **Performance Report** — {health}\n\n"
            f"**P&L:**\n"
            f"- Total: **${snap.total_pnl:.2f}**\n"
            f"- Today: ${snap.daily_pnl:.2f}\n"
            f"- This hour: ${snap.hourly_pnl:.2f}\n\n"
            f"**Win Rate:** {snap.win_rate:.1%} ({snap.total_trades} trades) — {wr_comment}\n\n"
            f"**Risk Metrics:**\n"
            f"- Sharpe Ratio: {snap.sharpe_ratio:.2f} — {sharpe_comment}\n"
            f"- Sortino Ratio: {snap.sortino_ratio:.2f}\n"
            f"- Max Drawdown: ${snap.max_drawdown:.2f}\n"
            f"- Profit Factor: {snap.profit_factor:.2f}\n\n"
            f"**Trade Quality:**\n"
            f"- Avg Win: ${snap.avg_win:.2f} | Avg Loss: ${snap.avg_loss:.2f}\n"
            f"- Largest Win: ${snap.largest_win:.2f} | Largest Loss: ${snap.largest_loss:.2f}\n"
            f"- Prediction Accuracy: {snap.prediction_accuracy:.1%}\n"
            f"- Unique Markets: {snap.unique_markets}\n"
            f"- Regime: **{snap.regime}**"
        )

        return text, {"type": "performance", "snapshot": snap.to_dict()}

    def _handle_strategy(self, msg: str, intents: list[str]) -> tuple[str, dict | None]:
        stats = self.brain.strategy.stats()
        params = stats["current_params"]
        snap = self.brain.performance.compute_snapshot()

        # Explain the current strategy logic
        aggression = params.get("aggression", 0.5)
        if aggression > 0.7:
            agg_desc = "**aggressive** — taking more risk for higher returns"
        elif aggression > 0.4:
            agg_desc = "**moderate** — balanced risk/reward"
        else:
            agg_desc = "**conservative** — protecting capital, tight entries"

        text = (
            f"🎯 **Trading Strategy** — Currently {agg_desc}\n\n"
            f"**How I decide to trade:**\n"
            f"1. **Scan** all active Kalshi markets\n"
            f"2. **Compute features** — spread, volume, book imbalance, momentum, RSI, MACD, etc.\n"
            f"3. **Predict** yes/no probability with my XGBoost model\n"
            f"4. **Filter** — only trade when confidence ≥ {params['min_confidence']:.0%} "
            f"and edge ≥ {params['min_edge']:.1%}\n"
            f"5. **Size** position with Kelly criterion "
            f"(fraction: {params['kelly_fraction']:.0%}, max: {params['max_position_size']} contracts)\n"
            f"6. **Risk check** — verify exposure limits, daily loss, spread\n"
            f"7. **Execute** — place limit order and track in memory\n\n"
            f"**Current Parameters:**\n"
            f"- Min Confidence: {params['min_confidence']:.0%}\n"
            f"- Min Edge: {params['min_edge']:.1%}\n"
            f"- Kelly Fraction: {params['kelly_fraction']:.0%}\n"
            f"- Max Position Size: {params['max_position_size']} contracts\n"
            f"- Max Simultaneous Positions: {params['max_simultaneous_positions']}\n"
            f"- Max Daily Loss: ${params['max_daily_loss']:.0f}\n"
            f"- Max Spread: {params['max_spread_cents']}¢\n"
            f"- Aggression Score: {aggression:.2f}\n\n"
            f"**Adaptations:** {stats['total_adaptations']} total adjustments made\n"
            f"**Market Regime:** {snap.regime}"
        )

        return text, {"type": "strategy", "params": params, "stats": stats}

    def _handle_markets(self, msg: str, intents: list[str]) -> tuple[str, dict | None]:
        from app.pipeline import market_cache

        cached = market_cache.get_active()
        total = len(cached) if cached else 0

        if total == 0:
            text = (
                "🏛️ **Market Data:**\n\n"
                "No markets cached right now. I need to be awake and scanning "
                "to have live market data. Wake me up with `/awaken`!"
            )
            return text, {"type": "markets", "count": 0}

        # Analyze the cached markets
        with_spread = [m for m in cached if m.yes_bid and m.yes_ask]
        tight_spread = [m for m in with_spread if (m.yes_ask - m.yes_bid) <= 5]
        high_volume = sorted(
            [m for m in cached if m.volume and m.volume > 0],
            key=lambda x: x.volume or 0,
            reverse=True,
        )[:5]

        # Categories
        categories: dict[str, int] = {}
        for m in cached:
            cat = getattr(m, "category", "unknown") or "unknown"
            categories[cat] = categories.get(cat, 0) + 1

        cat_lines = "\n".join(
            f"  - {cat}: {count}" for cat, count in
            sorted(categories.items(), key=lambda x: -x[1])[:8]
        )

        top_vol_lines = "\n".join(
            f"  - `{m.ticker}`: vol={m.volume:,.0f}, "
            f"mid={((m.yes_bid or 0) + (m.yes_ask or 0)) / 200:.0%}"
            for m in high_volume
        ) if high_volume else "  No volume data available"

        text = (
            f"🏛️ **Market Scan** — {total} markets cached\n\n"
            f"**Spread Analysis:**\n"
            f"- Markets with active spreads: {len(with_spread)}\n"
            f"- Tight spread (≤5¢): {len(tight_spread)} — best for trading\n\n"
            f"**Top 5 by Volume:**\n{top_vol_lines}\n\n"
            f"**Categories:**\n{cat_lines}\n\n"
            f"I filter for markets with sufficient volume (>{self.brain.strategy.params.min_volume:.0f}), "
            f"tight spreads (≤{self.brain.strategy.params.max_spread_cents}¢), and "
            f"enough time to expiry (>{self.brain.strategy.params.min_hours_to_expiry:.0f}h)."
        )

        return text, {"type": "markets", "count": total, "categories": categories}

    def _handle_memory(self, msg: str, intents: list[str]) -> tuple[str, dict | None]:
        stats = self.brain.memory.stats()
        recent = self.brain.memory.get_recent_trades(n=5)
        pending = self.brain.memory.get_pending_trades()

        recent_lines = ""
        if recent:
            recent_lines = "\n**Last 5 Trades:**\n"
            for t in recent:
                outcome_emoji = {
                    "win": "✅", "loss": "❌", "pending": "⏳",
                    "expired": "⌛", "cancelled": "🚫",
                }.get(t.outcome.value if hasattr(t.outcome, 'value') else str(t.outcome), "❓")
                pnl_str = f"${t.pnl_cents / 100:.2f}" if t.pnl_cents else "—"
                recent_lines += (
                    f"  {outcome_emoji} `{t.ticker}` — "
                    f"{t.predicted_side} @ {t.price_cents}¢, "
                    f"conf={t.confidence:.0%}, P&L={pnl_str}\n"
                )

        text = (
            f"🧠 **Trade Memory** — {stats['total_trades']} trades stored\n\n"
            f"**Breakdown:**\n"
            f"- Resolved: {stats['total_resolved']}\n"
            f"- Pending: {stats['total_pending']}\n"
            f"- Wins: {stats.get('total_wins', 'N/A')}\n"
            f"- Losses: {stats.get('total_losses', 'N/A')}\n\n"
            f"**Important trades pinned:** {stats.get('important_trades', 0)}\n"
            f"**Memory capacity:** {stats['total_trades']}/{stats.get('max_capacity', 50000)}"
            f"{recent_lines}"
        )

        if pending:
            text += f"\n\n⏳ **{len(pending)} trades still pending** — waiting for market settlement."

        return text, {
            "type": "memory",
            "stats": stats,
            "recent": [t.to_dict() for t in recent],
        }

    def _handle_learning(self, msg: str, intents: list[str]) -> tuple[str, dict | None]:
        learner = self.brain.learner
        stats = learner.stats()
        importance = learner.get_feature_importance()

        # Top 5 features
        sorted_features = sorted(importance.items(), key=lambda x: -x[1])[:5]
        feat_lines = "\n".join(
            f"  {i+1}. **{name}**: {score:.3f}"
            for i, (name, score) in enumerate(sorted_features)
        ) if sorted_features else "  No feature importance data yet (need more training)"

        text = (
            f"🧬 **Learning System** — Generation {stats['generation']}\n\n"
            f"**Model:** `{stats['current_version']}` (XGBoost)\n"
            f"**Training data:** {stats['training_samples']} samples\n"
            f"**Checkpoints saved:** {stats['checkpoints_saved']}\n\n"
            f"**How I learn:**\n"
            f"1. Every trade is recorded with its features and prediction\n"
            f"2. When the market settles, I mark it as WIN or LOSS\n"
            f"3. Every hour (or {self.brain.config.retrain_interval:.0f}s), "
            f"I retrain on all historical data\n"
            f"4. New model must **beat** the current champion to be promoted\n"
            f"5. Champion/challenger pattern ensures I never get worse\n\n"
            f"**Top Features (what matters most):**\n{feat_lines}\n\n"
            f"I'm using a **29-feature** set including spread, momentum, RSI, MACD, "
            f"volume ratios, book imbalance, time decay, and more."
        )

        return text, {"type": "learning", "stats": stats, "features": importance}

    def _handle_regime(self, msg: str, intents: list[str]) -> tuple[str, dict | None]:
        snap = self.brain.performance.compute_snapshot()
        regime = snap.regime

        regime_explanations = {
            "trending": (
                "📈 **Trending** — Markets are showing directional momentum. "
                "I'm leaning into momentum signals and being more aggressive "
                "with position sizing. Trades tend to run in my favor."
            ),
            "mean_reverting": (
                "🔄 **Mean Reverting** — Markets are bouncing around. "
                "I'm fading extremes and taking profit quickly. "
                "Patience pays here — wait for overreaction then countertrend."
            ),
            "volatile": (
                "🌊 **Volatile** — Big swings in both directions. "
                "I've widened my confidence thresholds and reduced position sizes. "
                "Protecting capital is priority — only high-conviction trades."
            ),
            "quiet": (
                "😴 **Quiet** — Low volatility, small moves. "
                "I can afford tighter entry criteria and slightly larger positions. "
                "Edge is consistent but small."
            ),
            "mixed": (
                "🔀 **Mixed** — No clear regime. I'm using balanced parameters "
                "and monitoring for a regime shift."
            ),
            "unknown": (
                "❓ **Unknown** — Not enough data to determine regime. "
                "Need more trades before I can characterize conditions."
            ),
        }

        text = (
            f"🌍 **Market Regime Analysis**\n\n"
            f"{regime_explanations.get(regime, regime_explanations['unknown'])}\n\n"
            f"**How I adapt to regime:**\n"
            f"- Volatile → Higher confidence threshold, smaller positions\n"
            f"- Quiet → Lower threshold, can be more aggressive\n"
            f"- Trending → Momentum-following, wider stops\n"
            f"- Mean Reverting → Fade extremes, quick profit-taking\n\n"
            f"I re-detect regime every 15 minutes using autocorrelation "
            f"of my P&L series and volatility measurements."
        )

        return text, {"type": "regime", "regime": regime, "snapshot": snap.to_dict()}

    def _handle_risk(self, msg: str, intents: list[str]) -> tuple[str, dict | None]:
        snap = self.brain.performance.compute_snapshot()
        should_pause, pause_reason = self.brain.performance.should_pause_trading()
        degrading = self.brain.performance.is_model_degrading()
        params = self.brain.strategy.params

        status = "🟢 **All Clear**"
        if degrading:
            status = "🟡 **Caution — Model Degrading**"
        if should_pause:
            status = f"🔴 **Alert — {pause_reason}**"

        text = (
            f"🛡️ **Risk Assessment** — {status}\n\n"
            f"**Current Exposure:**\n"
            f"- Max Drawdown: ${snap.max_drawdown:.2f}\n"
            f"- Current Drawdown: ${snap.current_drawdown:.2f}\n"
            f"- Consecutive Losses: {snap.consecutive_losses} "
            f"(max: {snap.max_consecutive_losses})\n"
            f"- Daily P&L: ${snap.daily_pnl:.2f}\n\n"
            f"**Risk Limits:**\n"
            f"- Max Daily Loss: ${params.max_daily_loss:.0f}\n"
            f"- Stop Loss: {params.stop_loss_pct:.0%}\n"
            f"- Take Profit: {params.take_profit_pct:.0%}\n"
            f"- Max Position Size: {params.max_position_size} contracts\n"
            f"- Max Positions: {params.max_simultaneous_positions}\n\n"
            f"**Safety Rules:**\n"
            f"- 🔴 Pause after 5 consecutive losses\n"
            f"- 🔴 Pause if daily loss > $50\n"
            f"- 🔴 Pause if max drawdown > $15\n"
            f"- 🔴 Pause if accuracy drops below 35%\n"
            f"- 🟡 Flag if model degradation detected\n\n"
            f"**Model Degrading:** {'⚠️ Yes' if degrading else '✅ No'}\n"
            f"**Should Pause:** {'⚠️ Yes' if should_pause else '✅ No'}"
        )

        return text, {
            "type": "risk",
            "should_pause": should_pause,
            "degrading": degrading,
            "snapshot": snap.to_dict(),
        }

    def _handle_explain(self, msg: str, intents: list[str]) -> tuple[str, dict | None]:
        msg_lower = msg.lower()

        if "kelly" in msg_lower:
            text = (
                "📐 **Kelly Criterion** — Optimal position sizing\n\n"
                "The Kelly formula tells me exactly how much to bet:\n\n"
                "$$f^* = \\frac{p \\cdot b - q}{b}$$\n\n"
                "Where:\n"
                "- $p$ = probability of winning (my model's prediction)\n"
                "- $q$ = probability of losing ($1 - p$)\n"
                "- $b$ = odds (payout ratio)\n"
                "- $f^*$ = fraction of bankroll to wager\n\n"
                f"I use a **fractional Kelly** ({self.brain.strategy.params.kelly_fraction:.0%}) "
                "to reduce variance while maintaining most of the edge.\n\n"
                "Example: If I predict 65% chance of YES at 50¢, "
                "Kelly says bet ~30% of bankroll, but I'd use ~7.5% (quarter Kelly)."
            )
        elif "xgboost" in msg_lower or "model" in msg_lower:
            text = (
                "🤖 **XGBoost Model** — How I predict markets\n\n"
                "I use XGBoost (eXtreme Gradient Boosting) — a top-tier ML algorithm "
                "that builds an ensemble of decision trees.\n\n"
                "**My 29 input features:**\n"
                "- **Price**: midpoint, spread, last price, changes (1m/5m/15m)\n"
                "- **Momentum**: velocity, SMA5/20, EMA12/26, MACD, RSI, momentum_10\n"
                "- **Volume**: raw volume, 5-period MA, volume ratio, open interest\n"
                "- **Order Book**: book imbalance, spread percentage\n"
                "- **Time**: hours to expiry, time decay, hour/day features\n"
                "- **Probability**: implied prob, distance from 50%, extreme indicator\n\n"
                "**Training:**\n"
                "- Binary classification: YES wins (1) vs NO wins (0)\n"
                "- Objective: log loss with L1 + L2 regularization\n"
                "- Early stopping on validation AUC\n"
                "- Champion/challenger: new model must beat current to be promoted"
            )
        elif "feature" in msg_lower:
            importance = self.brain.learner.get_feature_importance()
            sorted_f = sorted(importance.items(), key=lambda x: -x[1])[:10]
            feat_lines = "\n".join(
                f"  {i+1}. **{n}**: {s:.4f}" for i, (n, s) in enumerate(sorted_f)
            ) if sorted_f else "  Not enough training data yet"
            text = (
                f"🔬 **Feature Importance** — What drives my predictions\n\n"
                f"**Top 10 Features:**\n{feat_lines}\n\n"
                f"Higher score = more important for splitting decisions in XGBoost.\n"
                f"I track how these change across generations to detect regime shifts."
            )
        elif "sharpe" in msg_lower:
            text = (
                "📈 **Sharpe Ratio** — Risk-adjusted returns\n\n"
                "$$S = \\frac{E[R] - R_f}{\\sigma_R} \\times \\sqrt{252}$$\n\n"
                "Measures return per unit of risk. Higher = better.\n"
                "- **> 2.0**: Excellent\n"
                "- **1.0 - 2.0**: Good\n"
                "- **0 - 1.0**: Mediocre\n"
                "- **< 0**: Losing money\n\n"
                "I annualize with √252 (trading days). "
                "The Sortino ratio is similar but only penalizes downside deviation."
            )
        else:
            text = (
                "🎓 **I can explain these concepts:**\n\n"
                "- **Kelly criterion** — optimal position sizing\n"
                "- **XGBoost model** — how my ML predictions work\n"
                "- **Features** — what data I use to predict\n"
                "- **Sharpe ratio** — risk-adjusted returns\n\n"
                "Try asking: *\"Explain Kelly criterion\"* or *\"How does the model work?\"*"
            )

        return text, {"type": "explain"}

    def _handle_capabilities(self, msg: str, intents: list[str]) -> tuple[str, dict | None]:
        text = (
            "🧟 **What I can do:**\n\n"
            "**Ask me about:**\n"
            "- 📊 **Performance** — P&L, win rate, Sharpe, drawdown\n"
            "- 🎯 **Strategy** — current parameters, how I trade\n"
            "- 🏛️ **Markets** — what I'm scanning, opportunities\n"
            "- 🧠 **Memory** — recent trades, pending, history\n"
            "- 🧬 **Learning** — model generation, features, retraining\n"
            "- 🌍 **Regime** — market conditions, adaptations\n"
            "- 🛡️ **Risk** — exposure, drawdown, safety rules\n"
            "- 🏗️ **Deployed** — architecture, tech stack, infrastructure\n"
            "- 🎓 **Explain** — Kelly, XGBoost, Sharpe, features\n\n"
            "**Commands:**\n"
            "- `/status` — quick status check\n"
            "- `/awaken` — bring me to life\n"
            "- `/sleep` — put me to sleep\n"
            "- `/retrain` — force model retraining\n\n"
            "Just ask naturally — I'll understand."
        )
        return text, {"type": "capabilities"}

    def _handle_deployed(self, msg: str, intents: list[str]) -> tuple[str, dict | None]:
        s = self.brain._state
        text = (
            "🏗️ **JA Hedge — What We Have Deployed**\n\n"
            "**Architecture:**\n"
            "- **Backend**: FastAPI (Python 3.13) — handles all trading logic\n"
            "- **Frontend**: Next.js 15 + React 19 — real-time dashboard\n"
            "- **ML Engine**: XGBoost with 29-feature pipeline\n"
            "- **Brain**: Frankenstein (me!) — unified AI orchestrator\n"
            "- **Deployment**: Railway.app (backend + frontend)\n\n"
            "**Backend Stack:**\n"
            "- FastAPI + uvicorn (async HTTP)\n"
            "- httpx with HTTP/2 for Kalshi API\n"
            "- XGBoost + scikit-learn for ML\n"
            "- Custom rate limiter (20 reads/s, 10 writes/s)\n"
            "- RSA signature authentication for Kalshi\n\n"
            "**Frankenstein Brain (me):**\n"
            f"- Generation: {s.generation}\n"
            "- 6 subsystems: Memory, Performance, Learner, Strategy, Scheduler, Brain\n"
            "- Trade memory: 50K trade buffer with experience replay\n"
            "- Champion/challenger online learning\n"
            "- Regime detection + adaptive strategy\n"
            "- 6 background tasks (retrain, perf, adapt, save, health, outcomes)\n"
            "- 20 API endpoints for monitoring & control\n\n"
            "**Trading Pipeline:**\n"
            "1. Market scan → 2. Feature extraction (29 features)\n"
            "3. XGBoost prediction → 4. Kelly sizing\n"
            "5. Risk check → 6. Execution → 7. Memory → 8. Learning\n\n"
            "**URLs:**\n"
            "- Backend: `https://backend-production-0a8a.up.railway.app`\n"
            "- Frontend: `https://frontend-production-2c6d.up.railway.app`\n"
            "- Mode: **Demo** (Kalshi demo API)"
        )

        return text, {"type": "deployed"}

    def _handle_general(self, msg: str, intents: list[str]) -> tuple[str, dict | None]:
        # Try to give a helpful response for unclassified messages
        s = self.brain._state

        text = (
            f"🧟 I'm not sure what you're asking, but here's a quick update:\n\n"
            f"- **Status:** {'Alive' if s.is_alive else 'Sleeping'} | "
            f"Gen {s.generation}\n"
            f"- **Trades:** {s.total_trades_executed} executed\n"
            f"- **Memory:** {self.brain.memory.size} trades stored\n\n"
            f"Try asking about my **strategy**, **performance**, **markets**, "
            f"**risk**, or say **help** to see everything I can do."
        )

        return text, {"type": "general"}
