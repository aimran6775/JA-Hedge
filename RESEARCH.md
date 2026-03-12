# JA Hedge — Kalshi Clone & AI Trading Platform
## Complete 10-Phase Research Document

---

# PHASE 1: KALSHI PLATFORM OVERVIEW

## What is Kalshi?
- **Type**: CFTC-regulated prediction market (Designated Contract Market — DCM)
- **Founded**: 2018 by Tarek Mansour & Luana Lopes Lara (MIT)
- **HQ**: 594 Broadway, Manhattan, New York
- **Valuation**: $11 billion (December 2025 funding round — raised $1B)
- **Revenue**: $263.5M in 2025 (89% from sports)
- **Launch**: July 2021 public launch after November 2020 CFTC license

## Core Concept
Binary event contracts — users buy YES or NO on outcomes. Contracts priced 1¢–99¢, always summing to $1.00. If your position is correct, you receive $1.00 per contract. If wrong, you lose your investment.

**Example**: "Will Bitcoin exceed $100K by Dec 31?" — YES at 65¢ means the market implies ~65% probability. Buy YES at 65¢ → win $1.00 (profit 35¢) or lose 65¢.

## Revenue Model
- Standard taker fees: $0.07–$1.75 per contract (varies by market)
- Fee types: `quadratic`, `quadratic_with_maker_fees`, `flat`
- Some markets charge maker fees too
- Contracts settle at $0 or $1.00 (binary) or proportional value (scalar)

## Market Categories
- **Sports**: NFL, NBA, MLB, NHL, Soccer, UFC, Tennis (89% of revenue)
- **Economics**: GDP, Inflation (CPI), Unemployment, Fed Rates
- **Politics**: Elections, Congressional Control, Policy Decisions
- **Weather**: Temperature records, Hurricanes, Snowfall
- **Finance**: Stock prices, Crypto prices, Company earnings
- **Entertainment**: Award shows, TV ratings, Box office
- **Science & Tech**: Space launches, AI milestones
- **Current Events**: Geopolitical events, Regulatory decisions

## Key Partnerships (2025)
- CNN — official prediction market partner
- CNBC — exclusive partnership
- Robinhood — offers Kalshi's football event contracts

---

# PHASE 2: KALSHI API DOCUMENTATION

## API Architecture
- **REST API Version**: v3.8.0
- **Production Base URL**: `https://api.elections.kalshi.com/trade-api/v2`
- **Demo Base URL**: `https://demo-api.kalshi.co/trade-api/v2`
- **Auth Method**: RSA-PSS with SHA256 signatures
- **Format**: JSON, with FixedPointDollars (4 decimal string) and FixedPointCount (2 decimal string)

## Authentication Flow
```
1. Generate RSA key pair on Kalshi (Account → API Keys)
2. For each request:
   - timestamp = current time in milliseconds
   - message = timestamp_str + HTTP_METHOD + path_without_query_params
   - signature = RSA-PSS(SHA256, private_key, message)
3. Headers:
   - KALSHI-ACCESS-KEY: <key_id>
   - KALSHI-ACCESS-SIGNATURE: base64(signature)
   - KALSHI-ACCESS-TIMESTAMP: <timestamp_ms>
```

### Python Auth Example
```python
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
import base64, datetime, requests

def load_private_key(file_path):
    with open(file_path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)

def sign_request(private_key, text):
    signature = private_key.sign(
        text.encode('utf-8'),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode('utf-8')

timestamp_ms = str(int(datetime.datetime.now().timestamp() * 1000))
method = "GET"
path = "/trade-api/v2/portfolio/balance"
sig = sign_request(private_key, timestamp_ms + method + path)
headers = {
    'KALSHI-ACCESS-KEY': '<key_id>',
    'KALSHI-ACCESS-SIGNATURE': sig,
    'KALSHI-ACCESS-TIMESTAMP': timestamp_ms
}
```

## Complete Endpoint Inventory

### Portfolio (Account Management)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/portfolio/balance` | GET | Account balance |
| `/portfolio/positions` | GET | All positions (market + event level) |
| `/portfolio/fills` | GET | Trade fills history |
| `/portfolio/settlements` | GET | Settlement history |
| `/portfolio/summary/total_resting_order_value` | GET | Total value of resting orders |

### Subaccounts
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/portfolio/subaccounts` | POST | Create subaccount (max 32) |
| `/portfolio/subaccounts/transfer` | POST | Transfer between subaccounts |
| `/portfolio/subaccounts/balances` | GET | All subaccount balances |
| `/portfolio/subaccounts/transfers` | GET | Transfer history |
| `/portfolio/subaccounts/netting` | PUT/GET | Netting settings |

### Orders
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/portfolio/orders` | GET | List all orders |
| `/portfolio/orders` | POST | Create single order |
| `/portfolio/orders/{order_id}` | GET | Get order details |
| `/portfolio/orders/{order_id}` | DELETE | Cancel order |
| `/portfolio/orders/batched` | POST | Batch create (up to 20) or batch cancel |
| `/portfolio/orders/{order_id}/amend` | POST | Amend price/count |
| `/portfolio/orders/{order_id}/decrease` | POST | Decrease order size |
| `/portfolio/orders/queue_positions` | GET | Queue positions for multiple orders |
| `/portfolio/orders/{order_id}/queue_position` | GET | Single order queue position |

### Order Groups
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/portfolio/order_groups` | GET | List order groups |
| `/portfolio/order_groups/create` | POST | Create (with contracts_limit over 15s rolling window) |
| `/portfolio/order_groups/{id}` | GET/DELETE | Get or delete group |
| `/portfolio/order_groups/{id}/reset` | PUT | Reset group counters |
| `/portfolio/order_groups/{id}/trigger` | PUT | Manually trigger group |
| `/portfolio/order_groups/{id}/limit` | PUT | Update group limit |

### Markets
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/markets` | GET | List markets (filter by status, tickers, timestamps) |
| `/markets/{ticker}` | GET | Single market details |
| `/markets/{ticker}/orderbook` | GET | Orderbook (depth 0-100) |
| `/markets/trades` | GET | Recent trades |
| `/markets/candlesticks` | GET | Batch candlesticks (up to 100 tickers) |
| `/series/{series}/markets/{ticker}/candlesticks` | GET | Single market candlesticks |

### Events & Series
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/events` | GET | List events |
| `/events/{event_ticker}` | GET | Single event |
| `/events/{event_ticker}/metadata` | GET | Event metadata |
| `/events/multivariate` | GET | Multivariate events |
| `/series/{series_ticker}` | GET | Series details |
| `/series` | GET | List series (filter by category, tags) |

### Historical Data
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/historical/cutoff` | GET | Cutoff dates for partitioning |
| `/historical/markets` | GET | Historical market data |
| `/historical/markets/{ticker}` | GET | Single historical market |
| `/historical/markets/{ticker}/candlesticks` | GET | Historical candlesticks |
| `/historical/fills` | GET | Historical fills |
| `/historical/orders` | GET | Historical orders |

### Exchange
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/exchange/status` | GET | Exchange status |
| `/exchange/announcements` | GET | Announcements |
| `/exchange/schedule` | GET | Weekly schedule (open/close in ET) |
| `/exchange/user_data_timestamp` | GET | Last data update |
| `/series/fee_changes` | GET | Fee schedule changes |

### Communications (RFQ System)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/communications/rfqs` | GET/POST | List or create RFQs (max 100 open) |
| `/communications/rfqs/{id}` | GET/DELETE | Get or cancel RFQ |
| `/communications/quotes` | GET/POST | List or create quotes |
| `/communications/quotes/{id}` | GET/DELETE | Get or cancel quote |
| `/communications/quotes/{id}/accept` | PUT | Accept quote |
| `/communications/quotes/{id}/confirm` | PUT | Confirm accepted quote |

### Other
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/search/tags_by_categories` | GET | Market tags by category |
| `/search/filters_by_sport` | GET | Sport-specific filters |
| `/api_keys` | GET/POST/DELETE | Manage API keys |
| `/api_keys/generate` | POST | Generate new API key |
| `/account/limits` | GET | Account limits |
| `/incentive_programs` | GET | Active incentive programs |
| `/structured_targets` | GET | Structured targets |
| `/milestones` | GET | Platform milestones |

## Rate Limits
| Tier | Read Limit | Write Limit | Qualification |
|------|-----------|-------------|---------------|
| Basic | 20/sec | 10/sec | Complete signup |
| Advanced | 30/sec | 30/sec | Complete typeform application |
| Premier | 100/sec | 100/sec | 3.75% of exchange volume/month |
| Prime | 400/sec | 400/sec | 7.5% of exchange volume/month |

**Write-limited endpoints**: CreateOrder, CancelOrder, AmendOrder, DecreaseOrder, BatchCreateOrders (each item = 1 txn), BatchCancelOrders (each cancel = 0.2 txn)

---

# PHASE 3: TRADING MECHANICS & WEBSOCKET

## WebSocket API
- **Production**: `wss://api.elections.kalshi.com/trade-api/ws/v2`
- **Demo**: `wss://demo-api.kalshi.co/trade-api/ws/v2`

### Public Channels (No Auth Required)
| Channel | Data | Use Case |
|---------|------|----------|
| `ticker` | Real-time price updates | Price monitoring, signal generation |
| `trade` | Individual trades as they happen | Volume analysis, trade flow |
| `market_lifecycle_v2` | Market status changes | Market open/close/settlement tracking |
| `multivariate` | Multivariate event updates | Correlated market tracking |

### Private Channels (Auth Required)
| Channel | Data | Use Case |
|---------|------|----------|
| `orderbook_delta` | Orderbook changes | Market depth analysis, order flow |
| `fill` | Your trade executions | Order confirmation, position tracking |
| `market_positions` | Position changes | Portfolio monitoring |
| `communications` | RFQ/quote updates | Block trade monitoring |
| `order_group_updates` | Order group status | Group strategy tracking |

## Orderbook Structure
- Returns only **bids** (both YES bids and NO bids)
- YES BID at X¢ = implied NO ASK at (100-X)¢
- Depth parameter: 0-100 levels
- New format: `FixedPointDollars` (e.g., "0.5600") and `FixedPointCount` (e.g., "10.00")
- Legacy format: integer cents (being deprecated)

## Price Level Structure
- Markets have `price_ranges` array: `[{start, end, step}]`
- Defines valid price increments for orders
- Example: start=0.01, end=0.99, step=0.01 → penny increments

## New FixedPoint Format (Critical)
```
FixedPointDollars: "0.5600" (4 decimal places, string)
FixedPointCount:   "10.00"  (2 decimal places, string)
```
- All new fields use this format
- Legacy integer cent fields being deprecated
- Migration deadline: March 6, 2026

---

# PHASE 4: MARKET CATEGORIES & DATA HIERARCHY

## Data Hierarchy
```
Series (template for recurring events)
  └── Event (collection of related markets)
       └── Market (single binary contract with YES/NO)
```

### Series
- Recurring event templates (e.g., "Monthly CPI" series)
- Has `series_ticker` as identifier
- Filterable by category and tags

### Event
- Collection of markets for a specific occurrence
- Example: "January 2026 CPI Report" event might have:
  - "CPI > 3.0%" market
  - "CPI > 3.5%" market
  - "CPI between 2.5%–3.0%" market
- Has event-level exposure tracking

