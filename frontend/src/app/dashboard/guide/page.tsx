"use client";

import { useState } from "react";
import { IconBrain, IconBook, IconSports, IconShield, IconSettings, IconTarget, IconTrendUp, IconRocket, IconZap } from "@/components/ui/Icons";

/* ─── Sections ─────────────────────────────────────────────── */

const SECTIONS = [
  { id: "overview",      label: "What is JA Hedge?",    icon: "🏠" },
  { id: "kalshi",        label: "What is Kalshi?",       icon: "📈" },
  { id: "paper",         label: "Paper Trading",         icon: "📝" },
  { id: "frankenstein",  label: "Frankenstein AI",       icon: "🧠" },
  { id: "sports",        label: "Sports vs All Markets", icon: "🏀" },
  { id: "dashboard",     label: "Reading the Dashboard", icon: "📊" },
  { id: "trades",        label: "How Trades Work",       icon: "⚡" },
  { id: "controls",      label: "Controls & Settings",   icon: "⚙️" },
  { id: "ml",            label: "The AI / ML Engine",    icon: "🤖" },
  { id: "faq",           label: "FAQ",                   icon: "❓" },
] as const;

type SectionId = (typeof SECTIONS)[number]["id"];

/* ─── Reusable card ───────────────────────────────────────── */

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`glass rounded-2xl p-6 ${className}`}>{children}</div>;
}

function H2({ children }: { children: React.ReactNode }) {
  return <h2 className="text-xl font-bold mb-4 text-[var(--text-primary)]">{children}</h2>;
}

function P({ children }: { children: React.ReactNode }) {
  return <p className="text-[var(--text-secondary)] leading-relaxed mb-3">{children}</p>;
}

function Bullet({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2 text-[var(--text-secondary)] leading-relaxed">
      <span className="text-accent mt-1 shrink-0">•</span>
      <span>{children}</span>
    </li>
  );
}

function Step({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3 mb-3">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent/20 text-accent text-xs font-bold">{n}</span>
      <div className="text-[var(--text-secondary)] leading-relaxed">{children}</div>
    </div>
  );
}

function Callout({ emoji, children }: { emoji: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3 rounded-xl bg-accent/5 border border-accent/20 p-4 mb-4">
      <span className="text-lg shrink-0">{emoji}</span>
      <div className="text-sm text-[var(--text-secondary)] leading-relaxed">{children}</div>
    </div>
  );
}

/* ─── Section content ─────────────────────────────────────── */

function SectionOverview() {
  return (
    <Card>
      <H2>What is JA Hedge?</H2>
      <P>
        JA Hedge is an <strong className="text-[var(--text-primary)]">AI-powered prediction-market trading platform</strong> built
        on top of <strong className="text-[var(--text-primary)]">Kalshi</strong>, a U.S.-regulated exchange where you bet on
        real-world events — like &quot;Will the Eagles beat the Chiefs?&quot; or &quot;Will Bitcoin hit $100 000 by June?&quot;
      </P>
      <P>
        Instead of making every trade yourself, JA Hedge runs <strong className="text-[var(--text-primary)]">Frankenstein</strong> — a continuously-learning
        AI brain that scans live markets, builds ML predictions, applies risk rules, and executes trades automatically while you watch from this dashboard.
      </P>
      <Callout emoji="🔒">
        <strong>It starts in Paper Trading mode.</strong> No real money is at risk. Frankenstein trades a simulated $10,000 balance so you can
        see exactly how it works before ever connecting real funds.
      </Callout>
      <ul className="space-y-2 mt-4">
        <Bullet><strong>Backend:</strong> FastAPI server running the AI, risk engine, and Kalshi connection.</Bullet>
        <Bullet><strong>Frontend:</strong> This Next.js dashboard you&apos;re looking at right now.</Bullet>
        <Bullet><strong>AI Brain:</strong> Frankenstein — XGBoost ML model with 60 engineered features.</Bullet>
      </ul>
    </Card>
  );
}

