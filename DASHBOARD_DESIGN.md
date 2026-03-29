# JA Hedge Dashboard Redesign — Complete Design Document

## Executive Summary

The current dashboard has **13 sidebar pages** with significant overlap and fragmentation. Users must click through multiple pages to get a coherent picture of what's happening. The redesign consolidates everything into **4 tabs** — each a complete "world" of its own — with live data flowing throughout.

### Philosophy: From "Many Pages" → "4 Command Screens"

The new design treats each tab as a **full-screen command station** — dense with information but logically grouped. No page should require you to navigate elsewhere to answer the question you had when you opened it.

---

## Current State Audit

### 13 Existing Pages → What They Contain

| Page | Lines | What It Shows | Overlap With |
|------|-------|---------------|-------------|
| **Overview** | 439 | Balance, P&L, positions, risk, Frankenstein status, trades, fills | Portfolio, Risk, Frankenstein |
| **Frankenstein** | 1242 | Brain status + 5 internal tabs (overview/trades/analytics/model/chat) | Overview, Analytics, AI |
| **Strategies** | 842 | 8 strategy toggles, decision engine, model intelligence, scan | AI Engine, Intelligence |
| **Intelligence** | 735 | 5 internal tabs (overview/sources/signals/alerts/analysis) | Strategies, Alerts |
| **Trading** | 613 | Order form, market search, fills | Portfolio, Markets |
| **Guide** | 509 | Static docs (10 sections) | — |
| **Sports** | 475 | 4 internal tabs (markets/odds/live/performance) | Markets, Intelligence |
| **Settings** | 843 | 5 internal tabs (simulation/strategy/brain/system/diagnostics) | Frankenstein controls |
| **Risk** | 268 | Risk gauge, limits editor, kill switch | Overview |
| **Agent** | 208 | Legacy agent start/stop controls | Frankenstein |
| **Portfolio** | 201 | Balance, positions, fills | Overview |
| **AI Engine** | 174 | Brain status, features, signals | Frankenstein, Strategies |
| **Backtest** | 174 | Strategy backtester | Strategies |
| **Alerts** | 122 | Alert list, acknowledge | Intelligence |

**Key Insight**: There's a ~60% content overlap. Overview repeats Portfolio + Risk + Frankenstein. AI Engine repeats Frankenstein model tab. Strategies repeats Intelligence signals. Agent is superseded by Frankenstein controls.

---

## New 4-Tab Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  🧠 JA Hedge    [⚡ Live] [🟢 Connected] [⏰ 14:32:01]  [🚨 Kill Switch]  │
├──────────────┬───────────────┬──────────────┬───────────────────┤
│ ◉ LIVE       │ 📊 ANALYTICS  │ 🎯 MARKETS   │ ⚙️ CONTROL        │
│   Command    │   & Perf      │   & Signals  │   Center          │
├──────────────┴───────────────┴──────────────┴───────────────────┤
│                                                                  │
│                    [  TAB CONTENT AREA  ]                        │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### Navigation Design
- **Top bar** stays (health indicator, connection status, time, kill switch, alert badge)
- **Sidebar collapses** to a minimal 48px icon rail OR is replaced entirely by **horizontal tabs** below the top bar
- **4 tabs** with icon + label, active tab gets accent underline/glow
- **Each tab is a dense single-page app** — scrollable, with internal sub-sections and optional collapsible panels

---

## Tab 1: LIVE COMMAND CENTER

**Purpose**: "What's happening RIGHT NOW?" — the screen you stare at during trading hours.

**Replaces**: Overview, Portfolio, Risk, Agent

**Polling**: Every 5-8 seconds (fast)

