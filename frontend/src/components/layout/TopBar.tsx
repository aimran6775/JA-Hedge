"use client";

import { useCallback, useEffect, useState } from "react";
import { IconStop, IconCircle } from "@/components/ui/Icons";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function TopBar() {
  const [connected, setConnected] = useState(false);
  const [time, setTime] = useState("");

  const checkHealth = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(3000) });
      setConnected(res.ok);
    } catch {
      setConnected(false);
    }
  }, []);

  useEffect(() => {
    checkHealth();
    const iv = setInterval(checkHealth, 15000);
    return () => clearInterval(iv);
  }, [checkHealth]);

  useEffect(() => {
    const tick = () => {
      setTime(
        new Date().toLocaleTimeString("en-US", {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hour12: false,
        }),
      );
    };
    tick();
    const iv = setInterval(tick, 1000);
    return () => clearInterval(iv);
  }, []);

  return (
    <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-white/[0.04] bg-[var(--bg-primary)]/60 backdrop-blur-xl px-6">
      <div className="flex items-center gap-4">
        <span className="text-xs font-mono text-[var(--text-muted)] tabular-nums tracking-wider">
          {time}
        </span>
        <div className="h-4 w-px bg-white/[0.06]" />
        <span className="text-xs font-medium text-[var(--text-muted)] tracking-wide uppercase">
          AI Trading Terminal
        </span>
      </div>

      <div className="flex items-center gap-4">
        {/* Kill switch */}
        <button className="group flex items-center gap-2 rounded-lg border border-loss/20 bg-loss/5 px-3 py-1.5 text-xs font-semibold text-loss/80 transition-all hover:bg-loss/10 hover:text-loss hover:border-loss/30">
          <IconStop size={14} className="group-hover:animate-pulse" />
          <span>Kill Switch</span>
        </button>

        {/* Connection status */}
        <div className="flex items-center gap-2 rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-1.5">
          <IconCircle
            size={8}
            className={connected ? "text-accent" : "text-loss animate-pulse"}
          />
          <span className="text-xs font-medium text-[var(--text-muted)]">
            {connected ? "Connected" : "Offline"}
          </span>
        </div>
      </div>
    </header>
  );
}