function SectionKalshi() {
  return (
    <Card>
      <H2>What is Kalshi?</H2>
      <P>
        <strong className="text-[var(--text-primary)]">Kalshi</strong> is a CFTC-regulated prediction market exchange based in the US.
        Think of it like a stock exchange, but instead of shares in a company, you buy <strong className="text-[var(--text-primary)]">contracts</strong> on
        the outcome of real-world events.
      </P>

      <div className="rounded-xl bg-white/[0.02] border border-white/5 p-4 mb-4">
        <p className="text-sm font-semibold text-[var(--text-primary)] mb-2">Example contract</p>
        <p className="text-sm text-[var(--text-secondary)] mb-1">&quot;Will the Lakers win tonight?&quot;</p>
        <p className="text-xs text-[var(--text-muted)]">
          You can buy <strong className="text-accent">Yes</strong> at 62¢ → if they win, you get $1.00 (profit: 38¢).<br />
          You can buy <strong className="text-loss">No</strong> at 38¢ → if they lose, you get $1.00 (profit: 62¢).
        </p>
      </div>

      <ul className="space-y-2">
        <Bullet>Contracts trade between <strong>1¢ and 99¢</strong>. The price reflects the market&apos;s implied probability.</Bullet>
        <Bullet>When the event resolves, winning contracts pay out <strong>$1.00</strong>; losing ones pay <strong>$0</strong>.</Bullet>
        <Bullet>You can exit early by selling your contract back on the market.</Bullet>
        <Bullet>JA Hedge connects to Kalshi&apos;s API to read live prices and place orders on your behalf.</Bullet>
      </ul>
    </Card>
  );
}

function SectionPaper() {
  return (
    <Card>
      <H2>Paper Trading — No Real Money</H2>
      <P>
        By default, JA Hedge runs in <strong className="text-[var(--text-primary)]">Paper Trading mode</strong>.
        This means every trade Frankenstein makes is <em>simulated</em>. You start with a virtual <strong className="text-accent">$10,000</strong> balance.
      </P>
      <ul className="space-y-2 mb-4">
        <Bullet>All buy/sell orders hit a local simulator instead of Kalshi&apos;s real order book.</Bullet>
        <Bullet>Your balance, P&L, and trade history are all tracked just like real trading — but no actual money moves.</Bullet>
        <Bullet>The yellow <strong className="text-[var(--warning)]">PAPER</strong> badge in the header confirms you&apos;re in paper mode.</Bullet>
      </ul>
      <Callout emoji="🔄">
        <strong>You can reset your simulation</strong> at any time from <strong>Settings → Simulation → Reset Simulation</strong>.
        This wipes the paper balance back to $10,000 and clears trade history so you can start fresh.
      </Callout>
    </Card>
  );
}

function SectionFrankenstein() {
  return (
    <Card>
      <H2>Frankenstein AI — The Brain</H2>
      <P>
        Frankenstein is the AI &quot;brain&quot; that runs the show. It&apos;s a continuously-running loop that:
      </P>
      <Step n={1}>
        <strong>Scans</strong> all available Kalshi markets (or just sports markets, depending on your setting).
      </Step>
      <Step n={2}>
        <strong>Filters</strong> candidates — removing low-volume, illiquid, or already-settled markets.
      </Step>
      <Step n={3}>
        <strong>Runs ML predictions</strong> — a trained XGBoost model scores each market using 60 engineered features.
      </Step>
      <Step n={4}>
        <strong>Applies risk checks</strong> — position limits, portfolio heat, drawdown guards, maximum bet sizes.
      </Step>
      <Step n={5}>
        <strong>Executes trades</strong> — if a signal passes all checks, Frankenstein places a Yes or No order.
      </Step>
      <Step n={6}>
        <strong>Learns &amp; evolves</strong> — after trades resolve, it retrains its model and adapts strategy weights.
      </Step>

      <Callout emoji="💡">
        <strong>Starting &amp; stopping:</strong> Go to <strong>Frankenstein AI → Overview</strong> and click the big
        START or STOP button. You can also <strong>Pause</strong> (freeze scanning) or <strong>Resume</strong> without fully stopping.
      </Callout>
    </Card>
  );
}