### Layout Wireframe

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌───────┐│
│ │ Balance │ │  P&L    │ │ Open    │ │ Today's │ │ Win     │ │ Risk  ││
│ │ $456.32 │ │ +$19.40 │ │ Pos: 3  │ │ Trades:7│ │ Rate:57%│ │ ██░░  ││
│ │ ▲ $2.10 │ │ ▲ 4.2%  │ │ $150exp │ │ 5W 2L   │ │ ▲ from  │ │ 42%   ││
│ └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘ └───────┘│
│                                                                         │
│ ┌──────────────────────────────────┐  ┌────────────────────────────────┐│
│ │ 🧠 BRAIN STATUS                  │  │ 📈 LIVE P&L SPARKLINE          ││
│ │                                  │  │                                ││
│ │ State: ⚡ TRADING                │  │  ╱╲    ╱╲                      ││
│ │ Uptime: 4h 23m                   │  │ ╱  ╲╱╱  ╲  ╱╲                ││
│ │ Generation: 12                   │  │╱        ╲╱  ╲╱╲              ││
│ │ Last scan: 8s ago                │  │                  ╲            ││
│ │ Candidates: 47 → 3 passed gates  │  │ [last 200 trades]            ││
│ │ Pending orders: 2                │  │                                ││
│ │ Model: XGBoost (847 trees)       │  │ Today: +$4.20  |  All: +$19  ││
│ └──────────────────────────────────┘  └────────────────────────────────┘│
│                                                                         │
│ ┌──────────────────────────────────┐  ┌────────────────────────────────┐│
│ │ 📊 OPEN POSITIONS                │  │ ⚡ LIVE TRADE FEED             ││
│ │                                  │  │                                ││
│ │ KXBTC-24  YES@42¢  Qty:10  +$2  │  │ 14:31 BUY YES KXELEC-NH @38¢ ││
│ │ KXELEC-NH YES@38¢  Qty:5   -$1  │  │ 14:28 FILL KXBTC-24   +$4.20 ││
│ │ KXNFL-KC  NO @65¢  Qty:8   +$3  │  │ 14:22 BUY NO  KXNFL-KC @65¢ ││
│ │                                  │  │ 14:15 FILL KXELEC-AZ  -$1.30 ││
│ │ Total Exposure: $230             │  │ 14:10 CANCEL KXWEATH  (aged)  ││
│ │ Unrealized P&L: +$4.00          │  │ 14:05 BUY YES KXNFL-KC @62¢  ││
│ └──────────────────────────────────┘  └────────────────────────────────┘│
│                                                                         │
│ ┌───────────────────────────────────────────────────────────────────────┐│
│ │ 🛡️ RISK MONITOR (compact bar)                                        ││
│ │                                                                       ││
│ │ Positions: ██████░░░░ 3/10    Exposure: ████░░░░░░ $230/$500         ││
│ │ Daily Loss: █░░░░░░░░░ $3/$50  Drawdown: ██░░░░░░░░ 8%/20%          ││
│ └───────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
```

### Data Sources (API Calls)

| Section | Endpoint | Poll Rate |
|---------|----------|-----------|
| Stat cards | `GET /api/portfolio/balance`, `GET /api/portfolio/pnl` | 8s |
| Brain status | `GET /api/frankenstein/status` | 8s |
| P&L sparkline | `GET /api/frankenstein/analytics` → `pnl_curve` | 30s |
| Open positions | `GET /api/portfolio/positions` | 8s |
| Live trade feed | `GET /api/frankenstein/memory/recent?limit=20` + `GET /api/portfolio/fills?limit=10` | 8s |
| Risk monitor | `GET /api/risk/snapshot` | 15s |

### Key Design Decisions
- **P&L sparkline** uses `lightweight-charts` (already in deps) — small area chart showing last 200 trade outcomes
- **Live trade feed** merges Frankenstein trades + exchange fills into one unified timeline
- **Brain status** shows the full funnel: active markets → candidates → passed gates → orders placed
- **Risk monitor** is a compact horizontal bar visualization, not a full page

---

## Tab 2: ANALYTICS & PERFORMANCE

**Purpose**: "How well is the system performing?" — deep dive into historical performance, model quality, and strategy analysis.

**Replaces**: Frankenstein analytics tab, AI Engine, Backtest, Strategies (decision engine/model views)

**Polling**: Every 30-60 seconds (slower, analytics data)

### Layout Wireframe

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌───────┐│
│ │ Total   │ │ Win     │ │ Sharpe  │ │ Profit  │ │ Avg     │ │ Max   ││
│ │ Trades  │ │ Rate    │ │ Ratio   │ │ Factor  │ │ Edge    │ │ DD    ││
│ │ 359     │ │ 57.4%   │ │ 1.87    │ │ 1.34    │ │ 3.2¢    │ │ -$12  ││
│ └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘ └───────┘│
│                                                                         │
│  [Overview]  [By Category]  [By Confidence]  [Model]  [Backtest]       │
│                                                                         │
│ ── Overview Sub-tab ──────────────────────────────────────────────────  │
│                                                                         │
│ ┌───────────────────────────────────────────────────────────────────────┐│
│ │ 📈 CUMULATIVE P&L CURVE                                              ││
│ │                                                                       ││
│ │  $20 ─┤                                          ╱──                 ││
│ │  $15 ─┤                               ╱╲   ╱╲╱╱                     ││
│ │  $10 ─┤                    ╱╲    ╱╲╱╱╱  ╲╱╱                        ││
│ │   $5 ─┤          ╱╲  ╱╲╱╱╱  ╲╱╱                                    ││
│ │   $0 ─┤────╱╲╱╱╱                                                    ││
│ │  -$5 ─┤╱╱╱                                                          ││
│ │       └─────────────────────────────────────────────────────────      ││
│ │        Trade #1                                      Trade #359      ││
│ └───────────────────────────────────────────────────────────────────────┘│
│                                                                         │
│ ┌──────────────────────────────────┐  ┌────────────────────────────────┐│
│ │ 🏷️ PERFORMANCE BY CATEGORY       │  │ 🎯 CONFIDENCE BAND BREAKDOWN   ││
│ │                                  │  │                                ││
│ │ Politics  ████████ +$8.40 (62%W) │  │ 90-100%: +$12.30 (78% WR)    ││
│ │ Crypto    ██████   +$5.20 (55%W) │  │ 80-90%:  +$4.50  (62% WR)    ││
│ │ Sports    ████     +$3.10 (58%W) │  │ 70-80%:  +$2.10  (55% WR)    ││
│ │ Weather   ██       +$1.80 (52%W) │  │ 60-70%:  +$0.50  (48% WR)    ││
│ │ Finance   █        +$0.90 (51%W) │  │ <60%:    -$0.00  (skipped)   ││
│ └──────────────────────────────────┘  └────────────────────────────────┘│
│                                                                         │
│ ┌───────────────────────────────────────────────────────────────────────┐│
│ │ 📋 TRADE LOG (scrollable, sortable)                                   ││
│ │                                                                       ││
│ │ Time      │ Market         │ Side │ Price │ Outcome │ P&L  │ Conf    ││
│ │ 14:31:02  │ KXELEC-NH     │ YES  │ 38¢   │ ⏳       │ —    │ 82%    ││
│ │ 14:28:15  │ KXBTC-24      │ YES  │ 42¢   │ ✅ WIN  │+$4.20│ 88%    ││
│ │ 14:22:40  │ KXELEC-AZ     │ NO   │ 62¢   │ ❌ LOSS │-$1.30│ 71%    ││
│ └───────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
```

