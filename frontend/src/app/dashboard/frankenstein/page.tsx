"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { Card } from "@/components/ui/Card";
import { IconSend, IconRefresh, IconBrain, IconCircle, IconZap, IconTarget, IconShield, IconTrendUp, IconMarkets, IconRocket } from "@/components/ui/Icons";
import { api } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
}

const QUICK_ACTIONS = [
  { label: "System Status", query: "How is the system doing?", icon: IconZap },
  { label: "Portfolio Summary", query: "Show me my portfolio", icon: IconTarget },
  { label: "Market Analysis", query: "What markets look promising right now?", icon: IconTrendUp },
  { label: "Risk Report", query: "Give me a risk assessment", icon: IconShield },
  { label: "Top Signals", query: "What are the top AI signals?", icon: IconBrain },
  { label: "Agent Status", query: "What is the agent status?", icon: IconRocket },
];

function processInline(text: string): string {
  // Bold
  text = text.replace(/\*\*(.*?)\*\*/g, '<strong class="text-[var(--text-primary)] font-semibold">$1</strong>');
  // Inline code
  text = text.replace(/`([^`]+)`/g, '<code class="rounded bg-white/[0.06] px-1.5 py-0.5 text-xs font-mono text-accent">$1</code>');
  return text;
}

function renderMarkdown(text: string): string {
  const lines = text.split("\n");
  let html = "";
  let inList = false;

  for (const line of lines) {
    const trimmed = line.trim();

    if (trimmed.startsWith("### ")) {
      if (inList) { html += "</ul>"; inList = false; }
      html += `<h3 class="text-sm font-bold text-[var(--text-primary)] mt-3 mb-1.5">${processInline(trimmed.slice(4))}</h3>`;
    } else if (trimmed.startsWith("## ")) {
      if (inList) { html += "</ul>"; inList = false; }
      html += `<h2 class="text-base font-bold text-[var(--text-primary)] mt-3 mb-1.5">${processInline(trimmed.slice(3))}</h2>`;
    } else if (trimmed.startsWith("# ")) {
      if (inList) { html += "</ul>"; inList = false; }
      html += `<h1 class="text-lg font-bold text-[var(--text-primary)] mt-3 mb-1.5">${processInline(trimmed.slice(2))}</h1>`;
    } else if (/^[-*] /.test(trimmed)) {
      if (!inList) { html += '<ul class="space-y-1 my-1.5">'; inList = true; }
      html += `<li class="flex items-start gap-2 text-sm text-[var(--text-secondary)]"><span class="mt-1.5 h-1 w-1 rounded-full bg-accent/60 flex-shrink-0"></span><span>${processInline(trimmed.slice(2))}</span></li>`;
    } else if (trimmed.startsWith("---")) {
      if (inList) { html += "</ul>"; inList = false; }
      html += '<hr class="border-white/[0.06] my-2" />';
    } else if (trimmed === "") {
      if (inList) { html += "</ul>"; inList = false; }
      html += "<br />";
    } else {
      if (inList) { html += "</ul>"; inList = false; }
      html += `<p class="text-sm text-[var(--text-secondary)] leading-relaxed">${processInline(trimmed)}</p>`;
    }
  }
  if (inList) html += "</ul>";
  return html;
}

export default function FrankensteinPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Check health
  useEffect(() => {
    const check = async () => {
      try {
        const r = await fetch(`${API_BASE}/frankenstein/health`);
        setConnected(r.ok);
      } catch {
        setConnected(false);
      }
    };
    check();
    const iv = setInterval(check, 20000);
    return () => clearInterval(iv);
  }, []);

  // Auto scroll
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, sending]);

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || sending) return;
    const userMsg: ChatMessage = { role: "user", content: text.trim(), timestamp: new Date().toISOString() };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setSending(true);

    try {
      const body: Record<string, unknown> = { message: text.trim() };
      if (sessionId) body.session_id = sessionId;

      const res = await fetch(`${API_BASE}/frankenstein/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      if (data.session_id) setSessionId(data.session_id);

      const assistantMsg: ChatMessage = {
        role: "assistant",
        content: data.response || data.message || "No response received",
        timestamp: new Date().toISOString(),
      };
      setMessages(prev => [...prev, assistantMsg]);
    } catch (e: unknown) {
      setMessages(prev => [...prev, {
        role: "assistant",
        content: `Connection error: ${e instanceof Error ? e.message : "Unknown error"}. Check that the backend is running.`,
        timestamp: new Date().toISOString(),
      }]);
    } finally {
      setSending(false);
    }
  }, [sending, sessionId]);

  const clearChat = () => {
    setMessages([]);
    setSessionId(null);
  };

  return (
    <div className="flex flex-col h-[calc(100vh-5rem)] animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-accent/20 to-accent/5 border border-accent/20">
            <IconBrain size={20} className="text-accent" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">Frankenstein AI</h1>
            <div className="flex items-center gap-2 text-xs text-[var(--text-muted)]">
              <IconCircle size={6} className={connected ? "text-accent" : "text-loss"} />
              {connected ? "Connected" : "Offline"}
              {sessionId && <span className="ml-2 text-[var(--text-muted)]/50">Session: {sessionId.slice(0, 8)}</span>}
            </div>
          </div>
        </div>
        <button onClick={clearChat}
          className="glass rounded-xl px-4 py-2 text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-all flex items-center gap-2">
          <IconRefresh size={14} /> New Chat
        </button>
      </div>

      {/* Chat Body */}
      <div className="flex-1 glass rounded-2xl flex flex-col overflow-hidden">
        {/* Messages */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full space-y-6">
              <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-accent/15 to-accent/5 border border-accent/15">
                <IconBrain size={32} className="text-accent" />
              </div>
              <div className="text-center">
                <div className="text-lg font-bold text-[var(--text-primary)]">Frankenstein AI Brain</div>
                <p className="text-sm text-[var(--text-muted)] mt-1 max-w-sm">
                  Your unified AI trading assistant. Ask about markets, portfolio, signals, risk, or anything about the system.
                </p>
              </div>
              {/* Quick Actions */}
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 max-w-lg">
                {QUICK_ACTIONS.map((qa) => (
                  <button key={qa.label} onClick={() => sendMessage(qa.query)}
                    className="rounded-xl bg-white/[0.02] border border-white/[0.04] px-3 py-2.5 text-left transition-all hover:bg-white/[0.05] hover:border-white/[0.08] group">
                    <div className="flex items-center gap-2">
                      <qa.icon size={14} className="text-accent/70 group-hover:text-accent transition-colors" />
                      <span className="text-xs text-[var(--text-secondary)] group-hover:text-[var(--text-primary)] transition-colors">{qa.label}</span>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[80%] ${msg.role === "user" ? "" : "w-full max-w-[80%]"}`}>
                  {msg.role === "assistant" && (
                    <div className="flex items-center gap-1.5 mb-1.5">
                      <IconBrain size={12} className="text-accent" />
                      <span className="text-xs text-[var(--text-muted)] font-medium">Frankenstein</span>
                    </div>
                  )}
                  <div className={`rounded-2xl px-4 py-3 ${
                    msg.role === "user"
                      ? "bg-accent/15 border border-accent/20 text-[var(--text-primary)]"
                      : "bg-white/[0.03] border border-white/[0.06]"
                  }`}>
                    {msg.role === "user" ? (
                      <p className="text-sm">{msg.content}</p>
                    ) : (
                      <div className="prose-chat" dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }} />
                    )}
                  </div>
                  <div className="text-xs text-[var(--text-muted)]/50 mt-1 px-1">
                    {new Date(msg.timestamp).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
                  </div>
                </div>
              </div>
            ))
          )}

          {/* Typing indicator */}
          {sending && (
            <div className="flex justify-start">
              <div className="rounded-2xl bg-white/[0.03] border border-white/[0.06] px-4 py-3">
                <div className="flex items-center gap-2">
                  <IconBrain size={12} className="text-accent animate-pulse" />
                  <div className="flex gap-1">
                    <span className="h-1.5 w-1.5 rounded-full bg-accent/60 animate-bounce" style={{ animationDelay: "0ms" }} />
                    <span className="h-1.5 w-1.5 rounded-full bg-accent/60 animate-bounce" style={{ animationDelay: "150ms" }} />
                    <span className="h-1.5 w-1.5 rounded-full bg-accent/60 animate-bounce" style={{ animationDelay: "300ms" }} />
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Input */}
        <div className="border-t border-white/[0.06] p-4">
          <form onSubmit={(e) => { e.preventDefault(); sendMessage(input); }} className="flex items-center gap-3">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask Frankenstein anything..."
              disabled={sending}
              className="flex-1 rounded-xl bg-white/[0.03] border border-white/[0.06] px-4 py-3 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:border-accent/30 focus:ring-1 focus:ring-accent/10 transition-all disabled:opacity-50"
            />
            <button type="submit" disabled={sending || !input.trim()}
              className="flex h-11 w-11 items-center justify-center rounded-xl bg-accent text-white hover:bg-accent/90 transition-all disabled:opacity-30 disabled:cursor-not-allowed">
              <IconSend size={16} />
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