function SectionSports() {
  return (
    <Card>
      <H2>Sports-Only vs All Markets</H2>
      <P>
        Kalshi has hundreds of markets across many categories — sports, politics, economics, weather, crypto, and more.
        JA Hedge lets you choose which ones Frankenstein trades.
      </P>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
        <div className="rounded-xl bg-orange-500/5 border border-orange-500/20 p-4">
          <p className="text-sm font-semibold text-orange-400 mb-2">🏀 Sports Only (Default)</p>
          <ul className="space-y-1 text-xs text-[var(--text-secondary)]">
            <li>• NFL, NBA, MLB, NHL, soccer, etc.</li>
            <li>• Enhanced with Vegas odds data when available</li>
            <li>• Generally faster resolution (games end today/tonight)</li>
            <li>• Recommended for beginners</li>
          </ul>
        </div>
        <div className="rounded-xl bg-blue-500/5 border border-blue-500/20 p-4">
          <p className="text-sm font-semibold text-blue-400 mb-2">🌐 All Markets</p>
          <ul className="space-y-1 text-xs text-[var(--text-secondary)]">
            <li>• Everything: politics, crypto, weather, economics…</li>
            <li>• More opportunities but harder to predict</li>
            <li>• Events may take days/weeks to resolve</li>
            <li>• For advanced users</li>
          </ul>
        </div>
      </div>

      <P><strong className="text-[var(--text-primary)]">How to switch:</strong></P>
      <ul className="space-y-2 mb-4">
        <Bullet>
          <strong>Quick toggle:</strong> On the <strong>Overview</strong> page, click the <strong className="text-orange-400">🏀 Sports Only</strong> or{" "}
          <strong className="text-blue-400">🌐 All Markets</strong> pill in the top bar. One click switches modes.
        </Bullet>
        <Bullet>
          <strong>Settings page:</strong> Go to <strong>Settings → Brain</strong> and flip the &quot;Sports Only Mode&quot; toggle.
        </Bullet>
      </ul>
    </Card>
  );
}

function SectionDashboard() {
  return (
    <Card>
      <H2>Reading the Dashboard</H2>
      <P>Here&apos;s what each section of the <strong className="text-[var(--text-primary)]">Overview</strong> page shows:</P>

      <div className="space-y-4">
        <div className="rounded-xl bg-white/[0.02] border border-white/5 p-4">
          <p className="text-sm font-semibold text-[var(--text-primary)] mb-1">📊 Top Header Bar</p>
          <ul className="space-y-1 text-xs text-[var(--text-secondary)]">
            <li>• <strong>Brain Status</strong> — Green &quot;TRADING&quot; = actively scanning and placing trades. Gray &quot;SLEEPING&quot; = stopped.</li>
            <li>• <strong>Market Mode</strong> — Orange &quot;Sports Only&quot; or Blue &quot;All Markets&quot; (clickable to toggle).</li>
            <li>• <strong>Paper / Live</strong> — Yellow &quot;PAPER&quot; = simulated. Green &quot;LIVE&quot; = real money.</li>
          </ul>
        </div>

        <div className="rounded-xl bg-white/[0.02] border border-white/5 p-4">
          <p className="text-sm font-semibold text-[var(--text-primary)] mb-1">💰 Stat Cards (top row)</p>
          <ul className="space-y-1 text-xs text-[var(--text-secondary)]">
            <li>• <strong>Balance</strong> — Your current portfolio value (starts at $10,000 in paper mode).</li>
            <li>• <strong>Total P&L</strong> — How much you&apos;re up or down overall. Green = profit, red = loss.</li>
            <li>• <strong>Open Positions</strong> — How many active bets you currently hold.</li>
            <li>• <strong>Win Rate</strong> — Percentage of resolved trades that made money.</li>
            <li>• <strong>Total Scans</strong> — How many market-scan cycles the AI has completed.</li>
            <li>• <strong>Risk Score</strong> — Current portfolio risk level (0–100, lower = safer).</li>
          </ul>
        </div>

        <div className="rounded-xl bg-white/[0.02] border border-white/5 p-4">
          <p className="text-sm font-semibold text-[var(--text-primary)] mb-1">🧠 Frankenstein Brain Card</p>
          <ul className="space-y-1 text-xs text-[var(--text-secondary)]">
            <li>• Shows model accuracy, generation (version), total trades, and current confidence.</li>
            <li>• <strong>START / STOP</strong> button to control the AI.</li>
          </ul>
        </div>

        <div className="rounded-xl bg-white/[0.02] border border-white/5 p-4">
          <p className="text-sm font-semibold text-[var(--text-primary)] mb-1">📋 Recent AI Trades</p>
          <ul className="space-y-1 text-xs text-[var(--text-secondary)]">
            <li>• The latest trades Frankenstein placed, with market name, side (Yes/No), price, and outcome.</li>
            <li>• Click any trade row to see full details.</li>
          </ul>
        </div>
      </div>
    </Card>
  );
}

