"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/* ── Types ──────────────────────────────────────────────────────── */

interface ChatMessage {
  role: "user" | "frankenstein";
  content: string;
  timestamp: number;
  time_human: string;
  data?: Record<string, unknown> | null;
}

interface FrankensteinHealth {
  alive: boolean;
  trading: boolean;
  paused: boolean;
  generation: number;
  model_version: string;
  total_trades: number;
}

/* ── API ────────────────────────────────────────────────────────── */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function frankFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}/api/frankenstein${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Error ${res.status}`);
  }
  return res.json();
}

/* ── Markdown-lite renderer ─────────────────────────────────────── */

function renderMarkdown(text: string) {
  // Split into lines and process
  const lines = text.split("\n");
  const elements: JSX.Element[] = [];
  let key = 0;

  for (const line of lines) {
    key++;
    if (line.trim() === "") {
      elements.push(<div key={key} className="h-2" />);
      continue;
    }

    // Headers
    if (line.startsWith("##")) {
      elements.push(
        <h3 key={key} className="text-base font-bold text-white mt-3 mb-1">
          {processInline(line.replace(/^##\s*/, ""))}
        </h3>
      );
      continue;
    }

    // Bullet points
    if (line.trimStart().startsWith("- ")) {
      const indent = line.length - line.trimStart().length;
      elements.push(
        <div key={key} className="flex gap-2" style={{ paddingLeft: indent * 4 + 8 }}>
          <span className="text-indigo-400 shrink-0">•</span>
          <span className="text-gray-300 text-sm">{processInline(line.trimStart().slice(2))}</span>
        </div>
      );
      continue;
    }

    // Numbered lists
    const numMatch = line.trimStart().match(/^(\d+)\.\s+(.*)$/);
    if (numMatch) {
      elements.push(
        <div key={key} className="flex gap-2 pl-2">
          <span className="text-indigo-400 font-mono text-sm shrink-0">{numMatch[1]}.</span>
          <span className="text-gray-300 text-sm">{processInline(numMatch[2])}</span>
        </div>
      );
      continue;
    }

    // Regular text
    elements.push(
      <p key={key} className="text-gray-300 text-sm leading-relaxed">
        {processInline(line)}
      </p>
    );
  }

  return <>{elements}</>;
}

function processInline(text: string) {
  // Process bold, code, and inline formatting
  const parts: (string | JSX.Element)[] = [];
  let remaining = text;
  let partKey = 0;

  while (remaining.length > 0) {
    // Bold: **text**
    const boldMatch = remaining.match(/\*\*(.+?)\*\*/);
    // Code: `text`
    const codeMatch = remaining.match(/`(.+?)`/);
    // Math: $text$ (not $$)
    const mathMatch = remaining.match(/(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)/);

    // Find earliest match
    const matches = [
      boldMatch ? { type: "bold", match: boldMatch, index: boldMatch.index! } : null,
      codeMatch ? { type: "code", match: codeMatch, index: codeMatch.index! } : null,
      mathMatch ? { type: "math", match: mathMatch, index: mathMatch.index! } : null,
    ].filter(Boolean).sort((a, b) => a!.index - b!.index);

    if (matches.length === 0) {
      parts.push(remaining);
      break;
    }

    const earliest = matches[0]!;
    const before = remaining.slice(0, earliest.index);
    if (before) parts.push(before);

    partKey++;
    if (earliest.type === "bold") {
      parts.push(
        <span key={`b${partKey}`} className="font-semibold text-white">
          {earliest.match![1]}
        </span>
      );
    } else if (earliest.type === "code") {
      parts.push(
        <code key={`c${partKey}`} className="bg-white/10 px-1.5 py-0.5 rounded text-indigo-300 text-xs font-mono">
          {earliest.match![1]}
        </code>
      );
    } else if (earliest.type === "math") {
      parts.push(
        <span key={`m${partKey}`} className="font-mono text-amber-300 text-xs">
          {earliest.match![1]}
        </span>
      );
    }

    remaining = remaining.slice(earliest.index + earliest.match![0].length);
  }

  return <>{parts}</>;
}

/* ── Quick Action Buttons ───────────────────────────────────────── */

const QUICK_ACTIONS = [
  { label: "📊 Performance", message: "How's my performance?" },
  { label: "🎯 Strategy", message: "What's the current trading strategy?" },
  { label: "🏛️ Markets", message: "What markets are you looking at?" },
  { label: "🧬 Learning", message: "How is the model learning?" },
  { label: "🛡️ Risk", message: "What's the risk assessment?" },
  { label: "🌍 Regime", message: "What's the current market regime?" },
  { label: "🧠 Memory", message: "Show me recent trades from memory" },
  { label: "🏗️ Deployed", message: "What do we have deployed right now?" },
];

/* ── Main Page ──────────────────────────────────────────────────── */

export default function FrankensteinPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [health, setHealth] = useState<FrankensteinHealth | null>(null);
  const [error, setError] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll to bottom
  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  // Fetch health status
  const fetchHealth = useCallback(async () => {
    try {
      const h = await frankFetch<FrankensteinHealth>("/health");
      setHealth(h);
    } catch {
      /* ignore */
    }
  }, []);

  // Load welcome message on mount
  useEffect(() => {
    async function init() {
      try {
        const welcome = await frankFetch<ChatMessage>("/chat/welcome");
        setMessages([welcome]);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Failed to connect to Frankenstein");
      }
      fetchHealth();
    }
    init();
    const iv = setInterval(fetchHealth, 10_000);
    return () => clearInterval(iv);
  }, [fetchHealth]);

  // Send message
  const sendMessage = async (text?: string) => {
    const msg = (text || input).trim();
    if (!msg || sending) return;

    // Add user message locally
    const userMsg: ChatMessage = {
      role: "user",
      content: msg,
      timestamp: Date.now() / 1000,
      time_human: new Date().toLocaleTimeString("en-US", {
        hour: "numeric",
        minute: "2-digit",
        hour12: true,
      }),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setSending(true);
    setError("");

    try {
      const response = await frankFetch<ChatMessage>("/chat", {
        method: "POST",
        body: JSON.stringify({ message: msg }),
      });
      setMessages((prev) => [...prev, response]);

      // Refresh health after commands
      if (msg.startsWith("/")) {
        fetchHealth();
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to send message");
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="flex flex-col h-[calc(100vh-7rem)]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--card-border)] pb-4 mb-4">
        <div className="flex items-center gap-3">
          <div className="relative">
            <span className="text-3xl">🧟</span>
            {health && (
              <span
                className={`absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-[var(--background)] ${
                  health.alive
                    ? health.paused
                      ? "bg-yellow-400"
                      : "bg-green-400 animate-pulse"
                    : "bg-gray-500"
                }`}
              />
            )}
          </div>
          <div>
            <h1 className="text-xl font-bold text-white">Frankenstein</h1>
            <p className="text-xs text-[var(--muted)]">
              {health
                ? health.alive
                  ? health.paused
                    ? "⏸️ Paused"
                    : `⚡ Gen ${health.generation} • ${health.total_trades} trades`
                  : "💤 Sleeping"
                : "Connecting..."}
            </p>
          </div>
        </div>

        {/* Status badges */}
        <div className="flex items-center gap-2">
          {health && (
            <>
              <span
                className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                  health.alive
                    ? "bg-green-500/10 text-green-400 ring-1 ring-green-500/20"
                    : "bg-gray-500/10 text-gray-400 ring-1 ring-gray-500/20"
                }`}
              >
                {health.alive ? "ALIVE" : "SLEEPING"}
              </span>
              {health.trading && (
                <span className="rounded-full bg-indigo-500/10 px-2.5 py-1 text-xs font-medium text-indigo-400 ring-1 ring-indigo-500/20">
                  TRADING
                </span>
              )}
              <span className="rounded-full bg-[var(--card)] px-2.5 py-1 text-xs text-[var(--muted)] ring-1 ring-[var(--card-border)]">
                v{health.model_version}
              </span>
            </>
          )}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-4 pr-2 scrollbar-thin">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-3 ${
                msg.role === "user"
                  ? "bg-indigo-600 text-white rounded-br-sm"
                  : "bg-[var(--card)] border border-[var(--card-border)] rounded-bl-sm"
              }`}
            >
              {msg.role === "frankenstein" ? (
                <div className="space-y-1">{renderMarkdown(msg.content)}</div>
              ) : (
                <p className="text-sm">{msg.content}</p>
              )}
              <p
                className={`text-[10px] mt-1.5 ${
                  msg.role === "user" ? "text-indigo-200/60" : "text-[var(--muted)]"
                }`}
              >
                {msg.time_human}
              </p>
            </div>
          </div>
        ))}

        {/* Typing indicator */}
        {sending && (
          <div className="flex justify-start">
            <div className="bg-[var(--card)] border border-[var(--card-border)] rounded-2xl rounded-bl-sm px-4 py-3">
              <div className="flex gap-1.5 items-center">
                <span className="text-sm text-[var(--muted)]">🧟 Thinking</span>
                <span className="flex gap-1">
                  <span className="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                  <span className="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                  <span className="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                </span>
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Quick actions */}
      <div className="flex flex-wrap gap-2 py-3 border-t border-[var(--card-border)] mt-2">
        {QUICK_ACTIONS.map((action) => (
          <button
            key={action.label}
            onClick={() => sendMessage(action.message)}
            disabled={sending}
            className="rounded-full bg-[var(--card)] border border-[var(--card-border)] px-3 py-1.5 text-xs text-[var(--muted)] hover:text-white hover:border-indigo-500/30 hover:bg-indigo-500/5 transition-all disabled:opacity-50"
          >
            {action.label}
          </button>
        ))}
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2 text-xs text-red-400 mb-2">
          {error}
        </div>
      )}

      {/* Input */}
      <div className="flex items-center gap-3 bg-[var(--card)] border border-[var(--card-border)] rounded-xl px-4 py-3">
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask Frankenstein anything... (try /status, /awaken, /retrain)"
          disabled={sending}
          className="flex-1 bg-transparent text-sm text-white placeholder:text-[var(--muted)] focus:outline-none disabled:opacity-50"
        />
        <button
          onClick={() => sendMessage()}
          disabled={!input.trim() || sending}
          className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition-all hover:bg-indigo-500 disabled:opacity-30 disabled:hover:bg-indigo-600"
        >
          <span>Send</span>
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
            <path d="M3.105 2.289a.75.75 0 00-.826.95l1.414 4.925A1.5 1.5 0 005.135 9.25h6.115a.75.75 0 010 1.5H5.135a1.5 1.5 0 00-1.442 1.086l-1.414 4.926a.75.75 0 00.826.95 28.896 28.896 0 0015.293-7.154.75.75 0 000-1.115A28.897 28.897 0 003.105 2.289z" />
          </svg>
        </button>
      </div>
    </div>
  );
}