### Market Object (Key Fields)
```
ticker:                  Unique market identifier
event_ticker:            Parent event
market_type:             binary | scalar
status:                  initialized → inactive → active → closed → determined → finalized
yes_bid_dollars:         Best YES bid (FixedPointDollars)
yes_ask_dollars:         Best YES ask
no_bid_dollars:          Best NO bid
no_ask_dollars:          Best NO ask
last_price_dollars:      Last traded price
volume_fp:               Total volume (FixedPointCount)
open_interest_fp:        Open interest
strike_type:             greater | less | between | functional | custom | structured
floor_strike:            Lower bound (for ranged markets)
cap_strike:              Upper bound
rules_primary:           Primary resolution rules
rules_secondary:         Secondary resolution rules
can_close_early:         Whether market can close before scheduled
fractional_trading_enabled: Whether fractional contracts allowed
price_ranges:            Valid price levels [{start, end, step}]
```

## Candlestick Data
```
Periods: 1 min, 60 min, 1440 min (daily)
Fields per candle:
  - yes_bid: {open, high, low, close}
  - yes_ask: {open, high, low, close}
  - price:   {open, high, low, close, mean, previous}
  - volume_fp, open_interest_fp
  - end_period_ts (timestamp)
```

---

# PHASE 5: ORDER TYPES & RISK MANAGEMENT

## Order Creation (CreateOrderRequest)
```
Required:
  ticker:    Market ticker
  side:      "yes" | "no"
  action:    "buy" | "sell"
  count/count_fp:  Number of contracts
  type:      "limit" | "market"

Optional:
  yes_price/yes_price_dollars:  Price for YES side
  no_price/no_price_dollars:    Price for NO side
  client_order_id:              UUID for deduplication
  expiration_ts:                Order expiration timestamp
  time_in_force:                "fill_or_kill" | "good_till_canceled" | "immediate_or_cancel"
  buy_max_cost:                 Maximum total cost (safety limit)
  self_trade_prevention_type:   "taker_at_cross" | "maker"
  order_group_id:               Link to order group
  cancel_order_on_pause:        Cancel if market pauses
  subaccount:                   Subaccount number
```

## Order States
```
resting → (filled) → executed
resting → canceled
resting → (partially filled) → canceled
```

## Order Amendment
- Can change: ticker, side, action, count, price
- Generates `updated_client_order_id`
- Atomic operation (old order canceled, new order created)

## Order Groups (Advanced Risk Management)
- **contracts_limit**: Maximum contracts over a rolling 15-second window
- Auto-cancel mechanism when triggered
- Use case: Prevent runaway algorithms from exceeding position limits
- Can manually trigger, reset, or update limits

## Built-in Risk Controls
1. **buy_max_cost**: Hard ceiling on order cost
2. **time_in_force**: Control order lifetime
3. **self_trade_prevention**: Prevent crossing own orders
4. **cancel_order_on_pause**: Auto-cancel during market pauses
5. **Order Groups**: Rolling window contract limits
6. **Subaccounts**: Isolate strategies (max 32 subaccounts)
7. **Netting**: Cross-subaccount netting settings

## Position Tracking
```
MarketPosition:
  ticker
  position_fp:              Positive = YES, Negative = NO
  market_exposure_dollars:  Max possible loss
  realized_pnl_dollars:     Realized P&L
  fees_paid_dollars:        Total fees

EventPosition:
  event_ticker
  total_cost_dollars:       Total invested
  event_exposure_dollars:   Max possible loss across event
  realized_pnl_dollars:     Realized P&L
```

## Settlement
```
Settlement:
  ticker, event_ticker
  market_result:  "yes" | "no" | "scalar" | "void"
  yes_count_fp:   YES contracts held
  no_count_fp:    NO contracts held
  revenue:        Settlement payout
  fee_cost:       Settlement fees
```

---

# PHASE 6: COMPETITOR ANALYSIS

| Feature | Kalshi | Polymarket | PredictIt | Manifold | Metaculus |
|---------|--------|------------|-----------|----------|-----------|
| **Regulation** | CFTC DCM | Unregulated (offshore) | CFTC no-action letter | Play money | Reputation |
| **Currency** | USD | USDC (crypto) | USD (capped $850) | Mana (play money) | Points |
| **Real Money** | ✅ | ✅ (crypto) | ✅ (limited) | ❌ | ❌ |
| **API** | Full REST + WebSocket | REST + WS | Limited | REST | REST |
| **Fees** | $0.07–$1.75/contract | 2% winner fee | 10% profit + 5% withdrawal | Free | Free |
| **US Legal** | ✅ (mostly) | ❌ (US blocked) | ✅ (academic) | ✅ | ✅ |
| **Sports** | ✅ (89% revenue) | Limited | ❌ | ✅ | ❌ |
| **Blockchain** | ❌ | ✅ (Polygon) | ❌ | ❌ | ❌ |

### Key Differentiators
- **Kalshi**: Only fully CFTC-regulated real-money prediction market with comprehensive API
- **Polymarket**: Larger volume but crypto-only, no US access, less regulated
- **PredictIt**: Academic, $850 position limit, limited API, being wound down
- **Manifold/Metaculus**: Free but play-money/reputation only

---

# PHASE 7: AI TRADING STRATEGIES FOR PREDICTION MARKETS

## 7.1 Applicable Algorithmic Strategies

### Strategy 1: Probability Calibration Arbitrage
**Concept**: Use ML models to estimate true event probabilities and trade when market price diverges.
```
Signal: model_probability - market_price > threshold
Action: Buy YES if model says higher probability than market implies
        Buy NO if model says lower probability than market implies
Edge:   Profitable when model is better-calibrated than the crowd
```
**Models**: Logistic regression, XGBoost, neural nets trained on historical outcomes vs. market prices.

### Strategy 2: Cross-Market Arbitrage
**Concept**: Exploit pricing inconsistencies across related markets within the same event.
```
Example: Event has markets for GDP growth >2%, >2.5%, >3%
  - If P(>3%) > P(>2.5%), arbitrage exists
  - Within an event, probabilities must be monotonically ordered
  - Buy the underpriced, sell the overpriced
```

### Strategy 3: Market Making / Spread Capture
**Concept**: Place resting limit orders on both sides to capture the bid-ask spread.
```
YES BID at 45¢ + NO BID at 52¢ = 97¢ total cost for guaranteed $1 payout = 3¢ profit
Risk: Adverse selection — informed traders pick off your stale quotes
Mitigation: Dynamic spread adjustment based on volume, time-to-expiry, volatility
```

### Strategy 4: Mean Reversion
**Concept**: Prices in prediction markets tend to overreact to news, then revert.
```
Signal: |current_price - moving_average| > k * standard_deviation
Action: Buy when price drops below band, sell when rises above
Edge:   Works well in low-information markets with occasional news spikes
```

### Strategy 5: Event-Driven / News Sentiment Trading
**Concept**: Analyze news, social media, and data feeds to trade before the market fully prices information.
```
Pipeline:
  1. News feed ingestion (Twitter/X API, NewsAPI, RSS)
  2. NLP sentiment analysis (FinBERT, GPT-based classification)
  3. Entity-event matching (map news to specific Kalshi markets)
  4. Signal generation (sentiment score → trade direction)
  5. Execution (API order placement)
```

### Strategy 6: Pairs Trading (Correlated Markets)
**Concept**: Trade the spread between two correlated prediction markets.
```
Example: "Fed raises rates in March" vs "Fed raises rates in June"
  - Normally correlated (if March is unlikely, June inherits some probability)
  - When correlation breaks, trade the spread
```

### Strategy 7: Time Decay / Theta Harvesting
**Concept**: Binary contracts have time-value characteristics similar to options.
```
As expiry approaches:
  - High-probability markets (>80¢) appreciate toward $1.00
  - Low-probability markets (<20¢) depreciate toward $0
  - Mid-range markets (40¢-60¢) have highest time-value uncertainty
Strategy: Sell far-from-money contracts as expiry approaches
```

### Strategy 8: Portfolio Hedging
**Concept**: Use prediction markets to hedge real-world risks.
```
Example: You're long stocks → Buy YES on "Recession in 2026" as hedge
Example: You're exposed to energy sector → Buy YES on "Oil above $90"
```

## 7.2 Kelly Criterion for Position Sizing

### Binary Market Formula
```
f* = p - (1-p) / b

Where:
  f* = fraction of bankroll to wager
  p  = estimated true probability of YES
  b  = payout odds ratio = (1 - market_price) / market_price

Example:
  Market price = 40¢ (YES)
  Your estimated probability = 55%
  b = 0.60 / 0.40 = 1.5
  f* = 0.55 - 0.45/1.5 = 0.55 - 0.30 = 0.25 (25% of bankroll)
```

### Fractional Kelly (Recommended)
```
Use half-Kelly (f*/2) or quarter-Kelly (f*/4) in practice:
  - Reduces variance and drawdown significantly
  - More robust to probability estimation errors
  - Half-Kelly achieves ~75% of full-Kelly growth with ~50% of variance
```

### Multi-Market Kelly
```
For N simultaneous positions across independent markets:
  Total allocation = Σ(f_i) for i=1..N
  If total > 1.0, scale all positions proportionally
  Consider correlation between markets (not independent in practice)
```

## 7.3 Stop-Loss for Binary Contracts

Binary contracts have **naturally bounded loss** (max loss = purchase price), but stop-losses are still valuable:

### Price-Based Stop-Loss
```
if position == YES and current_price < entry_price - stop_threshold:
    sell_position()  # Cut losses early

Example: Bought YES at 60¢, stop at 45¢ → max loss = 15¢ instead of 60¢
```

### Time-Based Stop-Loss
```
if time_to_expiry < threshold and profit_target_not_met:
    close_position()  # Don't hold losing positions to expiry
```

### Portfolio-Level Stop-Loss
```
if portfolio_drawdown > max_drawdown_percent:
    cancel_all_orders()
    close_all_positions()  # Emergency shutdown
```

### Dynamic Stop-Loss (Trailing)
```
trailing_stop = max_price_since_entry - trail_amount
if current_price < trailing_stop:
    sell_position()
```

## 7.4 Hedging Strategies for Correlated Binary Contracts

### Strategy A: Same-Event Hedging
```
Event: "January CPI Report"
Markets: CPI>2.5% (at 70¢), CPI>3.0% (at 40¢), CPI>3.5% (at 15¢)

Hedge: Buy YES on CPI>3.0% at 40¢, Buy NO on CPI>2.5% at 30¢
  - If CPI is 2.0%: Lose 40¢ on first, Win 70¢ on second = +30¢
  - If CPI is 2.8%: Lose 40¢ on first, Lose 30¢ on second = -70¢
  - If CPI is 3.2%: Win 60¢ on first, Lose 30¢ on second = +30¢
```

### Strategy B: Cross-Event Hedging
```
Trade correlated events:
  - YES on "Recession in 2026" + YES on "Fed cuts rates >3 times"
  - These are positively correlated; structure for asymmetric payoff
```

### Strategy C: Delta-Neutral Portfolios
```
For a portfolio of N binary contracts:
  Delta = Σ(position_i × sensitivity_i_to_underlying_factor)
  Adjust positions to keep Delta ≈ 0
```

## 7.5 AI/ML Model Architecture

### Recommended Pipeline
```
┌─────────────────┐     ┌──────────────────┐     ┌────────────────┐
│  Data Ingestion  │────▶│  Feature Engine   │────▶│  ML Models     │
│                  │     │                  │     │                │
│ • Kalshi API     │     │ • Price features │     │ • XGBoost      │
│ • News feeds     │     │ • Volume/OI      │     │ • LSTM/GRU     │
│ • Economic data  │     │ • Sentiment      │     │ • Transformer  │
│ • Social media   │     │ • Calendar       │     │ • Ensemble     │
│ • Historical     │     │ • Cross-market   │     │                │
└─────────────────┘     └──────────────────┘     └───────┬────────┘
                                                          │
                              ┌────────────────────────────┘
                              ▼
                    ┌──────────────────┐     ┌────────────────┐
                    │  Signal Engine    │────▶│  Execution     │
                    │                  │     │                │
                    │ • Kelly sizing   │     │ • Order mgmt   │
                    │ • Risk checks    │     │ • Rate limiting│
                    │ • Stop-loss      │     │ • Kalshi API   │
                    │ • Portfolio opt   │     │ • WebSocket    │
                    └──────────────────┘     └────────────────┘
```