### Sub-Tabs Within Analytics

1. **Overview** — P&L curve + category/confidence summary + trade log
2. **By Category** — Detailed per-category stats (politics, crypto, sports, etc.) with mini P&L curves per category
3. **By Confidence** — Confidence band analysis, calibration chart (predicted vs actual), edge distribution
4. **Model** — Model intelligence (XGBoost tree count, feature importance top 20, calibration health, uncertainty estimation, generation history)
5. **Backtest** — Strategy backtester (strategy picker, date range, run, results table) — migrated from old Backtest page

### Data Sources

| Section | Endpoint | Poll Rate |
|---------|----------|-----------|
| Stat cards | `GET /api/frankenstein/performance/snapshot` | 30s |
| P&L curve | `GET /api/frankenstein/analytics` → `pnl_curve` | 60s |
| Category breakdown | `GET /api/frankenstein/analytics` → `by_category` | 60s |
| Confidence bands | `GET /api/frankenstein/analytics` → `by_confidence` | 60s |
| Trade log | `GET /api/frankenstein/memory/recent?limit=100` | 30s |
| Model intelligence | `GET /api/frankenstein/model/intelligence` | 120s |
| Feature importance | `GET /api/frankenstein/features` | 120s |
| Calibration | `GET /api/frankenstein/model/calibration` | 120s |
| Backtest | `POST /api/backtest/run` | on-demand |

---

## Tab 3: MARKETS & SIGNALS

**Purpose**: "What opportunities exist?" — live market data, strategy signals, sports odds, intelligence feeds.

**Replaces**: Markets, Strategies, Sports, Intelligence, Alerts

**Polling**: Every 15-30 seconds