function SectionTrades() {
  return (
    <Card>
      <H2>How Trades Work</H2>
      <P>
        When Frankenstein finds a market it likes, here&apos;s the lifecycle of a trade:
      </P>

      <div className="relative border-l-2 border-accent/30 ml-3 pl-6 space-y-4 mb-4">
        <div>
          <p className="text-sm font-semibold text-accent">1. Signal Detected</p>
          <p className="text-xs text-[var(--text-secondary)]">The ML model scores the market and finds a &quot;Yes&quot; or &quot;No&quot; signal above the confidence threshold.</p>
        </div>
        <div>
          <p className="text-sm font-semibold text-accent">2. Risk Check</p>
          <p className="text-xs text-[var(--text-secondary)]">The risk manager checks position limits, portfolio heat, daily loss, and drawdown rules.</p>
        </div>
        <div>
          <p className="text-sm font-semibold text-accent">3. Order Placed</p>
          <p className="text-xs text-[var(--text-secondary)]">If everything passes, an order is sent (paper or live). You&apos;ll see it appear in the trades list.</p>
        </div>
        <div>
          <p className="text-sm font-semibold text-accent">4. Position Held</p>
          <p className="text-xs text-[var(--text-secondary)]">The contract sits in your portfolio. Price moves in real-time. Unrealized P&L updates accordingly.</p>
        </div>
        <div>
          <p className="text-sm font-semibold text-accent">5. Resolution</p>
          <p className="text-xs text-[var(--text-secondary)]">When the event happens, the contract resolves: $1.00 if you were right, $0 if wrong. Profit or loss is booked.</p>
        </div>
      </div>

      <Callout emoji="📌">
        <strong>Frankenstein can also exit early</strong> by selling a position before the event resolves — for example, if the market price moved favorably and it wants to lock in profit.
      </Callout>
    </Card>
  );
}

