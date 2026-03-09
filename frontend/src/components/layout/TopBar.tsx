"use client";

export function TopBar() {
  return (
    <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-[var(--card-border)] bg-[var(--card)]/80 px-6 backdrop-blur-sm">
      <div className="flex items-center gap-4">
        <h2 className="text-sm font-medium text-white">AI Trading Dashboard</h2>
      </div>

      <div className="flex items-center gap-4">
        {/* Kill switch */}
        <button className="flex items-center gap-2 rounded-md border border-loss/30 bg-loss/10 px-3 py-1.5 text-xs font-medium text-loss transition-colors hover:bg-loss/20">
          🛑 Kill Switch
        </button>

        {/* Connection status */}
        <div className="flex items-center gap-2 text-xs text-[var(--muted)]">
          <span className="h-2 w-2 rounded-full bg-green-500" />
          Connected
        </div>
      </div>
    </header>
  );
}