### Layout Wireframe

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌───────┐│
│ │ Active  │ │ Candi-  │ │ Active  │ │ Signal  │ │ Sports  │ │ Intel ││
│ │ Markets │ │ dates   │ │ Signals │ │ Hit Rate│ │ Games   │ │ Alerts││
│ │ 2,847   │ │ 47      │ │ 12      │ │ 63%     │ │ 8 live  │ │ 3 new ││
│ └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘ └───────┘│
│                                                                         │
│  [Candidates]  [Strategies]  [Sports]  [Intelligence]  [Alerts]        │
│                                                                         │
│ ── Candidates Sub-tab (DEFAULT) ─────────────────────────────────────  │
│                                                                         │
│ ┌───────────────────────────────────────────────────────────────────────┐│
│ │ 🎯 CURRENT TRADE CANDIDATES (from Frankenstein filter pipeline)       ││
│ │                                                                       ││
│ │ [🔍 Search...]  [Category ▾]  [Min Edge ▾]  [Sort: Edge ▾]          ││
│ │                                                                       ││
│ │ Ticker        │ Title              │ Price │ Edge  │ Conf │ Status   ││
│ │ KXELEC-NH     │ NH primary winner  │ 38¢   │ +4.2¢ │ 82%  │ 📤 Sent ││
│ │ KXBTC-25K     │ BTC above $25k     │ 56¢   │ +3.8¢ │ 79%  │ ⏳ Queue││
│ │ KXNFL-KC-W    │ Chiefs win week 12 │ 42¢   │ +3.1¢ │ 76%  │ ❌ Rejct││
│ │ ...more candidates...                                                 ││
│ │                                                                       ││
│ │ [Expand row → full confidence breakdown: base, spread, volume,        ││
│ │  category, regime, uncertainty, gate results]                          ││
│ └───────────────────────────────────────────────────────────────────────┘│
│                                                                         │
│ ┌──────────────────────────────────┐  ┌────────────────────────────────┐│
│ │ 🔬 REJECTION ANALYSIS            │  │ 📊 EDGE DISTRIBUTION           ││
│ │                                  │  │                                ││
│ │ Why rejected (last scan):       │  │  12│  ██                       ││
│ │ • 23 → spread too wide (>6¢)    │  │  10│  ████                     ││
│ │ • 12 → confidence < 60%         │  │   8│  ████ ██                  ││
│ │ •  8 → edge < 2¢                │  │   6│  ████ ████                ││
│ │ •  3 → position limit           │  │   4│  ████ ████ ██            ││
│ │ •  1 → daily loss limit         │  │     1¢  2¢  3¢  4¢  5¢+      ││
│ └──────────────────────────────────┘  └────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
```

### Sub-Tabs Within Markets & Signals

1. **Candidates** (default) — Live candidate pipeline from Frankenstein debug/rejections endpoint. Shows what passed and what didn't, with expandable confidence breakdowns. This is THE key operational view.
2. **Strategies** — The 8 strategy engines with enable/disable toggles, signal counts, scan trigger. Decision engine logic explanation.
3. **Sports** — Live games, Vegas odds comparison, sport-specific markets, performance by sport.
4. **Intelligence** — Multi-source signal feed, source quality, correlation analysis, feature weights.
5. **Alerts** — Alert feed with severity filtering and bulk acknowledge.

### Data Sources

| Section | Endpoint | Poll Rate |
|---------|----------|-----------|
| Stat cards | `GET /api/frankenstein/status` + `GET /api/strategies/status` | 15s |
| Candidates | `GET /api/frankenstein/debug/rejections` | 15s |
| Strategies | `GET /api/strategies/status` + `GET /api/strategies/signals` | 30s |
| Sports | `GET /api/sports/markets` + `GET /api/sports/live` | 30s |
| Intelligence | `GET /api/intelligence/dashboard` | 30s |
| Alerts | `GET /api/alerts` | 30s |

---

## Tab 4: CONTROL CENTER

**Purpose**: "Configure, tune, and interact with the system." — all knobs and levers in one place.

**Replaces**: Settings, Frankenstein controls (awaken/sleep/pause), Trading (manual orders), Risk (limits editor), Guide

**Polling**: Every 15 seconds for status, on-demand for actions

### Layout Wireframe

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ┌──────────────────────────────────────────────────────────────────────┐│
│ │ 🧠 BRAIN CONTROLS                                                    ││
│ │                                                                       ││
│ │ [⚡ AWAKEN]  [💤 SLEEP]  [⏸️ PAUSE]  [▶️ RESUME]  [🔄 RETRAIN]       ││
│ │                                                                       ││
│ │ State: TRADING  │  Generation: 12  │  Uptime: 4h23m  │  Paper: ✅    ││
│ └──────────────────────────────────────────────────────────────────────┘│
│                                                                         │
│  [Settings]  [Risk]  [Trading]  [Chat]  [Guide]                        │
│                                                                         │
│ ── Settings Sub-tab ─────────────────────────────────────────────────  │
│                                                                         │
│ ┌──────────────────────────────────┐  ┌────────────────────────────────┐│
│ │ ⚙️ STRATEGY PARAMETERS            │  │ 🧠 BRAIN CONFIGURATION         ││
│ │                                  │  │                                ││
│ │ Min Confidence:  [====●===] 60%  │  │ Scan Interval:  [=●======] 30s││
│ │ Min Edge:        [==●=====] 2.0¢ │  │ Sports Only:    [OFF]         ││
│ │ Kelly Fraction:  [===●====] 0.25 │  │ Memory Decay:   [=●======] 50 ││
│ │ Max Pos Size:    [====●===] 15   │  │                                ││
│ │ Max Spread:      [===●====] 6¢   │  │                                ││
│ │                                  │  │                                ││
│ │ Stop Loss:       [===●====] 15%  │  │                                ││
│ │ Take Profit:     [====●===] 25%  │  │                                ││
│ │ Aggression:      [===●====] 0.5  │  │                                ││
│ │                                  │  │                                ││
│ │        [💾 Save Changes]          │  │        [💾 Save Changes]       ││
│ └──────────────────────────────────┘  └────────────────────────────────┘│
│                                                                         │
│ ┌──────────────────────────────────┐  ┌────────────────────────────────┐│
│ │ 💰 PAPER TRADING SIM              │  │ 🔍 DIAGNOSTICS                 ││
│ │                                  │  │                                ││
│ │ Fee Rate: [0] ¢ (maker = free!) │  │ Debug Scan Funnel: [▶ Run]    ││
│ │ Slippage: [0] ¢                  │  │ Cache Check: [▶ Run]          ││
│ │                                  │  │ Test Trade: [▶ Run]           ││
│ │ [🔄 Reset Simulation]            │  │                                ││
│ │   ☐ Reset balance               │  │ Last scan result:             ││
│ │   ☐ Clear memory                │  │ cache → 2847 active           ││
│ │   ☐ Reset brain state           │  │ filter → 47 candidates        ││
│ │                                  │  │ features → OK (mid=0.42)     ││
│ │   [⚠️ Reset]                     │  │ predict → OK (prob=0.68)     ││
│ └──────────────────────────────────┘  └────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
```

