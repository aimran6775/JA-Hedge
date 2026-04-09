/* ── Shared Dashboard Utilities ────────────────────────────────────────
   Centralised helpers used by all dashboard tabs.
   Import from "@/lib/dashboard-utils" — never duplicate these.          */

/** Colour class for P&L / signed number */
export function pnlColor(v: number): string {
  return v > 0 ? "text-accent" : v < 0 ? "text-loss" : "text-[var(--text-muted)]";
}

/** Format number → signed dollar string: +$3.14 / -$2.71 / $0.00 */
export function pnlSign(v: number): string {
  if (v > 0) return `+$${v.toFixed(2)}`;
  if (v < 0) return `-$${Math.abs(v).toFixed(2)}`;
  return "$0.00";
}

/** Prettify a Kalshi ticker for human display */
export function prettifyTicker(ticker: string): string {
  let base = ticker.split("-")[0] ?? ticker;
  base = base.replace(/^(KX|INX|CPI|GDP|FED|NFL|NBA|MLB|NHL|NCAA)/, "$1 ");
  base = base.replace(/([a-z])([A-Z])/g, "$1 $2");
  return base.replace(/\s+/g, " ").trim() || ticker;
}

/** Relative time ago string: "now" / "5m" / "2h" / "3d" */
export function timeAgo(ts: string | number | null): string {
  if (!ts) return "--";
  const epoch = typeof ts === "number" ? ts * 1000 : new Date(ts).getTime();
  if (isNaN(epoch)) return "--";
  const m = Math.round((Date.now() - epoch) / 60000);
  if (m < 1) return "now";
  if (m < 60) return `${m}m`;
  if (m < 1440) return `${Math.round(m / 60)}h`;
  return `${Math.round(m / 1440)}d`;
}

/** Format seconds to human uptime: "2h 14m" */
export function fmtUptime(s: number): string {
  if (!s || s < 0) return "--";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

/** Format cents to dollar string: 5000 → "$50.00" */
export function centsToDollars(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

/** Category emoji */
export function categoryEmoji(cat: string): string {
  const map: Record<string, string> = {
    sports: "🏀",
    politics: "🏛️",
    crypto: "₿",
    finance: "📈",
    weather: "🌦️",
    entertainment: "🎬",
    science: "🔬",
    social_media: "📱",
    culture: "🎭",
    current_events: "📰",
    economics: "💰",
    tech: "💻",
  };
  return map[cat.toLowerCase()] ?? "📊";
}