function SectionControls() {
  return (
    <Card>
      <H2>Controls &amp; Settings</H2>
      <P>Everything you can control from the dashboard:</P>

      <div className="space-y-3 mb-4">
        <div className="rounded-xl bg-white/[0.02] border border-white/5 p-4">
          <p className="text-sm font-semibold text-[var(--text-primary)] mb-1">🟢 Start / Stop</p>
          <p className="text-xs text-[var(--text-secondary)]">
            Found on <strong>Overview</strong> and <strong>Frankenstein AI → Overview</strong>. Start begins the scan-trade loop.
            Stop halts it entirely. Pause/Resume freezes scanning without fully shutting down.
          </p>
        </div>

        <div className="rounded-xl bg-white/[0.02] border border-white/5 p-4">
          <p className="text-sm font-semibold text-[var(--text-primary)] mb-1">🏀 Market Mode</p>
          <p className="text-xs text-[var(--text-secondary)]">
            Toggle between Sports Only and All Markets from the Overview header pill or Settings → Brain.
          </p>
        </div>

        <div className="rounded-xl bg-white/[0.02] border border-white/5 p-4">
          <p className="text-sm font-semibold text-[var(--text-primary)] mb-1">🔄 Reset Simulation</p>
          <p className="text-xs text-[var(--text-secondary)]">
            Settings → Simulation → &quot;Reset Paper Trading Simulation&quot;. Resets balance to $10,000 and clears history.
          </p>
        </div>

        <div className="rounded-xl bg-white/[0.02] border border-white/5 p-4">
          <p className="text-sm font-semibold text-[var(--text-primary)] mb-1">🎚️ Strategy Presets</p>
          <p className="text-xs text-[var(--text-secondary)]">
            Settings → Strategy. Choose <strong>Conservative</strong>, <strong>Balanced</strong>, <strong>Aggressive</strong>, or <strong>YOLO</strong>.
            Each preset tunes risk limits, bet sizes, and confidence thresholds differently.
          </p>
        </div>

        <div className="rounded-xl bg-white/[0.02] border border-white/5 p-4">
          <p className="text-sm font-semibold text-[var(--text-primary)] mb-1">🧠 Brain Settings</p>
          <p className="text-xs text-[var(--text-secondary)]">
            Settings → Brain. Fine-tune scan interval, confidence threshold, sports-only mode, and risk parameters.
          </p>
        </div>
      </div>
    </Card>
  );
}

function SectionML() {
  return (
    <Card>
      <H2>The AI / ML Engine</H2>
      <P>
        Frankenstein uses an <strong className="text-[var(--text-primary)]">XGBoost</strong> gradient-boosted tree model trained on
        60 engineered features. Here&apos;s a simplified breakdown:
      </P>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
        {[
          { cat: "Price & Volume", examples: "Current price, 24h volume, bid/ask spread, liquidity depth", count: 12 },
          { cat: "Technical Indicators", examples: "RSI, MACD, Bollinger Bands, price momentum", count: 10 },
          { cat: "Time Features", examples: "Hours to close, day of week, session timing", count: 8 },
          { cat: "Market Microstructure", examples: "Order book imbalance, trade velocity, price impact", count: 10 },
          { cat: "Cross-Market Signals", examples: "Correlation clusters, sector momentum, relative value", count: 8 },
          { cat: "Sports / Vegas (Phase 5)", examples: "Vegas odds, line movement, sharp money signals, public vs sharp %", count: 12 },
        ].map((g) => (
          <div key={g.cat} className="rounded-xl bg-white/[0.02] border border-white/5 p-3">
            <p className="text-xs font-semibold text-accent mb-1">{g.cat} <span className="text-[var(--text-muted)] font-normal">({g.count} features)</span></p>
            <p className="text-xs text-[var(--text-muted)]">{g.examples}</p>
          </div>
        ))}
      </div>

      <P>
        The model is retrained periodically (configurable) as new trades resolve, so it continuously adapts to changing market conditions.
        You can see the current model accuracy and generation number on the Frankenstein AI page.
      </P>

      <Callout emoji="🎓">
        You don&apos;t need to understand the ML to use JA Hedge — just start Frankenstein and let it do its thing.
        The features above are what it considers behind the scenes.
      </Callout>
    </Card>
  );
}