### Feature Categories
1. **Price Features**: Moving averages, RSI, Bollinger Bands, price velocity
2. **Volume Features**: Volume spikes, OI changes, trade count
3. **Sentiment Features**: News sentiment (FinBERT), social media sentiment
4. **Calendar Features**: Time to expiry, day of week, market schedule
5. **Cross-Market Features**: Correlation with related markets, event-level features
6. **External Data**: Economic indicators, odds from other platforms

---

# PHASE 8: DASHBOARD & UX DESIGN

## 8.1 Dashboard Layout (Modular Panel System)

### Main Dashboard Panels
```
┌─────────────────────────────────────────────────────────┐
│                    TOP NAV BAR                           │
│  Logo │ Markets │ Portfolio │ AI │ Settings │ Balance    │
├──────────────┬──────────────────────────────────────────┤
│  WATCHLIST   │         MAIN CHART AREA                  │
│              │  ┌──────────────────────────────────┐    │
│ ▸ Sports     │  │  Candlestick / Line Chart        │    │
│ ▸ Politics   │  │  with Volume overlay              │    │
│ ▸ Economics  │  │  Indicators: MA, BB, RSI          │    │
│ ▸ Weather    │  └──────────────────────────────────┘    │
│              │                                          │
│  Search...   │  ┌─────────────┬────────────────────┐    │
│              │  │ ORDER BOOK  │  TRADE HISTORY      │    │
│ Favorites ★  │  │ YES │ NO   │  Time│Price│Size    │    │
│              │  │ 65¢ │ 20   │  12:01│0.65│10      │    │
│              │  │ 64¢ │ 35   │  12:00│0.64│25      │    │
│              │  │ 63¢ │ 50   │  11:59│0.65│5       │    │
│              │  └─────────────┴────────────────────┘    │
├──────────────┴──────────────────────────────────────────┤
│                    BOTTOM PANELS (Tabbed)                │
│  [Positions] [Orders] [Fills] [P&L] [AI Signals]        │
│                                                         │
│  Ticker │ Side │ Qty │ Entry │ Current │ P&L │ Actions  │
│  BTC-Y  │ YES  │ 50  │ 0.65  │ 0.72    │ +$3.50 │ ✕   │
│  CPI-N  │ NO   │ 30  │ 0.40  │ 0.35    │ -$1.50 │ ✕   │
└─────────────────────────────────────────────────────────┘
```

## 8.2 Key Dashboard Pages

### 1. Market Explorer
- Category tree navigation (Series → Events → Markets)
- Real-time price ticker
- Heatmap view of markets by category
- Sorting: by volume, by price change, by time to expiry
- Advanced filters: status, category, min/max price, volume threshold

### 2. Trading View
- Full candlestick chart with technical indicators
- Depth chart (orderbook visualization)
- One-click order panel (Buy YES / Buy NO)
- Order ticket with: price, quantity, type, TIF, max cost
- Real-time P&L for current position

### 3. Portfolio Dashboard
- **Summary Cards**: Total Balance, Total Exposure, Day P&L, Open Orders
- **Positions Table**: All open positions with real-time P&L
- **Event Grouping**: Group positions by event for hedging visibility
- **Pie Chart**: Allocation by category
- **Equity Curve**: Historical account value over time

### 4. AI Control Panel
- **Strategy Selector**: Enable/disable individual strategies
- **Parameter Tuning**: Sliders/inputs for each strategy's parameters
  - Kelly fraction (0.1–1.0)
  - Stop-loss threshold (% or absolute)
  - Max position size per market
  - Max total exposure
  - Min edge threshold (how much model probability must differ from market)
  - Rebalance frequency
- **Signal Monitor**: Live feed of AI-generated signals with confidence scores
- **Backtest Runner**: Select strategy + date range → view historical performance
- **Kill Switch**: Emergency stop-all button

### 5. Risk Management Panel
- **Exposure Heatmap**: By category, by event, by market
- **Drawdown Monitor**: Current vs. max allowed drawdown
- **Correlation Matrix**: Between active positions
- **Stop-Loss Status**: Active stops with trigger levels
- **Order Group Monitor**: Remaining capacity in order groups

### 6. Analytics & Reporting
- **Performance Metrics**: Sharpe ratio, win rate, avg P&L per trade, max drawdown
- **Trade Journal**: Annotated history of all trades
- **Strategy Attribution**: P&L breakdown by strategy
- **Fee Analysis**: Total fees paid, fee-adjusted returns

## 8.3 Real-Time Components
- WebSocket-powered live price updates
- Toast notifications for fills, settlements, alerts
- Audio alerts for significant events
- System status indicator (exchange open/closed/maintenance)

## 8.4 User-Configurable Logic (Key Requirement)
The dashboard MUST allow users to:
1. **Define custom rules**: "If price of X drops below Y, buy Z contracts"
2. **Set stop-losses**: Per-position and portfolio-level
3. **Set take-profits**: Auto-sell when target reached
4. **Create alerts**: Price, volume, sentiment thresholds
5. **Adjust AI parameters**: Without code changes
6. **Enable/disable strategies**: Per-market or globally
7. **Set risk limits**: Max position, max exposure, max daily loss

---

# PHASE 9: TECH STACK & ARCHITECTURE

## 9.1 Recommended Tech Stack

### Frontend
| Layer | Technology | Reason |
|-------|-----------|--------|
| Framework | **Next.js 14+ (App Router)** | SSR, API routes, great DX |
| UI Library | **shadcn/ui + Tailwind CSS** | Customizable, modern, fast |
| Charts | **Lightweight Charts (TradingView)** | Professional trading charts, free |
| State | **Zustand + React Query** | Lightweight global state + server state |
| Real-time | **Native WebSocket** | Direct Kalshi WS connection |
| Forms | **React Hook Form + Zod** | Type-safe validation |
| Tables | **TanStack Table** | Virtualized, sortable, filterable |
| Auth | **NextAuth.js** | Session management |

### Backend
| Layer | Technology | Reason |
|-------|-----------|--------|
| Runtime | **Python (FastAPI)** | Best ML/AI ecosystem, async support |
| API Framework | **FastAPI** | Async, auto-docs, type hints |
| Task Queue | **Celery + Redis** | Background jobs (backtesting, signals) |
| WebSocket | **websockets** library | Kalshi WS connection |
| Scheduler | **APScheduler** | Cron-like scheduling for strategies |
| HTTP Client | **httpx** (async) | API calls to Kalshi |

### AI/ML
| Layer | Technology | Reason |
|-------|-----------|--------|
| ML Framework | **scikit-learn + XGBoost** | Tabular prediction models |
| Deep Learning | **PyTorch** | LSTM/Transformer models |
| NLP | **transformers (HuggingFace)** | Sentiment analysis (FinBERT) |
| Feature Store | **pandas + Redis** | Real-time feature computation |
| Backtesting | **Custom engine** | Prediction market specific |
| Experiment Tracking | **MLflow** | Model versioning and comparison |

### Data & Infrastructure
| Layer | Technology | Reason |
|-------|-----------|--------|
| Primary DB | **PostgreSQL** | Relational data, JSONB for flexibility |
| Time-series | **TimescaleDB** (PG extension) | Candlestick, price, volume data |
| Cache | **Redis** | Real-time data, session cache, pub/sub |
| Message Queue | **Redis Streams** | Event-driven architecture |
| Containerization | **Docker + Docker Compose** | Local dev and deployment |
| Deployment | **Railway / Fly.io / AWS** | Scalable hosting |
| Monitoring | **Prometheus + Grafana** | System & trading metrics |

## 9.2 System Architecture

```
                    ┌──────────────────────────┐
                    │      Next.js Frontend     │
                    │   (Dashboard, Charts, UI) │
                    └──────────┬───────────────┘
                               │ REST + WebSocket
                    ┌──────────▼───────────────┐
                    │     FastAPI Backend        │
                    │  ┌─────────────────────┐  │
                    │  │   API Gateway        │  │
                    │  │   (Auth, Rate Limit) │  │
                    │  └────────┬────────────┘  │
                    │           │                │
                    │  ┌────────▼────────────┐  │
                    │  │  Service Layer       │  │
                    │  │  • Order Service     │  │
                    │  │  • Market Service    │  │
                    │  │  • Portfolio Service │  │
                    │  │  • Strategy Service  │  │
                    │  │  • Risk Service      │  │
                    │  └────────┬────────────┘  │
                    └──────────┬───────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────▼──────┐ ┌──────▼──────┐ ┌───────▼──────┐
    │   PostgreSQL   │ │    Redis     │ │ Celery Workers│
    │  + TimescaleDB │ │  (Cache/MQ)  │ │ (AI/Backtest)│
    └────────────────┘ └─────────────┘ └──────┬───────┘
                                               │
                               ┌───────────────┘
                    ┌──────────▼───────────────┐
                    │    Kalshi API Client      │
                    │  ┌──────────────────────┐│
                    │  │ REST Client (httpx)   ││
                    │  │ WebSocket Client      ││
                    │  │ Auth (RSA-PSS)        ││
                    │  │ Rate Limiter          ││
                    │  └──────────────────────┘│
                    └──────────┬───────────────┘
                               │
                    ┌──────────▼───────────────┐
                    │    Kalshi Exchange        │
                    │  REST + WebSocket APIs    │
                    └──────────────────────────┘
```

## 9.3 Key Modules

### Module 1: Kalshi API Client (`kalshi_client/`)
```
kalshi_client/
├── auth.py              # RSA-PSS signing, key management
├── rest_client.py       # Async HTTP client for all REST endpoints
├── ws_client.py         # WebSocket connection + channel subscriptions
├── rate_limiter.py      # Token bucket rate limiter (per-tier)
├── models.py            # Pydantic models matching OpenAPI schemas
└── exceptions.py        # Custom exceptions for API errors
```

### Module 2: Trading Engine (`trading/`)
```
trading/
├── order_manager.py     # Create, cancel, amend orders
├── position_tracker.py  # Real-time position tracking
├── portfolio.py         # Portfolio-level aggregation
├── risk_manager.py      # Stop-loss, max exposure, drawdown checks
├── execution.py         # Smart order routing, slippage control
└── order_groups.py      # Order group management
```

### Module 3: AI Strategies (`strategies/`)
```
strategies/
├── base_strategy.py     # Abstract strategy interface
├── calibration.py       # Probability calibration strategy
├── market_maker.py      # Spread capture strategy
├── mean_reversion.py    # Mean reversion strategy
├── sentiment.py         # NLP-driven sentiment strategy
├── arbitrage.py         # Cross-market arbitrage
├── kelly.py             # Kelly criterion position sizing
├── backtest_engine.py   # Historical backtesting
└── signal_aggregator.py # Combine signals from multiple strategies
```

### Module 4: Data Pipeline (`data/`)
```
data/
├── market_data.py       # Fetch & store market data
├── candlestick_store.py # TimescaleDB candlestick storage
├── news_ingestion.py    # News feed processing
├── feature_engine.py    # Feature computation pipeline
├── historical_sync.py   # Historical data backfill
└── realtime_feed.py     # WebSocket data processing
```

