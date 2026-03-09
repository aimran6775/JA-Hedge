"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/Card";
import { api, type HealthStatus } from "@/lib/api";

export default function SettingsPage() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const h = await api.health();
        setHealth(h);
      } catch {
        // health endpoint may not be available
      } finally {
        setLoading(false);
      }
    };
    load();
    const interval = setInterval(load, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <h1 className="text-2xl font-bold text-white">Settings</h1>

      {/* Connection Status */}
      <Card title="System Status">
        <div className="space-y-2">
          {loading ? (
            <div className="py-4 text-center text-sm text-[var(--muted)]">Connecting to backend...</div>
          ) : !health ? (
            <div className="py-4 text-center text-sm text-red-400">❌ Cannot reach backend at localhost:8000</div>
          ) : (
            <>
              <div className="flex items-center justify-between rounded-md bg-white/5 px-3 py-2 text-sm">
                <span className="text-white">Backend Status</span>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-[var(--muted)]">{health.status}</span>
                  <span className={`h-2 w-2 rounded-full ${health.status === "ok" ? "bg-green-500" : "bg-red-500"}`} />
                </div>
              </div>
              <div className="flex items-center justify-between rounded-md bg-white/5 px-3 py-2 text-sm">
                <span className="text-white">Trading Mode</span>
                <span className={`rounded px-2 py-0.5 text-xs font-medium ${
                  health.mode === "demo" ? "bg-yellow-500/20 text-yellow-400" : "bg-red-500/20 text-red-400"
                }`}>
                  {health.mode?.toUpperCase() ?? "UNKNOWN"}
                </span>
              </div>
              <div className="flex items-center justify-between rounded-md bg-white/5 px-3 py-2 text-sm">
                <span className="text-white">API Keys</span>
                <span className={`text-xs ${health.has_api_keys ? "text-green-400" : "text-red-400"}`}>
                  {health.has_api_keys ? "✅ Configured" : "❌ Missing"}
                </span>
              </div>
              <div className="flex items-center justify-between rounded-md bg-white/5 px-3 py-2 text-sm">
                <span className="text-white">Version</span>
                <span className="text-xs text-[var(--muted)]">{health.version ?? "—"}</span>
              </div>

              {/* Components */}
              {health.components && Object.keys(health.components).length > 0 && (
                <div className="mt-3 border-t border-white/10 pt-3">
                  <h4 className="text-xs font-medium text-[var(--muted)] uppercase tracking-wider mb-2">Components</h4>
                  {Object.entries(health.components).map(([name, status]) => (
                    <div key={name} className="flex items-center justify-between rounded-md bg-white/5 px-3 py-2 text-sm mb-1">
                      <span className="text-white">{name}</span>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-[var(--muted)]">{status}</span>
                        <span className={`h-2 w-2 rounded-full ${
                          status === "ready" || status === "ok" || status === "connected" || status === "loaded"
                            ? "bg-green-500"
                            : status === "degraded" || status === "warning"
                            ? "bg-yellow-500"
                            : "bg-red-500"
                        }`} />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </Card>

      {/* Configuration Info */}
      <Card title="Configuration">
        <div className="space-y-3">
          <div className="rounded-md bg-white/5 p-3 text-sm">
            <h4 className="font-medium text-white">Kalshi Demo API</h4>
            <p className="mt-1 text-xs text-[var(--muted)]">
              This platform is connected to Kalshi&apos;s demo environment. All trades use simulated money — 
              no real funds are at risk. API credentials are configured in the backend .env file.
            </p>
          </div>
          <div className="rounded-md bg-white/5 p-3 text-sm">
            <h4 className="font-medium text-white">Backend URL</h4>
            <p className="mt-1 text-xs text-[var(--muted)] font-mono">
              {process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}
            </p>
          </div>
          <div className="rounded-md bg-white/5 p-3 text-sm">
            <h4 className="font-medium text-white">Paper Trading</h4>
            <p className="mt-1 text-xs text-[var(--muted)]">
              Orders placed through the Trading page are sent to Kalshi&apos;s demo exchange. 
              You start with demo balance and can practice strategies risk-free.
            </p>
          </div>
        </div>
      </Card>

      {/* Quick Actions */}
      <Card title="Quick Actions">
        <div className="space-y-3">
          <div className="flex items-center justify-between rounded-md border border-yellow-500/20 bg-yellow-500/5 px-4 py-3">
            <div>
              <div className="text-sm font-medium text-white">Cancel All Open Orders</div>
              <div className="text-xs text-[var(--muted)]">Cancels all pending limit orders on the exchange</div>
            </div>
            <button
              onClick={async () => {
                try {
                  await api.orders.cancelAll();
                  alert("All orders cancelled");
                } catch {
                  alert("Failed to cancel orders");
                }
              }}
              className="rounded-md border border-yellow-500/30 px-3 py-1.5 text-xs font-medium text-yellow-400 hover:bg-yellow-500/10"
            >
              Cancel All
            </button>
          </div>
        </div>
      </Card>
    </div>
  );
}
