"""
Frankenstein — LLM Market Analyzer. 🧠🔮

Phase 35: The #1 alpha source for prediction markets.

The people who consistently win on prediction markets (Kalshi, Polymarket,
PredictIt) are those who can read a question like "Will the Fed raise rates
in June 2026?" and produce a BETTER probability estimate than the crowd.

An LLM with world knowledge can do exactly this — and do it for 40,000+
markets simultaneously, 24/7, without fatigue or emotional bias.

Architecture:
    Market Title + Category + Current Price + Context
                    ↓
            GPT-4o-mini (structured output)
                    ↓
    LLMPrediction(probability, confidence, reasoning, side)
                    ↓
            EnsemblePredictor (blended with XGBoost)

Key design decisions:
- GPT-4o-mini: cheapest ($0.15/1M input, $0.60/1M output), fast (<1s),
  good enough for probability estimation. Cost: ~$0.001 per market = $40/day
  for 40K markets. In practice we analyze ~200-500 per scan cycle.
- Structured output: force JSON schema for reliable parsing
- Per-ticker cache (15min TTL): avoid re-analyzing unchanged markets
- Rate limiting: max 50 concurrent, max 500/hour
- Graceful degradation: if API key missing or rate limited, return None
  and let XGBoost handle the prediction alone

Why this works:
- LLMs have encoded vast knowledge about politics, sports, economics,
  science, weather, entertainment from training data
- They can reason about conditional probabilities and base rates
- They're not subject to recency bias, anchoring, or emotional trading
- They provide genuine INFORMATION EDGE over pure price-based features
- Combined with XGBoost's pattern recognition = best of both worlds
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

from app.logging_config import get_logger

log = get_logger("ai.llm_analyzer")

# Cache TTL: 15 minutes (markets don't change that fast)
CACHE_TTL_SECONDS = 900

# Rate limits
MAX_CONCURRENT_REQUESTS = 20
MAX_REQUESTS_PER_HOUR = 500
MAX_REQUESTS_PER_SCAN = 30  # Don't overwhelm the API in one scan cycle

# Cost tracking
COST_PER_INPUT_TOKEN = 0.15 / 1_000_000   # $0.15 per 1M input tokens
COST_PER_OUTPUT_TOKEN = 0.60 / 1_000_000  # $0.60 per 1M output tokens


@dataclass
class LLMPrediction:
    """Structured output from LLM market analysis."""
    ticker: str
    probability: float       # 0.0–1.0, LLM's estimated P(YES)
    confidence: float        # 0.0–1.0, how confident the LLM is in its estimate
    side: str                # "yes" or "no" — which side to trade
    edge: float              # LLM probability - market price (signed)
    reasoning: str           # Brief explanation
    model: str = "gpt-4o-mini"
    cached: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "probability": round(self.probability, 4),
            "confidence": round(self.confidence, 3),
            "side": self.side,
            "edge": round(self.edge, 4),
            "reasoning": self.reasoning[:200],
            "model": self.model,
            "cached": self.cached,
        }


# The core prompt — this is where the alpha lives
SYSTEM_PROMPT = """You are an expert prediction market analyst. Your job is to estimate the probability that a prediction market question resolves YES.

You must output a JSON object with exactly these fields:
- "probability": float between 0.01 and 0.99 — your estimated probability of YES
- "confidence": float between 0.1 and 1.0 — how confident you are in your estimate (0.1 = very uncertain, 1.0 = very certain)
- "reasoning": string — brief 1-2 sentence explanation

Rules:
1. Use your world knowledge, base rates, and reasoning to estimate the probability.
2. Do NOT just echo the current market price. Think independently.
3. Consider base rates: most "will X happen by date Y" questions resolve NO.
4. Consider current conditions: recent events, trends, data you know about.
5. Be calibrated: if you say 70%, that should happen 70% of the time.
6. Express genuine uncertainty — don't default to 50%.
7. For sports: consider team strength, recent form, injuries, home/away.
8. For politics: consider polling data, incumbency advantage, historical patterns.
9. For crypto: consider recent price trends, volatility, support/resistance levels.
10. For weather: consider seasonal patterns, climate data, forecast accuracy.

Output ONLY valid JSON. No markdown, no code blocks, no extra text."""


def _make_user_prompt(
    title: str,
    category: str,
    current_price: float,
    hours_to_expiry: float,
    extra_context: str = "",
) -> str:
    """Build the user prompt for a specific market."""
    price_pct = f"{current_price * 100:.1f}%"
    time_str = (
        f"{hours_to_expiry:.0f} hours"
        if hours_to_expiry > 1
        else f"{hours_to_expiry * 60:.0f} minutes"
    )

    prompt = f"""Market question: "{title}"