function SectionFAQ() {
  const faqs = [
    {
      q: "Is this using real money?",
      a: "Not by default. JA Hedge starts in Paper Trading mode with a simulated $10,000 balance. You'd need to explicitly configure Kalshi API keys and disable paper mode to trade real money.",
    },
    {
      q: "What kind of events can it trade?",
      a: "Anything on Kalshi: sports outcomes, economic indicators, weather events, politics, crypto prices, and more. By default it's set to Sports Only, but you can switch to All Markets.",
    },
    {
      q: "How much can I lose?",
      a: "In paper mode, nothing real. The max loss per contract is the price you paid (e.g., buy Yes at 60¢, max loss = 60¢). Risk controls limit total exposure.",
    },
    {
      q: "How often does Frankenstein trade?",
      a: "It scans every 30–90 seconds (configurable). Whether it actually trades depends on finding opportunities that pass the confidence and risk thresholds.",
    },
    {
      q: "Can I manually place trades?",
      a: "Yes! Use the Trading page to place manual orders on any Kalshi market, independent of Frankenstein.",
    },
    {
      q: "What are the strategy presets?",
      a: "Conservative (small bets, tight stops), Balanced (medium risk/reward), Aggressive (bigger positions), and YOLO (maximum risk, maximum reward). Pick from Settings → Strategy.",
    },
    {
      q: "How do I reset everything?",
      a: "Go to Settings → Simulation → Reset Simulation. This wipes paper balance back to $10,000 and clears all trade history.",
    },
    {
      q: "What if the backend goes offline?",
      a: "The dashboard will show 'Offline' in the header. Frankenstein stops trading when disconnected. No phantom trades happen.",
    },
    {
      q: "Where can I see trade details?",
      a: "Go to Frankenstein AI → Trades tab. Click any trade row to see the full detail popup including price, side, fees, and timestamps.",
    },
  ];

  return (
    <Card>
      <H2>Frequently Asked Questions</H2>
      <div className="space-y-4">
        {faqs.map((f, i) => (
          <div key={i} className="rounded-xl bg-white/[0.02] border border-white/5 p-4">
            <p className="text-sm font-semibold text-[var(--text-primary)] mb-1">{f.q}</p>
            <p className="text-xs text-[var(--text-secondary)]">{f.a}</p>
          </div>
        ))}
      </div>
    </Card>
  );
}

/* ─── Section map ─────────────────────────────────────────── */

const SECTION_COMPONENTS: Record<SectionId, () => React.ReactNode> = {
  overview:     SectionOverview,
  kalshi:       SectionKalshi,
  paper:        SectionPaper,
  frankenstein: SectionFrankenstein,
  sports:       SectionSports,
  dashboard:    SectionDashboard,
  trades:       SectionTrades,
  controls:     SectionControls,
  ml:           SectionML,
  faq:          SectionFAQ,
};

/* ─── Page ────────────────────────────────────────────────── */

export default function GuidePage() {
  const [active, setActive] = useState<SectionId>("overview");

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-[var(--text-primary)] flex items-center gap-3">
          <IconBook size={26} className="text-accent" />
          How It Works
        </h1>
        <p className="text-sm text-[var(--text-muted)] mt-1">
          A beginner-friendly guide to understanding and operating JA Hedge.
        </p>
      </div>

      <div className="flex flex-col lg:flex-row gap-6">
        {/* Side nav */}
        <nav className="lg:w-56 shrink-0">
          <div className="glass rounded-2xl p-3 space-y-1 lg:sticky lg:top-6">
            {SECTIONS.map((s) => (
              <button
                key={s.id}
                onClick={() => setActive(s.id)}
                className={`w-full text-left flex items-center gap-2 rounded-xl px-3 py-2 text-sm transition-all ${
                  active === s.id
                    ? "bg-accent/10 text-accent font-semibold"
                    : "text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-white/[0.03]"
                }`}
              >
                <span className="text-base">{s.icon}</span>
                <span>{s.label}</span>
              </button>
            ))}
          </div>
        </nav>

        {/* Content */}
        <div className="flex-1 min-w-0">
          {SECTION_COMPONENTS[active]()}
        </div>
      </div>
    </div>
  );
}
