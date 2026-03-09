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

*Research completed. Ready to build.*