### Sub-Tabs Within Control Center

1. **Settings** (default) — Strategy params, brain config, paper trading sim settings, diagnostics. All editable with sliders and save buttons.
2. **Risk** — Risk limits editor (max positions, max exposure, max daily loss), kill switch toggle, risk gauge visualizations.
3. **Trading** — Manual order placement (market search, side/price/quantity, cost preview, submit). For when you want to override the AI.
4. **Chat** — Full chat interface with Frankenstein (supports slash commands: /status, /awaken, /sleep, /retrain). Markdown rendering. Chat history.
5. **Guide** — Embedded documentation/FAQ (migrated from the static Guide page). Collapsible sections.

### Data Sources

| Section | Endpoint | Poll Rate |
|---------|----------|-----------|
| Brain controls | `GET /api/frankenstein/status` | 15s |
| Settings read | `GET /api/frankenstein/settings` | on-load |
| Settings write | `PUT /api/frankenstein/settings` | on-save |
| Risk limits | `GET /api/risk/limits` + `GET /api/risk/snapshot` | 15s |
| Kill switch | `POST /api/risk/kill-switch` | on-click |
| Trading | `POST /api/orders` | on-submit |
| Markets search | `GET /api/markets?search=...` | on-type |
| Chat | `POST /api/frankenstein/chat`, `GET /api/frankenstein/chat/history` | on-send |
| Diagnostics | `GET /api/frankenstein/debug-scan` | on-click |
| Simulation reset | `POST /api/frankenstein/simulation/reset` | on-click |

---

## Visual Design System