### Module 5: Dashboard API (`api/`)
```
api/
├── routes/
│   ├── markets.py       # Market data endpoints
│   ├── orders.py        # Order management endpoints
│   ├── portfolio.py     # Portfolio endpoints
│   ├── strategies.py    # Strategy config endpoints
│   ├── backtest.py      # Backtesting endpoints
│   └── risk.py          # Risk management endpoints
├── websocket.py         # WS endpoint for dashboard
└── middleware.py         # Auth, CORS, rate limiting
```

## 9.4 Database Schema (Core Tables)

```sql
-- Markets cache (synced from Kalshi)
CREATE TABLE markets (
    ticker VARCHAR PRIMARY KEY,
    event_ticker VARCHAR NOT NULL,
    series_ticker VARCHAR,
    status VARCHAR NOT NULL,
    market_type VARCHAR DEFAULT 'binary',
    yes_bid DECIMAL(10,4),
    yes_ask DECIMAL(10,4),
    last_price DECIMAL(10,4),
    volume DECIMAL(15,2),
    open_interest DECIMAL(15,2),
    rules_primary TEXT,
    close_time TIMESTAMPTZ,
    expiration_time TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Candlestick data (TimescaleDB hypertable)
CREATE TABLE candlesticks (
    ticker VARCHAR NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    period_minutes INT NOT NULL,
    yes_bid_open DECIMAL(10,4),
    yes_bid_high DECIMAL(10,4),
    yes_bid_low DECIMAL(10,4),
    yes_bid_close DECIMAL(10,4),
    yes_ask_open DECIMAL(10,4),
    yes_ask_high DECIMAL(10,4),
    yes_ask_low DECIMAL(10,4),
    yes_ask_close DECIMAL(10,4),
    volume DECIMAL(15,2),
    open_interest DECIMAL(15,2),
    PRIMARY KEY (ticker, period_end, period_minutes)
);
SELECT create_hypertable('candlesticks', 'period_end');

-- Orders (our records)
CREATE TABLE orders (
    order_id VARCHAR PRIMARY KEY,
    client_order_id UUID UNIQUE,
    ticker VARCHAR NOT NULL,
    side VARCHAR NOT NULL,        -- yes/no
    action VARCHAR NOT NULL,      -- buy/sell
    type VARCHAR NOT NULL,        -- limit/market
    status VARCHAR NOT NULL,
    price DECIMAL(10,4),
    count DECIMAL(15,2),
    filled_count DECIMAL(15,2) DEFAULT 0,
    taker_fees DECIMAL(10,4) DEFAULT 0,
    strategy_id VARCHAR,          -- which AI strategy placed this
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Positions (real-time)
CREATE TABLE positions (
    ticker VARCHAR PRIMARY KEY,
    side VARCHAR NOT NULL,        -- yes/no
    quantity DECIMAL(15,2),
    avg_entry_price DECIMAL(10,4),
    current_price DECIMAL(10,4),
    unrealized_pnl DECIMAL(10,4),
    realized_pnl DECIMAL(10,4),
    fees_paid DECIMAL(10,4),
    strategy_id VARCHAR,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Strategy configurations
CREATE TABLE strategies (
    id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    type VARCHAR NOT NULL,        -- calibration/market_maker/etc.
    enabled BOOLEAN DEFAULT FALSE,
    parameters JSONB NOT NULL,    -- strategy-specific params
    risk_limits JSONB NOT NULL,   -- max_position, stop_loss, etc.
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- AI signals
CREATE TABLE signals (
    id SERIAL PRIMARY KEY,
    strategy_id VARCHAR NOT NULL,
    ticker VARCHAR NOT NULL,
    signal_type VARCHAR NOT NULL,  -- buy/sell/hold
    confidence DECIMAL(5,4),       -- 0.0000 to 1.0000
    model_probability DECIMAL(5,4),
    market_price DECIMAL(10,4),
    kelly_fraction DECIMAL(5,4),
    executed BOOLEAN DEFAULT FALSE,
    order_id VARCHAR,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Trade journal
CREATE TABLE trade_journal (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR NOT NULL,
    ticker VARCHAR NOT NULL,
    strategy_id VARCHAR,
    entry_price DECIMAL(10,4),
    exit_price DECIMAL(10,4),
    quantity DECIMAL(15,2),
    pnl DECIMAL(10,4),
    fees DECIMAL(10,4),
    notes TEXT,
    entry_time TIMESTAMPTZ,
    exit_time TIMESTAMPTZ
);
```

---

# PHASE 10: LEGAL, COMPLIANCE & OPERATIONAL CONCERNS

## 10.1 Regulatory Framework

### CFTC Regulation
- Kalshi is a **Designated Contract Market (DCM)** under CFTC oversight
- Contracts are classified as **event contracts** (binary options on real-world events)
- CFTC Rule 40.11 allows the CFTC to review and potentially block event contracts
- Kalshi successfully sued the CFTC in 2024 to offer election contracts

### State-Level Restrictions
| State | Status | Details |
|-------|--------|---------|
| **Massachusetts** | ❌ BLOCKED | AG sued Kalshi (Sept 2025); preliminary injunction Jan 2026 for sports |
| Other states | ✅ Available | Generally available across US |
| International | ✅ Available | Expanded to 140+ countries (Oct 2025) |

### Automated Trading on Kalshi
- **Explicitly supported** via API keys and documented REST/WebSocket APIs
- Rate limit tiers specifically designed for algorithmic traders
- Premier/Prime tiers require "technical competency" verification:
  - Knowledge of security practices
  - API usage monitoring capability
  - Rate limiting implementation
  - Legal/compliance awareness
- Demo environment available for testing without real funds

## 10.2 Key Legal Considerations for Our Platform

### As API Users (Trading Bot)
1. **API Terms of Service**: Must comply with Kalshi's API usage terms
2. **Rate Limits**: Must implement proper rate limiting (Basic: 20 read/10 write per sec)
3. **Self-Trade Prevention**: Must configure properly to avoid crossing own orders
4. **No Market Manipulation**: Wash trading, spoofing, layering are prohibited
5. **Insider Trading**: Kalshi actively enforces (see MrBeast editor case Feb 2026)
6. **Geofencing**: Must respect state restrictions (Massachusetts)

### As a Clone Platform
1. **CFTC Registration**: Would need DCM designation to operate real-money prediction markets in US
2. **State Gambling Laws**: Sports betting is state-regulated; varies by jurisdiction
3. **Money Transmission**: May need money transmitter licenses
4. **KYC/AML**: Must implement Know Your Customer and Anti-Money Laundering compliance
5. **Data Privacy**: Must comply with state privacy laws (CCPA, etc.)

### Disclaimers Needed
- Not financial advice
- Past performance doesn't guarantee future results
- Users can lose their entire investment
- Automated trading carries additional risks
- Not available in all jurisdictions

## 10.3 Risk Disclosures
- Binary contracts have **bounded loss** (max loss = purchase price)
- But portfolio-level losses can compound
- Automated systems can malfunction and place erroneous trades
- API outages can prevent order management
- Market liquidity can dry up, making exits difficult
- Settlement disputes (see Kalshi NFL payout controversy, Jan 2026)

## 10.4 Operational Risk Mitigation
1. **Kill Switch**: Mandatory emergency stop that cancels all orders + closes positions
2. **Max Loss Circuit Breaker**: Auto-shutdown at daily/weekly loss threshold
3. **Order Validation**: Pre-flight checks on all orders (price sanity, size limits)
4. **Heartbeat Monitor**: Alert if system loses API/WS connection
5. **Audit Trail**: Log every order, signal, and decision for compliance
6. **Separate Demo Testing**: Always test strategies in demo before production
7. **Gradual Deployment**: Start with small positions, scale up as confidence grows

## 10.5 Demo Environment
- URL: `https://demo.kalshi.co/`
- API: `https://demo-api.kalshi.co/trade-api/v2`
- Credentials NOT shared with production
- Mock funds for testing
- Full API surface available
- **Must use for all development and backtesting**

---

# SUMMARY: BUILD PLAN

## Phase Summary
| Phase | Topic | Key Takeaway |
|-------|-------|-------------|
| 1 | Platform Overview | CFTC-regulated, $11B valuation, binary event contracts |
| 2 | API Documentation | 60+ REST endpoints, RSA-PSS auth, FixedPoint format |
| 3 | Trading & WebSocket | Real-time WS channels, orderbook structure |
| 4 | Market Structure | Series → Events → Markets hierarchy |
| 5 | Orders & Risk | Limit/market orders, order groups, buy_max_cost |
| 6 | Competitors | Kalshi is only fully regulated real-money API platform |
| 7 | AI Strategies | 8 strategies, Kelly criterion, stop-loss, hedging |
| 8 | Dashboard & UX | 6 dashboard pages, user-configurable logic |
| 9 | Tech Stack | Next.js + FastAPI + PostgreSQL + Redis + ML pipeline |
| 10 | Legal & Compliance | CFTC rules, state restrictions, risk mitigation |

## Recommended Build Order
```
Sprint 1: Foundation (Week 1-2)
  ├── Kalshi API Client (auth, REST, WebSocket)
  ├── Database setup (PostgreSQL + TimescaleDB)
  ├── Data ingestion pipeline
  └── Basic market data display

Sprint 2: Trading Core (Week 3-4)
  ├── Order management system
  ├── Position tracking
  ├── Portfolio aggregation
  └── Risk management framework

Sprint 3: Dashboard MVP (Week 5-6)
  ├── Next.js setup with shadcn/ui
  ├── Market explorer page
  ├── Trading view with charts
  ├── Portfolio dashboard
  └── Order management UI

Sprint 4: AI Engine (Week 7-8)
  ├── Feature engineering pipeline
  ├── Probability calibration model
  ├── Kelly criterion position sizing
  ├── Signal generation system
  └── Backtest engine

Sprint 5: Advanced Features (Week 9-10)
  ├── Multiple strategy support
  ├── User-configurable rules engine
  ├── Alert system
  ├── Stop-loss/take-profit automation
  └── AI control panel in dashboard

Sprint 6: Polish & Deploy (Week 11-12)
  ├── Performance optimization
  ├── Error handling & monitoring
  ├── Security hardening
  ├── Documentation
  └── Production deployment
```

---

*Original research completed. System built and deployed.*

---
---
---

# 🧠 JA HEDGE — 10-PHASE IMPROVEMENT PLAN
## From "It Works" to "It Prints Money 24/7"
### Research Date: March 2026 | Post-Deployment Audit

---

## EXECUTIVE SUMMARY: WHY IT'S NOT GOOD YET

We ran a brutal 16-file audit of the entire AI pipeline after deploying to Railway. Frankenstein is alive — 100 markets cached, 12 signals generated, 6 trades executed. But *alive* and *profitable* are two very different things.

### The Ugly Truth (8 Critical Weakness Categories)

| # | Category | Severity | One-Line Summary |
|---|----------|----------|-----------------|
| 1 | **No Sell/Exit** | 🔴 CRITICAL | System can only BUY — capital is locked until settlement |
| 2 | **XGBoost Never Trained** | 🔴 CRITICAL | ML model never gets enough data, runs 100% on heuristic fallback |
| 3 | **Wrong Training Label** | 🔴 CRITICAL | Learning "was I right?" instead of "what's the probability?" |
| 4 | **Kelly Criterion Broken** | 🔴 CRITICAL | Conflates confidence with payout ratio — incorrect position sizing |
| 5 | **Stop-Loss is Dead Code** | 🔴 CRITICAL | Detection-only — never actually executes exit orders |
| 6 | **Paper Trader Unrealistic** | 🟠 HIGH | Instant fills at quoted price — no spread, no slippage, no partial fills |
| 7 | **No External Data** | 🟠 HIGH | Trading blind — no news, no polls, no social sentiment, no other markets |
| 8 | **Look-Ahead Bias** | 🟠 HIGH | Train/val split is backwards in time — model "sees the future" |
| 9 | **All State In-Memory** | 🟠 HIGH | 30-min save interval, everything lost on crash |
| 10 | **Heuristic = Mean Reversion** | 🟡 MEDIUM | Applying stock market logic to prediction markets where prices converge to 0/100 |

