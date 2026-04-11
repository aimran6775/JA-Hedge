"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";

/* ═══════════════════════════════════════════════════════════════════════
   MARKETS TAB — Simplified market opportunities view
   ═══════════════════════════════════════════════════════════════════════ */
export function MarketsTab() {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [rejections, setRejections] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const rej = await api.frankenstein.debugRejections().catch(() => null);
      
      if (rej) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const raw = rej as any;
        const candList = raw?.candidates ?? raw?.markets ?? [];
        const summary = raw?.summary ?? raw?.rejection_reasons ?? {};
        
        // Transform candidates
        const transformed = (Array.isArray(candList) ? candList : []).map((c: RawCandidate) => ({
          ticker: c.ticker,
          title: c.title || prettifyTicker(c.ticker),
          stage: c.stage || c.filter_stage || "unknown",
          reason: c.reason || c.rejection_reason || null,
          confidence: c.confidence || c.score || 0,
          edge: c.edge || 0,
          prob: c.predicted_prob || c.prob || null,
          category: c.category || "unknown",
        }));
        
        setCandidates(transformed);
        setRejections(summary);
      }
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const iv = setInterval(fetchData, 30000);
    return () => clearInterval(iv);
  }, [fetchData]);

  // Group candidates by stage
  const grouped = candidates.reduce((acc, c) => {
    const stage = c.stage || "other";
    if (!acc[stage]) acc[stage] = [];
    acc[stage].push(c);
    return acc;
  }, {} as Record<string, Candidate[]>);

  const stageOrder = ["executed", "pending", "qualified", "filtered", "rejected"];
  const sortedStages = Object.keys(grouped).sort((a, b) => {
    const ai = stageOrder.indexOf(a);
    const bi = stageOrder.indexOf(b);
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
  });

  if (loading && candidates.length === 0) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="space-y-4 p-1">
      {error && (
        <div className="rounded-lg border border-loss/30 bg-loss/10 p-3 text-sm text-loss">{error}</div>
      )}

      {/* Summary */}
      <div className="rounded-xl glass p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium text-secondary">Market Scanner</h3>
          <button 
            onClick={fetchData}
            className="text-xs text-accent hover:underline"
          >
            Refresh
          </button>
        </div>
        <div className="grid grid-cols-4 gap-3">
          <StatBox label="Scanned" value={candidates.length.toString()} />
          <StatBox label="Qualified" value={(grouped["qualified"]?.length || 0).toString()} color="accent" />
          <StatBox label="Executed" value={(grouped["executed"]?.length || 0).toString()} color="accent" />
          <StatBox label="Rejected" value={(grouped["rejected"]?.length || grouped["filtered"]?.length || 0).toString()} color="muted" />
        </div>
      </div>

      {/* Rejection Reasons Summary */}
      {Object.keys(rejections).length > 0 && (
        <details className="rounded-xl glass p-4">
          <summary className="text-sm font-medium text-secondary cursor-pointer hover:text-primary">
            Rejection Breakdown ({Object.values(rejections).reduce((a, b) => a + b, 0)} total)
          </summary>
          <div className="mt-3 space-y-1.5">
            {Object.entries(rejections)
              .sort(([, a], [, b]) => b - a)
              .slice(0, 10)
              .map(([reason, count]) => (
                <div key={reason} className="flex justify-between text-xs">
                  <span className="text-muted truncate">{formatReason(reason)}</span>
                  <span className="text-primary tabular-nums">{count}</span>
                </div>
              ))}
          </div>
        </details>
      )}

      {/* Candidates by Stage */}
      {sortedStages.map((stage) => (
        <div key={stage} className="rounded-xl glass p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-secondary capitalize flex items-center gap-2">
              <StageBadge stage={stage} />
              {stage}
            </h3>
            <span className="text-xs text-muted">{grouped[stage].length} markets</span>
          </div>
          <div className="space-y-1.5 max-h-[300px] overflow-y-auto">
            {grouped[stage].slice(0, 20).map((c, i) => (
              <CandidateRow key={c.ticker + i} candidate={c} />
            ))}
          </div>
        </div>
      ))}

      {candidates.length === 0 && !loading && (
        <div className="rounded-xl glass p-8 text-center">
          <div className="text-muted text-sm">No candidates in current scan</div>
        </div>
      )}
    </div>
  );
}

/* ── Components ────────────────────────────────────────────────────────── */

interface Candidate {
  ticker: string;
  title: string;
  stage: string;
  reason: string | null;
  confidence: number;
  edge: number;
  prob: number | null;
  category: string;
}

interface RawCandidate {
  ticker: string;
  title?: string;
  stage?: string;
  filter_stage?: string;
  reason?: string;
  rejection_reason?: string;
  confidence?: number;
  score?: number;
  edge?: number;
  predicted_prob?: number;
  prob?: number;
  category?: string;
}

function StatBox({ label, value, color }: { label: string; value: string; color?: "accent" | "muted" }) {
  const colorClass = color === "accent" ? "text-accent" : color === "muted" ? "text-muted" : "text-primary";
  return (
    <div>
      <div className="text-[10px] text-muted uppercase tracking-wider mb-1">{label}</div>
      <div className={`text-lg font-semibold tabular-nums ${colorClass}`}>{value}</div>
    </div>
  );
}

function StageBadge({ stage }: { stage: string }) {
  const colors: Record<string, string> = {
    executed: "bg-accent/20 text-accent",
    pending: "bg-amber-500/20 text-amber-400",
    qualified: "bg-sky-500/20 text-sky-400",
    filtered: "bg-white/10 text-muted",
    rejected: "bg-loss/20 text-loss",
  };
  
  return (
    <span className={`inline-flex h-2 w-2 rounded-full ${colors[stage]?.split(" ")[0] || "bg-white/10"}`} />
  );
}

function CandidateRow({ candidate }: { candidate: Candidate }) {
  const c = candidate;
  
  return (
    <div className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2">
      <div className="min-w-0 flex-1">
        <div className="text-sm text-primary truncate">{c.title}</div>
        <div className="text-[10px] text-muted truncate">
          {c.category}
          {c.reason && <span className="ml-1">· {c.reason}</span>}
        </div>
      </div>
      <div className="flex items-center gap-3 flex-shrink-0 ml-2">
        {c.confidence > 0 && (
          <div className="text-xs">
            <span className="text-muted">Conf </span>
            <span className="text-primary tabular-nums">{(c.confidence * 100).toFixed(0)}%</span>
          </div>
        )}
        {c.edge > 0 && (
          <div className="text-xs">
            <span className="text-muted">Edge </span>
            <span className="text-accent tabular-nums">+{(c.edge * 100).toFixed(1)}%</span>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Utilities ─────────────────────────────────────────────────────────── */

function prettifyTicker(ticker: string): string {
  return ticker
    .replace(/^KX/, "")
    .replace(/-\d{2}[A-Z]{3}\d{2}.*$/, "")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/-/g, " ")
    .slice(0, 35);
}

function formatReason(reason: string): string {
  return reason
    .replace(/_/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .toLowerCase()
    .replace(/^./, (c) => c.toUpperCase());
}