### Existing Assets to Preserve
- **Dark theme**: `--bg-primary: #050508`, glass morphism with backdrop-filter blur
- **Accent**: Emerald `#10b981` for positive/active states
- **Danger**: Red `#ef4444` for losses, kill switch, critical alerts
- **Warning**: Amber `#f59e0b` for caution states
- **Info**: Blue `#3b82f6` for neutral information
- **Fonts**: Inter (UI) + JetBrains Mono (numbers/code)
- **Glass utilities**: `glass`, `glass-strong`, `glass-subtle` with blur levels
- **Animations**: `fade-in`, `pulse-glow`, `shimmer`

### New Design Patterns

#### Tab Bar Component
```
Height: 48px
Background: glass-subtle
Active tab: accent underline (2px) + text-accent + slight glow
Inactive tab: text-muted, hover → text-white
Icons: lucide-react, 18px, to left of label
Tab label: font-medium text-sm
```

#### Stat Card Row (hero metrics)
```
6 cards in a row (responsive: 3x2 on tablet, 2x3 on mobile)
Height: ~80px
Background: glass
Large number: text-2xl font-mono (JetBrains Mono)
Label: text-xs text-muted uppercase tracking-wider
Change indicator: ▲/▼ with color (emerald/red)
Optional sparkline in card background (subtle)
```

#### Data Tables
```
Background: glass-subtle
Header: text-xs text-muted uppercase, sticky
Rows: hover → glass-strong, border-b border-white/5
Numbers: font-mono
Status badges: rounded-full px-2 py-0.5 text-xs
Expandable rows: click → slide-down detail panel
```

#### Live Feed / Timeline
```
Left border: 2px colored by event type (emerald=fill, blue=order, red=cancel, amber=rejection)
Timestamp: font-mono text-xs text-muted
Content: text-sm, market ticker in accent
Auto-scroll with "jump to latest" button
Max visible: 20 items with virtual scrolling
```

#### Charts
```
Library: lightweight-charts (TradingView)
Background: transparent (inherits glass)
Line color: emerald for P&L, with red for drawdown periods
Crosshair: on hover with tooltip
Responsive: fill container width
```

---

## State Management

### Zustand Store Structure
```typescript
interface DashboardStore {
  // Active tab
  activeTab: 'live' | 'analytics' | 'markets' | 'control';
  setActiveTab: (tab: string) => void;

  // Live data (fast poll)
  balance: Balance | null;
  pnl: PnL | null;
  positions: Position[];
  fills: Fill[];
  brainStatus: FrankensteinStatus | null;
  riskSnapshot: RiskSnapshot | null;
  recentTrades: FrankensteinTrade[];

  // Analytics data (slow poll)
  analytics: FrankensteinAnalytics | null;
  performanceSnapshot: any;
  modelIntelligence: any;

  // Markets data
  candidates: any[];
  strategies: StrategyEngineStatus | null;
  signals: any[];

  // Connection
  isConnected: boolean;
  lastUpdate: Date | null;
}
```

### Polling Architecture
```
Tab 1 (Live):     Fast poll (8s)  → balance, pnl, positions, status, trades
Tab 2 (Analytics): Slow poll (60s) → analytics, performance, model
Tab 3 (Markets):   Med poll (15s)  → candidates, strategies, signals
Tab 4 (Control):   On-demand       → settings, diagnostics (only status at 15s)

Rule: Only poll for the ACTIVE TAB's data.
      Always poll health + connection (15s) regardless of tab.
```

---

## Implementation Phases

### Phase 1: Foundation (Layout + Tab Navigation)
- Replace 13-item Sidebar with 4-tab navigation bar
- Create `TabBar` component
- Update `dashboard/layout.tsx` to use new tab system
- Set up route structure: `/dashboard?tab=live` (or keep as single page with state)

### Phase 2: Live Command Center
- Build stat card row (6 cards)
- Brain status panel
- P&L sparkline with lightweight-charts
- Open positions table
- Live trade feed (merged trades + fills)
- Compact risk monitor bars

### Phase 3: Analytics & Performance
- Stat card row (6 performance metrics)
- Full P&L curve chart
- Category breakdown bars
- Confidence band analysis
- Trade log table with sorting
- Model intelligence panel
- Backtest sub-tab migration

### Phase 4: Markets & Signals
- Candidates table (from debug/rejections endpoint)
- Rejection analysis summary
- Strategy toggles migration
- Sports sub-tab migration
- Intelligence sub-tab migration
- Alerts sub-tab migration

### Phase 5: Control Center
- Brain control buttons (awaken/sleep/pause/resume/retrain)
- Settings editor with sliders
- Risk limits editor
- Manual trading form
- Chat interface migration
- Guide/documentation migration
- Diagnostics panel