### What Kalshi API Actually Supports (That We're Not Using)

From the full OpenAPI v3.10.0 spec audit:

| Capability | API Endpoint | We Use It? |
|-----------|-------------|-----------|
| **SELL orders** | `POST /portfolio/orders` with `action: "sell"` | ❌ NO |
| **Order amend** (reprice) | `POST /portfolio/orders/{id}/amend` | ❌ NO |
| **Order cancel** | `DELETE /portfolio/orders/{id}` | ❌ NO |
| **Batch orders** (up to 20) | `POST /portfolio/orders/batched` | ❌ NO |
| **Batch cancel** | `DELETE /portfolio/orders/batched` | ❌ NO |
| **Order decrease** | `POST /portfolio/orders/{id}/decrease` | ❌ NO |
| **Order groups** (risk limits) | `/portfolio/order_groups/*` | ❌ NO |
| **Queue position** | `/portfolio/orders/{id}/queue_position` | ❌ NO |
| **WebSocket ticker** (real-time prices) | `ws: ticker` channel | ❌ NO |
| **WebSocket orderbook** | `ws: orderbook_delta` channel | ❌ NO |
| **WebSocket trades** | `ws: trade` channel | ❌ NO |
| **WebSocket fills** | `ws: fill` channel (private) | ❌ NO |
| **1-min candlesticks** | `/series/{s}/markets/{t}/candlesticks?period=1` | ❌ NO |
| **Batch candlesticks** (100 markets) | `/markets/candlesticks` | ❌ NO |
| **Orderbook depth** | `/markets/{ticker}/orderbook?depth=N` | ❌ NO |
| **Fill history** | `/portfolio/fills` | ❌ NO |
| **Settlement history** | `/portfolio/settlements` | ❌ NO |
| **Exchange schedule** | `/exchange/schedule` | ❌ NO |
| **Exchange status** | `/exchange/status` | ❌ NO |
| **Events with nested markets** | `/events?with_nested_markets=true` | ❌ NO |
| **Historical data** | `/historical/markets`, `/historical/fills` | ❌ NO |
| **Structured targets** | `/structured_targets` | ❌ NO |
| **Self-trade prevention** | `self_trade_prevention_type` field | ❌ NO |
| **Fill-or-kill / IOC orders** | `time_in_force` field | ❌ NO |
| **Post-only orders** | `post_only` field | ❌ NO |
| **Reduce-only orders** | `reduce_only` field | ❌ NO |
| **Client order ID** (dedup) | `client_order_id` field | Partial |
| **Cancel on pause** | `cancel_order_on_pause` field | ❌ NO |
| **Market metadata** | `/events/{ticker}/metadata` | ❌ NO |
| **Forecast percentiles** | `/forecast_percentile_history` | ❌ NO |
| **Incentive programs** | `/incentive_programs` (liquidity rewards!) | ❌ NO |
| **RFQ system** (block trades) | `/communications/rfqs` | ❌ NO |

**We are using ~10% of the API.** The other 90% is the difference between a toy and a weapon.

---

## THE 10 PHASES

---

# PHASE 1: STOP THE BLEEDING — Fix Critical Math & Logic Bugs
### Priority: 🔴 IMMEDIATE | Complexity: Medium | Timeline: 2-3 days

**Why First**: Everything else builds on correct math. If Kelly sizing is wrong, if we can't sell, if the model label is wrong — adding more features just makes a broken system trade faster.

### 1A. Fix Kelly Criterion (Incorrect Formula)

**Current (WRONG)**:
```python
# backend/app/frankenstein/strategy.py
kelly_fraction = (confidence * (1/price) - (1-confidence)) / (1/price)
```
This conflates `confidence` with true probability and `1/price` with odds. It's mathematically meaningless for binary contracts.

**Correct Formula for Binary Prediction Markets**:
For a YES contract at price `c` (in dollars, 0 to 1) where our estimated true probability is `p`:
$$f^* = \frac{p - c}{1 - c}$$

If $f^* < 0$, we should BUY NO (or sell YES). If $f^* > 0$, we buy YES. The magnitude tells us what fraction of bankroll to wager.

For a NO contract at price `(1-c)`:
$$f^*_{no} = \frac{(1-p) - (1-c)}{c} = \frac{c - p}{c}$$

**Edge cases**:
- Apply half-Kelly ($f^*/2$) for safety — full Kelly is theoretically optimal but has massive variance
- Minimum edge threshold: only trade when $|p - c| > 0.05$ (5¢ edge minimum)
- Maximum position: cap at 5% of bankroll per market regardless of Kelly output
- Never let Kelly output exceed 25% (even half-Kelly can suggest absurd sizes with high confidence)

### 1B. Fix Training Labels (Wrong Learning Target)

**Current (WRONG)**:
```python
# Learning: "did my trade make money?" → binary 0/1
label = 1 if trade_was_profitable else 0
```

This teaches the model to predict its own profitability, not the actual probability of an event. It's circular — and biased toward the model's existing behavior (selection bias: we only have labels for trades we took).

**Correct Approach**: Probability calibration target
```
label = settlement_outcome  # 0.0 or 1.0 (did YES actually happen?)
features = [market features at time of prediction]
target = P(YES settles) — the true probability
```

Use Kalshi's settlement history (`GET /portfolio/settlements` → `market_result: "yes"|"no"`) as ground truth. For every market we *observe* (not just trade), record the features and eventual outcome.

**Calibration validation**: After training, bin predictions into deciles (0-10%, 10-20%, etc.). In a calibrated model, events predicted at 30% should resolve YES ~30% of the time. Plot a reliability diagram.

### 1C. Fix Train/Val Split (Look-Ahead Bias)

**Current (WRONG)**: Random or reversed time split — future data leaks into training.

**Correct**: Walk-forward validation (temporal cross-validation):
```
Training: [day 1 ... day N]
Validation: [day N+1 ... day N+K]
Then slide forward:
Training: [day 1 ... day N+K]
Validation: [day N+K+1 ... day N+2K]
```

Never train on data that is chronologically after validation data. This is non-negotiable for time series.

### 1D. Fix Heuristic Predictor (Stop Mean-Reverting)

**Current (WRONG)**: If price > 0.5, predict lower (short). If price < 0.5, predict higher (long).