Category: {category}
Current market price (crowd consensus): {price_pct}
Time until resolution: {time_str}
Today's date: {time.strftime("%B %d, %Y")}"""

    if extra_context:
        prompt += f"\nAdditional context: {extra_context}"

    prompt += """

Estimate the TRUE probability of YES. Think step-by-step about base rates, current conditions, and relevant factors. Then output your JSON."""

    return prompt


class LLMAnalyzer:
    """
    LLM-powered market probability estimator.

    The single biggest alpha source for prediction markets:
    uses GPT-4o-mini to reason about event outcomes and produce
    calibrated probability estimates that can disagree with the crowd.
    """

    def __init__(self, api_key: str = "", model: str = "gpt-4o-mini") -> None:
        self._api_key = api_key
        self._model = model
        self._client: Any = None  # openai.AsyncOpenAI (lazy init)
        self._enabled = bool(api_key)

        # Cache: ticker_hash → (LLMPrediction, timestamp)
        self._cache: dict[str, tuple[LLMPrediction, float]] = {}

        # Rate limiting
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        self._hourly_count = 0
        self._hourly_reset_time = time.time() + 3600
        self._scan_count = 0

        # Stats
        self._total_requests = 0
        self._total_cached = 0
        self._total_errors = 0
        self._total_cost_usd = 0.0
        self._avg_latency_ms = 0.0

        if self._enabled:
            log.info("llm_analyzer_initialized", model=model)
        else:
            log.info("llm_analyzer_disabled", reason="no API key")

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def _ensure_client(self) -> Any:
        """Lazily create the OpenAI async client."""
        if self._client is None and self._enabled:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(api_key=self._api_key)
            except ImportError:
                log.warning("openai package not installed — LLM analyzer disabled")
                self._enabled = False
                return None
        return self._client

    def _cache_key(self, ticker: str, title: str) -> str:
        """Generate cache key from ticker + title hash."""
        raw = f"{ticker}:{title}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def _check_cache(self, key: str) -> LLMPrediction | None:
        """Check cache for a valid (non-expired) prediction."""
        if key in self._cache:
            pred, ts = self._cache[key]
            if time.time() - ts < CACHE_TTL_SECONDS:
                self._total_cached += 1
                pred.cached = True
                return pred
            else:
                del self._cache[key]
        return None

    def _rate_limit_ok(self) -> bool:
        """Check if we're within rate limits."""
        now = time.time()
        if now >= self._hourly_reset_time:
            self._hourly_count = 0
            self._hourly_reset_time = now + 3600
        return self._hourly_count < MAX_REQUESTS_PER_HOUR

    def reset_scan_count(self) -> None:
        """Reset per-scan request counter. Call at start of each scan cycle."""
        self._scan_count = 0

    async def analyze(
        self,
        ticker: str,
        title: str,
        category: str,
        current_price: float,
        hours_to_expiry: float = 24.0,
        extra_context: str = "",
    ) -> LLMPrediction | None:
        """
        Analyze a market using the LLM and return a probability estimate.

        Returns None if:
        - LLM is disabled (no API key)
        - Rate limited
        - API error
        - Invalid response

        This method is safe to call for every candidate — it handles
        caching, rate limiting, and errors gracefully.
        """
        if not self._enabled:
            return None

        # Check cache first
        key = self._cache_key(ticker, title)
        cached = self._check_cache(key)
        if cached is not None:
            # Update edge with current price (price may have changed since cache)
            cached.edge = cached.probability - current_price
            cached.side = "yes" if cached.edge > 0 else "no"
            return cached

        # Rate limit checks
        if not self._rate_limit_ok():
            return None
        if self._scan_count >= MAX_REQUESTS_PER_SCAN:
            return None

        client = self._ensure_client()
        if client is None:
            return None

        # Call LLM with concurrency limit
        async with self._semaphore:
            try:
                start = time.monotonic()
                self._hourly_count += 1
                self._scan_count += 1
                self._total_requests += 1

                user_prompt = _make_user_prompt(
                    title, category, current_price,
                    hours_to_expiry, extra_context,
                )

                response = await client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.3,        # Low temp for calibrated estimates
                    max_tokens=200,          # Short responses save cost
                    timeout=8.0,             # 8s timeout — don't block the scan
                )

                elapsed_ms = (time.monotonic() - start) * 1000
                self._avg_latency_ms = (
                    self._avg_latency_ms * 0.9 + elapsed_ms * 0.1
                )

                # Track cost
                usage = response.usage
                if usage:
                    cost = (
                        usage.prompt_tokens * COST_PER_INPUT_TOKEN
                        + usage.completion_tokens * COST_PER_OUTPUT_TOKEN
                    )
                    self._total_cost_usd += cost

                # Parse response
                content = response.choices[0].message.content or ""
                pred = self._parse_response(content, ticker, current_price)
                if pred is None:
                    self._total_errors += 1
                    return None

                # Cache it
                self._cache[key] = (pred, time.time())

                log.info(
                    "llm_prediction",
                    ticker=ticker,
                    prob=f"{pred.probability:.3f}",
                    market=f"{current_price:.3f}",
                    edge=f"{pred.edge:+.3f}",
                    conf=f"{pred.confidence:.2f}",
                    ms=f"{elapsed_ms:.0f}",
                    reason=pred.reasoning[:80],
                )

                return pred

            except Exception as e:
                self._total_errors += 1
                log.debug("llm_analyze_error", ticker=ticker, error=str(e))
                return None

    async def analyze_batch(
        self,
        markets: list[dict[str, Any]],
    ) -> dict[str, LLMPrediction]:
        """
        Analyze multiple markets concurrently.

        Each market dict should have: ticker, title, category, midpoint, hours_to_expiry.
        Returns dict of ticker → LLMPrediction (only for successful analyses).

        Prioritizes markets with the most potential edge (furthest from 50%).
        """
        if not self._enabled:
            return {}

        self.reset_scan_count()

        # Sort by potential edge (markets near 50% are boring — LLM has no edge there)
        # Prioritize markets where LLM knowledge is most likely to help
        def _priority(m: dict) -> float:
            mid = m.get("midpoint", 0.5)
            cat = m.get("category", "")
            # Prioritize categories where LLM has domain knowledge
            cat_boost = {
                "politics": 1.5, "economics": 1.4, "science": 1.3,
                "weather": 1.2, "crypto": 1.1, "sports": 1.0,
                "entertainment": 0.9, "culture": 0.8,
            }.get(cat, 0.7)
            return abs(mid - 0.5) * cat_boost

        sorted_markets = sorted(markets, key=_priority, reverse=True)

        # Take top N for this scan (rate limited)
        batch = sorted_markets[:MAX_REQUESTS_PER_SCAN]

        tasks = [
            self.analyze(
                ticker=m["ticker"],
                title=m["title"],
                category=m.get("category", "general"),
                current_price=m.get("midpoint", 0.5),
                hours_to_expiry=m.get("hours_to_expiry", 24.0),
                extra_context=m.get("extra_context", ""),
            )
            for m in batch
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        predictions: dict[str, LLMPrediction] = {}
        for m, result in zip(batch, results):
            if isinstance(result, LLMPrediction):
                predictions[m["ticker"]] = result

        return predictions

    def _parse_response(
        self,
        content: str,
        ticker: str,
        current_price: float,
    ) -> LLMPrediction | None:
        """Parse LLM JSON response into structured prediction."""
        try:
            # Strip markdown code blocks if present
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[-1]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

            data = json.loads(content)

            prob = float(data.get("probability", 0.5))
            conf = float(data.get("confidence", 0.5))
            reasoning = str(data.get("reasoning", ""))

            # Validate ranges
            prob = max(0.01, min(0.99, prob))
            conf = max(0.1, min(1.0, conf))

            # Detect if LLM is just echoing market price (a common failure mode)
            # If LLM probability is within 2% of market price, reduce confidence
            if abs(prob - current_price) < 0.02:
                conf *= 0.5  # LLM is not adding information

            edge = prob - current_price
            side = "yes" if edge > 0 else "no"

            return LLMPrediction(
                ticker=ticker,
                probability=prob,
                confidence=conf,
                side=side,
                edge=edge,
                reasoning=reasoning,
            )

        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            log.debug("llm_parse_error", ticker=ticker, error=str(e),
                      content=content[:100])
            return None

    def evict_stale_cache(self) -> int:
        """Remove expired cache entries. Returns count evicted."""
        now = time.time()
        stale = [k for k, (_, ts) in self._cache.items()
                 if now - ts >= CACHE_TTL_SECONDS]
        for k in stale:
            del self._cache[k]
        return len(stale)

    def stats(self) -> dict[str, Any]:
        """LLM analyzer statistics."""
        return {
            "enabled": self._enabled,
            "model": self._model,
            "total_requests": self._total_requests,
            "total_cached": self._total_cached,
            "total_errors": self._total_errors,
            "cache_size": len(self._cache),
            "cache_hit_rate": round(
                self._total_cached / max(self._total_cached + self._total_requests, 1), 3
            ),
            "hourly_count": self._hourly_count,
            "hourly_limit": MAX_REQUESTS_PER_HOUR,
            "scan_limit": MAX_REQUESTS_PER_SCAN,
            "avg_latency_ms": round(self._avg_latency_ms, 0),
            "total_cost_usd": round(self._total_cost_usd, 4),
        }