### Phase 6: Polish & Responsive
- Mobile/tablet responsive breakpoints
- Loading states and skeletons
- Error boundaries per section
- Transition animations between tabs
- Keyboard shortcuts (1-4 for tabs)

---

## File Structure (New)

```
frontend/src/
├── app/
│   └── dashboard/
│       ├── layout.tsx          (updated: tab bar + top bar)
│       ├── page.tsx            (updated: single page with tab switching)
│       │
│       ├── _tabs/              (tab content components - not routes)
│       │   ├── LiveTab.tsx
│       │   ├── AnalyticsTab.tsx
│       │   ├── MarketsTab.tsx
│       │   └── ControlTab.tsx
│       │
│       └── _components/        (shared sub-components)
│           ├── StatCardRow.tsx
│           ├── BrainStatus.tsx
│           ├── PnLChart.tsx
│           ├── PositionsTable.tsx
│           ├── TradeFeed.tsx
│           ├── RiskBars.tsx
│           ├── TradeLog.tsx
│           ├── CandidateTable.tsx
│           ├── StrategyList.tsx
│           ├── SettingsEditor.tsx
│           ├── ChatPanel.tsx
│           └── ...
│
├── components/
│   ├── layout/
│   │   ├── TopBar.tsx          (keep, minor updates)
│   │   ├── TabBar.tsx          (NEW: replaces Sidebar)
│   │   └── Sidebar.tsx         (deprecated/removed)
│   │
│   └── ui/
│       ├── Card.tsx            (keep)
│       ├── StatCard.tsx        (keep + enhance)
│       ├── Icons.tsx           (keep + add new icons)
│       ├── Badge.tsx           (NEW: status badges)
│       ├── ProgressBar.tsx     (NEW: risk bars)
│       ├── Slider.tsx          (NEW: settings sliders)
│       └── Table.tsx           (NEW: base table component)
│
├── lib/
│   ├── api.ts                  (keep as-is, already comprehensive)
│   └── store.ts                (NEW: zustand store)
│
└── hooks/
    ├── usePolling.ts           (NEW: smart polling hook)
    └── useTabs.ts              (NEW: tab state + URL sync)
```

---

## Migration Notes

### Pages to Remove After Migration
All 13 old page directories under `dashboard/` can be removed once the 4-tab system is complete:
- `agent/`, `ai/`, `alerts/`, `backtest/`, `frankenstein/`, `guide/`, `intelligence/`, `markets/`, `portfolio/`, `risk/`, `settings/`, `sports/`, `strategies/`, `trading/`

### Pages That Need Content Preserved
- **Frankenstein** (1242 lines) → Chat interface → Control Center Chat sub-tab
- **Settings** (843 lines) → Parameter editors → Control Center Settings sub-tab  
- **Strategies** (842 lines) → Strategy toggles + decision engine → Markets Strategies sub-tab
- **Intelligence** (735 lines) → Multi-source analysis → Markets Intelligence sub-tab
- **Trading** (613 lines) → Order form → Control Center Trading sub-tab
- **Sports** (475 lines) → Odds/live/performance → Markets Sports sub-tab

### What Gets Simplified
- **Overview** (439 lines) → Becomes a better version as Live Tab
- **Risk** (268 lines) → Compact bars in Live + full editor in Control
- **Agent** (208 lines) → Superseded by Frankenstein brain controls
- **Portfolio** (201 lines) → Merged into Live tab positions + stat cards
- **AI Engine** (174 lines) → Merged into Analytics Model sub-tab
- **Backtest** (174 lines) → Becomes Analytics Backtest sub-tab
- **Alerts** (122 lines) → Becomes Markets Alerts sub-tab
- **Guide** (509 lines) → Becomes Control Center Guide sub-tab

---

## Summary: The 4-Tab Mental Model

| Tab | Emoji | Question It Answers | Update Speed |
|-----|-------|--------------------| -------------|
| **LIVE** | ⚡ | "What's happening NOW?" | Fast (8s) |
| **ANALYTICS** | 📊 | "How well is the system doing?" | Medium (30-60s) |
| **MARKETS** | 🎯 | "What opportunities exist?" | Medium (15-30s) |
| **CONTROL** | ⚙️ | "How do I configure/interact?" | On-demand |

Each tab is self-contained. You never need to leave a tab to answer the question that brought you there.