This is textbook stock-market mean reversion applied to prediction markets. **Prediction markets are fundamentally different**: prices converge toward 0 or 100 as expiration approaches (because the event either happens or doesn't). A contract at 80¢ going to 95¢ is *normal convergence*, not an anomaly.

**Replace with**:
1. **Momentum near expiration**: As expiry approaches, lean with the trend (convergence to settlement)
2. **Contrarian far from expiration**: Mean reversion only makes sense far from settlement with high volume
3. **Spread-aware**: Only predict opportunities where bid-ask spread < expected edge
4. **Volume-weighted**: Ignore thin markets where heuristics are meaningless

### Phase 1 Deliverables:
- [ ] Correct Kelly formula with half-Kelly default
- [ ] Settlement-based training labels
- [ ] Walk-forward temporal validation
- [ ] Time-to-expiry-aware heuristic
- [ ] Unit tests for all four fixes

---

# PHASE 2: LEARN TO SELL — Full Order Lifecycle Management
### Priority: 🔴 CRITICAL | Complexity: High | Timeline: 3-4 days

**Why Second**: Without sell capability, we're playing poker where we can only call, never fold. Capital is trapped until settlement. This single missing feature is the #1 reason the system can't be profitable.

### 2A. Sell/Exit Orders

Kalshi API `CreateOrder` supports:
```json
{
  "ticker": "KXBTC-25MAR10-T100000",
  "action": "sell",        // ← THE KEY: we've only ever sent "buy"
  "side": "yes",           // sell YES contracts we hold
  "type": "limit",
  "yes_price_dollars": "0.7500",
  "count_fp": "5.00",
  "client_order_id": "uuid-for-idempotency"
}
```

**Selling mechanics in binary markets**:
- Selling YES at 75¢ = Buying NO at 25¢ (the exchange handles this netting)
- You can sell contracts you own (closing position)
- You can "short sell" — sell YES you don't own (opens a NO position, costs `1 - yes_price`)
- `reduce_only: true` ensures you only reduce, never accidentally flip

**Required changes**:
1. `ExecutionEngine.execute_sell()` — new method, mirrors `execute_buy()` with `action: "sell"`
2. `PaperTradingSimulator.simulate_sell()` — close or reduce positions
3. Position tracking: track `net_position` per ticker (positive = long YES, negative = long NO)
4. Exit decision logic in Frankenstein brain

### 2B. Stop-Loss / Take-Profit Execution (Currently Dead Code)

**Current**: `risk.py` detects when SL/TP thresholds are hit, logs a warning, does nothing.

**Fix**: When threshold is breached → call `execute_sell()` immediately.

Stop-loss logic for prediction markets:
- **Price-based SL**: If bought YES at 60¢ and price drops to 45¢, sell (15¢ loss, not 60¢)
- **Time-based SL**: If <2 hours to expiry and position is underwater, exit (avoid settlement risk)
- **Trailing stop**: If YES price went from 60¢ → 80¢ → now 70¢, trigger trailing stop (lock in some profit)

Take-profit:
- **Edge decay**: If bought at 60¢ predicting 75¢, and price reaches 73¢, exit (remaining edge < spread cost)
- **Partial exit**: At 50% of target, sell half the position (lock in profit, let rest run)

### 2C. Order Amend & Cancel

Use Kalshi's `AmendOrder` endpoint to reprice resting orders without cancel+recreate:
```
POST /portfolio/orders/{order_id}/amend
{
  "ticker": "...",
  "side": "yes",
  "action": "buy",
  "yes_price_dollars": "0.6200"  // updated price
}
```

Cancel stale orders that haven't filled in N minutes:
```
DELETE /portfolio/orders/{order_id}
```

### 2D. Order State Machine

Every order goes through states:
```
PENDING → SUBMITTED → RESTING → {PARTIAL_FILL, FILLED, CANCELLED, AMENDED, EXPIRED}
```

Track with:
- `client_order_id` for deduplication (prevent double-submits on retry)
- WebSocket `fill` channel for real-time fill notifications (Phase 5)
- Periodic polling of `GET /portfolio/orders?status=resting` as fallback

### Phase 2 Deliverables:
- [ ] `execute_sell()` in ExecutionEngine
- [ ] `simulate_sell()` in PaperTradingSimulator
- [ ] Active stop-loss execution (not just detection)
- [ ] Active take-profit execution with partial exits
- [ ] Order amend for repricing stale orders
- [ ] Order cancel for timed-out orders
- [ ] `client_order_id` on every order for idempotency
- [ ] Order state tracking (state machine)

---

# PHASE 3: REAL FEATURE ENGINEERING — See the Market Clearly
### Priority: 🟠 HIGH | Complexity: High | Timeline: 4-5 days

**Why Third**: Once math is fixed and we can sell, the next bottleneck is that the model can't see anything useful. Current features are stock-market technical indicators applied to prediction markets. That's like using a fish finder to hunt deer.

### 3A. Prediction-Market-Native Features

**Time dynamics** (most important for prediction markets):
- `time_to_expiry_hours`: Raw hours until settlement
- `time_to_expiry_pct`: Percentage of market lifetime remaining
- `urgency_factor`: `1 / max(time_to_expiry_hours, 0.1)` — exponentially important near expiry
- `is_last_hour`: Binary flag for final-hour dynamics (price convergence accelerates)
- `hours_since_open`: How long the market has been tradeable

**Price features** (prediction-market-aware):
- `mid_price`: `(yes_bid + yes_ask) / 2`
- `spread_dollars`: `yes_ask - yes_bid` (the cost of trading)
- `spread_pct`: `spread / mid_price` (relative cost)
- `price_vs_50`: `|mid_price - 0.50|` — how "decided" the market is
- `implied_prob`: `mid_price` itself (in prediction markets, price ≈ probability)
- `price_momentum_1h`: Price change over last hour (from 1-min candlesticks)
- `price_momentum_24h`: Price change over 24h
- `price_volatility_1h`: Std dev of 1-min candle closes over last hour
- `price_from_open`: Current price vs. market open price

**Orderbook features** (from `GET /markets/{ticker}/orderbook`):
- `bid_depth_5c`: Total contracts within 5¢ of best bid
- `ask_depth_5c`: Total contracts within 5¢ of best ask
- `bid_ask_imbalance`: `(bid_depth - ask_depth) / (bid_depth + ask_depth)` — directional pressure
- `total_book_depth`: Sum of all resting contracts
- `top_of_book_size`: Contracts at best bid + best ask

**Volume & liquidity** (from market object + candlesticks):
- `volume_24h`: 24-hour trading volume (from `volume_24h_fp`)
- `volume_1h`: Last hour volume (from 1-hour candlestick)
- `open_interest`: Total outstanding contracts (`open_interest_fp`)
- `volume_oi_ratio`: `volume_24h / open_interest` — turnover rate
- `trade_count_1h`: Number of trades in last hour (from trade endpoint)

**Cross-market features**:
- `event_market_count`: How many markets in this event
- `event_sum_prices`: Sum of all YES prices in event (should ≈ 1.0 for mutually exclusive)
- `event_arbitrage_gap`: `|sum_prices - 1.0|` — arbitrage opportunity indicator
- `category_avg_spread`: Average spread across all markets in same category
- `correlated_market_price`: Price of most correlated market in same event

### 3B. Candlestick Data Integration

Use Kalshi's candlestick API for proper OHLC data:
```
GET /series/{series}/markets/{ticker}/candlesticks
  ?start_ts=UNIX&end_ts=UNIX&period_interval=1   // 1-minute candles
```

**Batch endpoint** for efficiency (up to 100 markets at once):
```
GET /markets/candlesticks
  ?market_tickers=TICK1,TICK2,...&start_ts=X&end_ts=Y&period_interval=60
```

From candlestick OHLC, compute:
- True Range: `max(high-low, |high-prev_close|, |low-prev_close|)`
- VWAP: Volume-weighted average price (use `mean_dollars` from candlestick)
- Volume profile: Where most trading happened (price levels)

### 3C. External Data Sources

**News/Events** (critical for prediction markets):
- **RSS/Atom feeds**: AP News, Reuters, ESPN for sports
- **Event calendar**: Kalshi's own `/milestones` endpoint (scheduled events with start dates!)
- **Settlement source tracking**: Each series has `settlement_sources` — scrape those sites
- **Exchange announcements**: `GET /exchange/announcements` for market-affecting info

**Polling / Forecasting aggregators** (for political/economic markets):
- FiveThirtyEight / Silver Bulletin
- PredictIt / Polymarket prices (cross-market comparison)
- RealClearPolitics polling averages
- FRED economic data (for econ markets)

**Sports data** (89% of Kalshi volume = where the money is):
- ESPN API / Sports Reference
- Vegas odds/lines (pinnacle, consensus)
- Injury reports, lineup confirmations
- Weather for outdoor sports

### 3D. Feature Store Architecture

```
┌─────────────────────────────────────────────┐
│              Feature Store                   │
├──────────┬──────────┬───────────┬───────────┤
│  Market  │ Orderbook│ Candle    │ External  │
│  Features│ Features │ Features  │ Features  │
│ (REST)   │ (REST+WS)│ (REST)    │ (Scrapers)│
├──────────┴──────────┴───────────┴───────────┤
│         Feature Computation Layer            │
│  (normalize, lag, rolling windows, combos)   │
├─────────────────────────────────────────────┤
│         Persistent Storage (SQLite/Redis)    │
│  (survive restarts, enable backtesting)      │
└─────────────────────────────────────────────┘
```

Features must be:
- **Timestamped**: Know exactly when each feature was computed
- **Persisted**: Survive restarts (currently all in-memory, lost on crash)
- **Point-in-time correct**: Never use future data when reconstructing historical features
- **Normalized**: Z-score or min-max within rolling windows

### Phase 3 Deliverables:
- [ ] 20+ prediction-market-native features (time, price, orderbook, volume, cross-market)
- [ ] Candlestick data integration (1-min, 1-hour, 1-day)
- [ ] Batch candlestick fetching for efficiency
- [ ] Orderbook depth fetching and feature extraction
- [ ] At least 1 external data source (news RSS or sports odds)
- [ ] Feature store with persistence (SQLite)
- [ ] Feature normalization pipeline

---

# PHASE 4: REAL ML PIPELINE — From Heuristic to Intelligence
### Priority: 🟠 HIGH | Complexity: Very High | Timeline: 5-7 days

**Why Fourth**: Now we have correct math (Phase 1), can trade both directions (Phase 2), and have real features (Phase 3). Time to build a model that actually learns.

### 4A. Solve the Cold Start Problem

**The chicken-and-egg**: XGBoost needs training data → training data comes from settled markets → we need to observe markets first → but we only observe markets we trade... circular.

**Solution: Observation Mode**
1. **Observe everything**: For every open market, record features every hour (or on every WebSocket tick)
2. **Wait for settlement**: Use `GET /portfolio/settlements` and historical API to get outcomes
3. **Build dataset**: `(features_at_time_T, settlement_outcome)` pairs
4. **Bootstrap**: Use Kalshi historical data (`GET /historical/markets`) for 1000s of past markets
5. **Minimum viable dataset**: 500+ settled markets with features before training XGBoost

**Historical data bootstrapping**:
```
GET /historical/markets?limit=1000
→ For each settled market, get:
   GET /historical/markets/{ticker}/candlesticks
→ Reconstruct features at various time points
→ Label = market.result ("yes" or "no")
→ Instant large training set
```

### 4B. Proper Model Architecture

**Ensemble approach** (don't rely on single model):

```
                    ┌──────────────┐
                    │  Meta-Learner │ (stacking)
                    │  (Logistic)   │
                    └──────┬───────┘
               ┌───────────┼───────────┐
               │           │           │
        ┌──────┴──────┐ ┌──┴───┐ ┌────┴────┐
        │  XGBoost    │ │ LR   │ │  NN     │
        │  (trees)    │ │(cal.)│ │(optional)│
        └─────────────┘ └──────┘ └─────────┘
```

1. **XGBoost**: Gradient-boosted trees, good at tabular data, handles missing features
2. **Logistic Regression**: Simple calibrated baseline (surprisingly competitive)
3. **Optional Neural Net**: If we get enough data (10K+ samples)
4. **Meta-learner**: Logistic regression stacking the outputs of base models

**Why ensemble?**: No single model dominates across all market types. Sports markets have different dynamics than political markets. Ensemble hedges against model-specific failure modes.

### 4C. Calibration (The Real Goal)

The model's job is NOT to predict "buy or sell." It's to output **calibrated probabilities**.

**Platt scaling**: After training, fit a logistic regression on validation set:
```python
calibrated_prob = 1 / (1 + exp(-(A * raw_output + B)))
```

**Isotonic regression**: Non-parametric calibration (more flexible, needs more data).

**Validation metric**: Brier Score (MSE of probability predictions):
$$BS = \frac{1}{N} \sum_{i=1}^{N} (p_i - o_i)^2$$

Where $p_i$ = predicted probability, $o_i$ = actual outcome (0 or 1). Lower is better. A perfectly calibrated coin-flip model scores 0.25.

### 4D. Walk-Forward Training Loop

```
For each week W:
    train_data = all settled markets from [week 1 ... week W-1]
    val_data   = settled markets from [week W]
    
    1. Train base models on train_data
    2. Calibrate on val_data
    3. Evaluate: Brier score, calibration plot, profit simulation
    4. If performance degrades → flag for review
    5. Deploy new model weights
    6. Log everything (model version, metrics, feature importances)
```

**Retraining triggers**:
- Scheduled: Weekly (Sunday when markets are quieter)
- Performance: If rolling Brier score degrades >10% from baseline
- Data: After accumulating 100+ new settled markets

### 4E. Feature Importance & Selection

After training:
- SHAP values for global feature importance
- Drop-column importance for validation
- Remove features with <1% importance (noise reduction)
- Monitor for feature drift (distributions changing over time)

### Phase 4 Deliverables:
- [ ] Historical data bootstrapping (1000+ past markets)
- [ ] Observation mode — record features for all markets
- [ ] XGBoost + Logistic Regression ensemble
- [ ] Platt scaling calibration
- [ ] Walk-forward validation with Brier score tracking
- [ ] Automated weekly retraining loop
- [ ] Feature importance logging (SHAP)
- [ ] Model versioning (save each week's model)

---

# PHASE 5: REAL-TIME DATA — WebSocket Integration
### Priority: 🟠 HIGH | Complexity: High | Timeline: 3-4 days

**Why Fifth**: REST polling every 60 seconds means we're always 30 seconds late on average. In fast-moving markets (sports, breaking news), that's an eternity. Kalshi offers 6 WebSocket channels — we use none.

### 5A. WebSocket Architecture

Kalshi WebSocket: `wss://api.elections.kalshi.com/trade-api/ws/v2` (prod) or `wss://demo-api.kalshi.co/trade-api/ws/v2` (demo)

**Public channels** (no auth needed):
1. **`ticker`**: Real-time price updates for all markets
   - `yes_bid`, `yes_ask`, `last_price`, `volume`, `open_interest`
   - Subscribe: `{"type": "subscribe", "channels": ["ticker"], "market_tickers": ["TICK1", "TICK2"]}`
   
2. **`trade`**: Every executed trade on a market
   - `price`, `count`, `taker_side`, `timestamp`
   - Useful for real-time volume tracking and trade flow analysis

**Authenticated channels** (need signed connection):
3. **`orderbook_delta`**: Incremental orderbook updates
   - Sends initial snapshot, then deltas (price level add/remove/change)
   - Build and maintain local orderbook mirror
   
4. **`fill`**: Our own fills in real-time
   - Know *instantly* when our order is matched (not polling every 60s)
   - Critical for order state machine (Phase 2)

5. **`market_positions`**: Position changes on our portfolio
   
6. **`order_group_updates`**: Order group state changes

### 5B. Event-Driven Architecture

```
┌─────────────────────────────────────────────────────┐
│                  WebSocket Manager                    │
│  (connect, auth, subscribe, heartbeat, reconnect)    │
└──────────────────────┬──────────────────────────────┘
                       │ events
          ┌────────────┼────────────┬──────────────┐
          ▼            ▼            ▼              ▼
   ┌────────────┐ ┌─────────┐ ┌─────────┐ ┌───────────┐
   │ Price      │ │ Order   │ │ Feature │ │ Signal    │
   │ Updater    │ │ Tracker │ │ Engine  │ │ Generator │
   │            │ │         │ │         │ │           │
   │ Update     │ │ Fill    │ │ Recomp  │ │ Check     │
   │ cache      │ │ tracking│ │ features│ │ thresholds│
   └────────────┘ └─────────┘ └─────────┘ └───────────┘
```

Instead of: `poll every 60s → check all markets → maybe trade`
Become: `price changes → instant feature update → instant signal check → trade in <1 second`

### 5C. Local Orderbook Maintenance

Subscribe to `orderbook_delta` for markets we're actively trading:
1. Receive initial snapshot (all price levels)
2. Apply deltas (add/remove/modify price levels)
3. Always have current best bid/ask and depth
4. Use for: spread calculation, slippage estimation, smart order placement

### 5D. Reconnection & Reliability

WebSockets drop. Handle it:
- Exponential backoff on reconnect (1s, 2s, 4s, 8s... max 60s)
- Re-subscribe to all channels on reconnect
- Re-request orderbook snapshots after reconnect (deltas may have been missed)
- Heartbeat/ping every 30 seconds to detect dead connections
- Fall back to REST polling if WebSocket is down for >5 minutes

### Phase 5 Deliverables:
- [ ] WebSocket manager (connect, auth, subscribe, heartbeat, reconnect)
- [ ] `ticker` channel integration (real-time price cache updates)
- [ ] `fill` channel integration (instant fill notification → order state machine)
- [ ] `orderbook_delta` channel (local orderbook mirror for active markets)
- [ ] `trade` channel (real-time volume/trade flow tracking)
- [ ] Event-driven feature recomputation on price changes
- [ ] Event-driven signal generation (sub-second latency)
- [ ] Graceful degradation to REST polling on WS failure

---

# PHASE 6: EXECUTION EXCELLENCE — Smart Order Routing
### Priority: 🟡 MEDIUM-HIGH | Complexity: High | Timeline: 4-5 days

**Why Sixth**: Now we have real-time data (Phase 5), correct signals (Phases 1+4), and can trade both ways (Phase 2). Time to stop executing like a noob. Current execution: market orders at whatever price. Smart execution can save 2-5¢ per contract.

### 6A. Smart Order Placement

**Current**: Buy at `yes_ask` (worst price — we always cross the spread).

**Better**: Use limit orders to capture spread instead of paying it.

```
Market: YES bid=60¢, YES ask=65¢ (spread = 5¢)

Dumb execution:  Buy at 65¢ (ask) → instant fill, pay 5¢ spread
Smart execution: Post limit buy at 61¢ → maybe fill, save 4¢
Smarter:         Post at 62¢ → higher fill probability, save 3¢
```

**Placement algorithm**:
1. Check orderbook depth at each price level
2. If spread ≤ 2¢: Just cross (tight spread, not worth posting)
3. If spread 3-5¢: Post inside spread (mid-price or better)
4. If spread > 5¢: Post at `bid + 1¢` and wait (wide spread = be patient)
5. Time limit: If not filled in N seconds, amend order closer to ask
6. If urgent (stop-loss triggered): Cross spread immediately

### 6B. Order Sizing with Spread Awareness

Current Kelly doesn't account for spread cost. Adjust:

$$f^*_{adjusted} = f^*_{kelly} \times \frac{edge - spread/2}{edge}$$

If edge is 5¢ but spread is 4¢, real edge is only 3¢ — size accordingly.

**Minimum edge filter**: Don't trade if `edge < spread + fees`. This alone would prevent most bad trades.

### 6C. Batch Order Submission

Kalshi supports batch orders (up to 20 per request):
```
POST /portfolio/orders/batched
{
  "orders": [
    {"ticker": "T1", "action": "buy", "side": "yes", "yes_price_dollars": "0.6100", "count_fp": "3.00"},
    {"ticker": "T2", "action": "sell", "side": "yes", "yes_price_dollars": "0.7500", "count_fp": "2.00"},
    ...
  ]
}
```

Use for:
- Rebalancing multiple positions simultaneously
- Entering correlated trades atomically
- Exiting multiple positions on risk trigger

### 6D. TWAP Execution (Time-Weighted Average Price)

For larger orders (>10 contracts), don't dump all at once:
```
Total order: 50 contracts
TWAP slices: 5 orders × 10 contracts, spaced 30 seconds apart
Each slice: limit order at current mid-price + 1¢
```

This reduces market impact and gets better average fill price.

### 6E. Post-Only Orders (Maker Rebates)

Kalshi's `post_only: true` flag ensures our order only rests in the book (never crosses spread). If it would immediately execute, it's rejected instead.

**Why use it**: On markets with maker fee rebates (series `fee_type: "quadratic_with_maker_fees"`), posting = earning rebates instead of paying taker fees. Check `GET /series/{ticker}` for fee structure.

### 6F. Paper Trading Realism

Current paper trader: instant fill at mid-price. Meaningless.

**Realistic simulation**:
1. Check actual orderbook before "filling" paper order
2. Apply spread: buy at ask, sell at bid (not mid)
3. Simulate partial fills: only fill up to available depth at price level
4. Add slippage: for orders >50% of top-of-book depth, apply 1¢ slippage per X contracts
5. Add fees: quadratic fee schedule from Kalshi
6. Simulate latency: add 50-200ms random delay before fill

### Phase 6 Deliverables:
- [ ] Spread-aware order placement (inside spread, not crossing)
- [ ] Order price amendment ladder (post → amend closer if unfilled)
- [ ] Batch order submission for rebalancing
- [ ] TWAP execution for large orders
- [ ] Post-only orders on maker-rebate markets
- [ ] Minimum edge filter (`edge > spread + fees`)
- [ ] Realistic paper trading (spread, partial fills, slippage, fees, latency)
- [ ] Fill-rate tracking (what % of limit orders actually fill?)

---

# PHASE 7: RISK MANAGEMENT OVERHAUL — Don't Blow Up
### Priority: 🟡 MEDIUM-HIGH | Complexity: High | Timeline: 3-4 days

**Why Seventh**: With real trading capability (Phases 1-6), we need real risk management. Current risk system is mostly decorative.

### 7A. Position-Level Risk

**Per-position limits**:
- Max position size: 5% of portfolio per market
- Max loss per position: 3% of portfolio
- Automatic exit when limit hit (not just logging!)

**Time-based risk**:
- Reduce max position size as expiry approaches (can't exit easily in illiquid final hours)
- Force close positions if market enters "paused" status (check `exchange/status` → `trading_active`)
- Cancel resting orders automatically on exchange pause (`cancel_order_on_pause: true`)

### 7B. Portfolio-Level Risk

**Concentration limits**:
- Max 20% of portfolio in any single event
- Max 40% in any single category (sports, politics, etc.)
- Max 60% deployed at any time (40% cash reserve)

**Correlation-aware risk**:
- Markets in the same event are correlated (e.g., "Trump wins" and "Republican wins" are ~same bet)
- Track correlated exposure: if 5 markets are all "Team X wins", that's ONE bet, not five
- Sum correlated exposures and apply single-bet limits

**Daily P&L limits**:
- Max daily loss: 5% of portfolio → pause all trading for 24 hours
- Max drawdown from peak: 15% → enter "safe mode" (reduce position sizes by 50%)
- Track realized + unrealized P&L continuously

### 7C. Order Groups (API-Native Risk)

Kalshi's Order Groups provide exchange-level risk control:
```
POST /portfolio/order_groups/create
{
  "contracts_limit_fp": "100.00"  // max 100 contracts in 15-second window
}
```

If the limit is hit, ALL orders in the group are auto-cancelled by Kalshi's exchange. This is a hardware-level circuit breaker — works even if our code crashes.

Use for:
- Rate-limiting order submission (prevent runaway loops)
- Category-level limits (one group per category)
- Emergency kill switch (`PUT /portfolio/order_groups/{id}/trigger`)

### 7D. Stress Testing

Before deploying with real money, simulate:
1. **Flash crash**: What if a market drops 30¢ in 1 minute?
2. **API outage**: What if we can't submit orders for 5 minutes?
3. **Position trap**: What if we're max-long and can't sell (no bids)?
4. **Correlated crash**: What if all sports markets move against us simultaneously?
5. **Exchange pause**: Kalshi pauses trading — do our orders survive?

### 7E. Value at Risk (VaR)

For each position, compute maximum expected loss at 95% confidence:
$$VaR_{95} = position\_size \times z_{0.95} \times \sigma_{daily}$$

For binary contracts, worst case is straightforward: lose entire investment. But VaR helps with portfolio-level questions like "what's our worst likely day?"

### Phase 7 Deliverables:
- [ ] Per-position size limits with auto-enforcement
- [ ] Portfolio concentration limits (per-event, per-category, total deployment)
- [ ] Daily P&L tracking with automatic pause on limit breach
- [ ] Drawdown detection with safe mode
- [ ] Correlation-aware exposure calculation
- [ ] Kalshi Order Groups integration (exchange-level circuit breaker)
- [ ] Stress test framework (5 scenarios)
- [ ] VaR calculation for portfolio

---

# PHASE 8: MARKET INTELLIGENCE — Category-Specific Strategies
### Priority: 🟡 MEDIUM | Complexity: Very High | Timeline: 5-7 days

**Why Eighth**: Generic "one model for all markets" doesn't work. Sports markets behave differently from political markets. 89% of Kalshi's volume is sports — that's where the edge is.

### 8A. Sports Strategy (The Money Maker)

**Why sports?**: Highest volume, tightest spreads, most data available, fastest settlement, most markets per day.

**Data sources**:
- Pre-game odds (Vegas lines, Pinnacle sharp lines)
- Live game data (score, time remaining, possession)
- Player props (injuries, lineups, minutes restrictions)
- Weather (for outdoor sports)

**Strategy: Odds Comparison**
```
Kalshi YES price: 62¢ (implied prob = 62%)
Vegas sharp line implied: 68%
Edge: +6¢ → BUY YES

Kalshi YES price: 45¢ (implied prob = 45%)
Vegas sharp line implied: 38%
Edge: -7¢ → BUY NO (or sell YES)
```

Vegas sharp lines (especially Pinnacle) are considered the most efficient sports odds in the world. If Kalshi deviates significantly from sharp lines, it's likely Kalshi that's wrong.

**Live trading**: As games progress, sports markets move fast. With WebSocket data (Phase 5), react to score changes before the market fully adjusts.

### 8B. Economics Strategy

**Markets**: CPI, GDP, unemployment, Fed rate decisions, jobs reports.

**Data sources**:
- FRED (Federal Reserve Economic Data) — free API
- Bloomberg consensus estimates
- Cleveland Fed inflation nowcast
- Atlanta Fed GDPNow

**Strategy: Nowcasting**
- Economic indicators are published on schedule (BLS, BEA, etc.)
- Nowcasting models (like GDPNow) publish real-time estimates before official release
- Compare nowcast to Kalshi market price → trade discrepancies
- These markets are less efficient than sports (fewer participants, less liquid)

### 8C. Weather Strategy

**Markets**: Temperature records, hurricanes, snowfall, rainfall.

**Data sources**:
- National Weather Service API (free)
- ECMWF / GFS model outputs
- Weather Underground historical data

**Strategy: Model Consensus**
- Multiple weather models make forecasts
- Average their predictions (ensemble)
- Compare ensemble forecast to Kalshi implied probability
- Weather markets are often very inefficient (retail-dominated)

### 8D. Political Strategy

**Markets**: Elections, policy decisions, Supreme Court rulings.

**Data sources**:
- Polling aggregators (FiveThirtyEight, Silver Bulletin, RCP)
- Other prediction markets (Polymarket, PredictIt) — cross-market arb
- Congressional schedule, judicial calendar

**Strategy: Poll Aggregation + Cross-Market Arbitrage**
- Build simple poll aggregation model
- Compare to Kalshi prices
- Also compare Kalshi to Polymarket — if they disagree, one is wrong
- Political markets are among the least efficient (emotional, biased participants)

### 8E. Cross-Event Arbitrage

Within mutually exclusive events, YES prices must sum to ~$1.00:
```
Event: "Which team wins Super Bowl?"
Market A (Chiefs): YES at 30¢
Market B (Bills):  YES at 25¢
Market C (Lions):  YES at 20¢
...all markets sum to: $1.08

Arbitrage: Buy NO on everything at a total cost < $1.00
Guaranteed profit: $0.08 per contract set
```

Use `GET /events?with_nested_markets=true` to scan for these.

Also: Kalshi's **multivariate event collections** (`/multivariate_event_collections/`) create combo markets. These can misprice relative to individual markets.

### Phase 8 Deliverables:
- [ ] Sports strategy module (Vegas odds comparison)
- [ ] At least one external sports data feed
- [ ] Economics strategy module (FRED data + nowcasting)
- [ ] Weather strategy module (NWS API integration)
- [ ] Category-specific model weights (don't use sports model for politics)
- [ ] Cross-event arbitrage scanner
- [ ] Mutually-exclusive price sum monitor
- [ ] Strategy performance tracking per category

---

# PHASE 9: PORTFOLIO OPTIMIZATION & CAPITAL EFFICIENCY
### Priority: 🟡 MEDIUM | Complexity: High | Timeline: 3-4 days

**Why Ninth**: Individual trade quality is great, but portfolio construction is how you compound returns. Phase 1 fixed Kelly for single bets — this phase optimizes across the entire book.

### 9A. Portfolio-Level Kelly (Multi-Asset)

Single-asset Kelly is easy. Multi-asset Kelly accounts for correlations:

For $N$ simultaneous bets with covariance matrix $\Sigma$ and expected returns vector $\mu$:
$$f^* = \Sigma^{-1} \mu$$

In practice, use a simplified version:
1. Compute individual Kelly fractions for each opportunity
2. If total exceeds 100%, scale all positions proportionally
3. Reduce positions for correlated bets (same event, same category)
4. Apply maximum deployment constraint (60% cap from Phase 7)

### 9B. Opportunity Ranking

When multiple signals fire simultaneously, rank by:
$$\text{Score} = \frac{\text{edge}^2}{\text{spread} + \text{fees}} \times \text{volume\_factor} \times \text{time\_factor}$$

Where:
- `edge²` rewards larger edges superlinearly (Kelly-like)
- `spread + fees` penalizes expensive markets
- `volume_factor` = `min(1, volume_24h / 1000)` — prefer liquid markets
- `time_factor` = `min(1, time_to_expiry / 24h)` — avoid markets about to close

### 9C. Rebalancing

Periodically (every hour or on significant market moves):
1. Recalculate optimal position for every market
2. Compare to current position
3. If deviation > threshold → submit rebalancing orders
4. Use batch orders (Phase 6C) for efficiency

### 9D. Capital Recycling

When markets settle, capital is freed. Immediately:
1. Update available balance
2. Re-run opportunity scan
3. Deploy freed capital to best available opportunities
4. Track `GET /portfolio/settlements` for settlement events

### 9E. Incentive Program Exploitation

Kalshi offers **liquidity incentive programs** (`GET /incentive_programs`):
```json
{
  "incentive_type": "liquidity",
  "period_reward": 50000,  // in centi-cents
  "market_ticker": "KXBTC-..."
}
```

Some markets literally **pay you to provide liquidity**. Post two-sided quotes (buy and sell) to earn rewards on top of trading P&L.

Strategy:
1. Scan active incentive programs
2. For qualifying markets, always maintain resting orders on both sides
3. Size based on reward vs. inventory risk
4. This is essentially getting paid to market-make

### Phase 9 Deliverables:
- [ ] Multi-asset Kelly with correlation adjustment
- [ ] Opportunity ranking system (edge, cost, liquidity, time)
- [ ] Periodic rebalancing (hourly + event-driven)
- [ ] Capital recycling on settlement
- [ ] Incentive program scanner and auto-participation
- [ ] Portfolio analytics dashboard (Sharpe ratio, drawdown, P&L attribution by category)

---

# PHASE 10: PRODUCTION HARDENING — Run Forever
### Priority: 🟡 MEDIUM | Complexity: Medium-High | Timeline: 3-4 days

**Why Last**: Everything works in dev. Now make it work at 3 AM on a Saturday when nobody is watching and Railway decides to restart the container.

### 10A. State Persistence (Don't Lose Everything on Restart)

**Current**: All state in-memory, 30-minute save to JSON. Crash = lose up to 30 minutes of data + all computed features.

**Fix**:
- **SQLite WAL mode**: Write-ahead logging, crash-safe, instant recovery
- **Write-through caching**: Every state change → immediate DB write + in-memory cache
- **On startup**: Load all state from DB, reconstruct feature store, resume where we left off
- **Key tables**: `positions`, `orders`, `signals`, `features`, `model_state`, `trade_log`, `settlements`

### 10B. Process Supervision

Railway can restart containers at any time. Handle it:
- **Startup checklist**: On boot, verify DB, check exchange status, sync positions, resub WebSockets
- **Health monitoring**: `GET /exchange/status` every 60 seconds — if `trading_active: false`, pause everything
- **Heartbeat**: Write timestamp to DB every 60 seconds — if gap detected on restart, reconcile
- **Idempotent recovery**: Use `client_order_id` (UUID) on every order — replaying is safe

### 10C. Exchange Schedule Awareness

Kalshi is NOT 24/7. Check `GET /exchange/schedule`:
```json
{
  "standard_hours": {
    "monday": [{"open_time": "00:00", "close_time": "23:59"}],
    ...
    "sunday": [{"open_time": "18:00", "close_time": "23:59"}]
  },
  "maintenance_windows": [...]
}
```

- Don't submit orders outside trading hours
- Cancel resting orders before maintenance windows
- Schedule retraining during off-hours
- Track `exchange_estimated_resume_time` during maintenance

### 10D. Monitoring & Alerting

**Metrics to track**:
- P&L (realized + unrealized, per-market and total)
- Win rate (by category, by model version)
- Fill rate (what % of our orders actually execute)
- Latency (order submission to fill)
- Feature freshness (how old is our latest data)
- Model calibration (rolling Brier score)
- API error rate (4xx, 5xx, timeouts)
- Available balance vs. deployed capital

**Alert thresholds**:
- Daily P&L loss > 3% → Slack/email alert
- Drawdown > 10% → CRITICAL alert + auto-pause
- API error rate > 5% → WARNING
- No fills in 4 hours during active trading → WARNING
- Model Brier score degraded > 20% → Retrain trigger

### 10E. Logging & Audit Trail

Every trade decision must be fully explainable:
```
[2026-03-10 14:32:01] SIGNAL ticker=KXNBA-LAL-NYK side=yes
  model_prob=0.72 market_price=0.64 edge=+0.08
  kelly_raw=0.222 kelly_half=0.111 adjusted_for_spread=0.089
  position_size=9_contracts at 0.65 (limit, inside spread)
  risk_check: PASS (portfolio_exposure=32%, max=60%)
  order_id=abc123 client_id=uuid-xyz
[2026-03-10 14:32:03] FILL order=abc123 filled=9/9 at 0.65 fee=0.42
[2026-03-10 16:15:00] EXIT ticker=KXNBA-LAL-NYK reason=take_profit
  entry=0.65 exit=0.78 pnl=+$1.17 hold_time=1h43m
```

### 10F. Graceful Degradation Hierarchy

```
Full Mode:     WebSocket + ML model + smart execution + all features
     ↓ (WebSocket fails)
Polling Mode:  REST polling + ML model + smart execution + all features
     ↓ (ML model stale or erroring)
Heuristic Mode: REST polling + heuristic + basic execution + core features
     ↓ (API errors > 10%)
Safe Mode:     Close all resting orders, hold existing positions, alert human
     ↓ (API fully down)
Offline Mode:  Save state to disk, wait for reconnection, alert human
```

### Phase 10 Deliverables:
- [ ] SQLite persistence with WAL mode (crash-safe)
- [ ] Write-through caching (DB + memory in sync)
- [ ] Startup reconciliation (sync with exchange state)
- [ ] Exchange schedule awareness (no trading during maintenance)
- [ ] Health check monitoring loop
- [ ] Idempotent order submission (client_order_id everywhere)
- [ ] Comprehensive audit logging for every trade decision
- [ ] Graceful degradation hierarchy (5 levels)
- [ ] Alert system (P&L, drawdown, errors)
- [ ] Automated recovery after container restart

---

## IMPLEMENTATION PRIORITY MATRIX

```
                    HIGH IMPACT
                        │
     Phase 1 ●──────────┼────────────● Phase 2
    (Fix Math)          │         (Learn to Sell)
                        │
     Phase 4 ●──────────┼────────────● Phase 3
    (Real ML)           │       (Real Features)
                        │
     Phase 5 ●──────────┼────────────● Phase 7
   (WebSocket)          │        (Risk Overhaul)
                        │
     Phase 6 ●──────────┼────────────● Phase 8
   (Smart Exec)         │      (Category Strats)
                        │
     Phase 9 ●──────────┼────────────● Phase 10
   (Portfolio)          │       (Production)
                        │
                    LOW IMPACT
        LOW EFFORT ◄────┼────► HIGH EFFORT
```

**Critical path**: Phase 1 → Phase 2 → Phase 3 → Phase 4 (each depends on the prior)
**Parallel work**: Phase 5 can start alongside Phase 3/4. Phase 7 alongside Phase 6.
**Independent**: Phases 8, 9, 10 can be done in any order after Phase 6.

## ESTIMATED TOTAL TIMELINE

| Phase | Days | Running Total | Milestone |
|-------|------|--------------|-----------|
| Phase 1: Fix Math | 2-3 | 3 days | Correct Kelly, correct labels, correct validation |
| Phase 2: Sell Orders | 3-4 | 7 days | Full order lifecycle — buy, sell, amend, cancel |
| Phase 3: Real Features | 4-5 | 12 days | 20+ features, orderbook, candlesticks, external data |
| Phase 4: Real ML | 5-7 | 19 days | Trained ensemble, calibrated probabilities, walk-forward |
| Phase 5: WebSocket | 3-4 | 23 days | Real-time prices, fills, orderbook — sub-second reactions |
| Phase 6: Smart Execution | 4-5 | 28 days | Spread capture, TWAP, batch orders, post-only |
| Phase 7: Risk Overhaul | 3-4 | 32 days | Position limits, correlation, drawdown protection, order groups |
| Phase 8: Category Strats | 5-7 | 39 days | Sports odds, econ nowcasting, weather, cross-event arb |
| Phase 9: Portfolio Opt | 3-4 | 43 days | Multi-Kelly, ranking, rebalancing, incentive farming |
| Phase 10: Production | 3-4 | **47 days** | Persistence, monitoring, alerts, graceful degradation |

**Total: ~7 weeks of focused work to go from "toy" to "weapon".**

## SUCCESS METRICS (How We Know It's Working)

| Metric | Current | Phase 4 Target | Phase 10 Target |
|--------|---------|----------------|-----------------|
| Brier Score | N/A (no calibration) | < 0.22 | < 0.18 |
| Win Rate | ~50% (coin flip) | > 55% | > 58% |
| Edge per Trade | Unknown | > 3¢ average | > 5¢ average |
| Sharpe Ratio | N/A | > 0.5 | > 1.5 |
| Max Drawdown | Untracked | < 20% | < 10% |
| Fill Rate | 100% (paper, fake) | > 60% (limit orders) | > 75% |
| Signal Latency | 60s (REST polling) | < 5s (WS + REST) | < 1s (full WS) |
| Markets Monitored | 100 | 500+ | All open markets |
| Data Sources | 1 (Kalshi REST) | 3+ (Kalshi + candlesticks + 1 external) | 5+ |
| Uptime | Until next crash | 95% | 99.5% |

---

*Plan complete. No building yet — but when we start, every line of code has a reason.*
