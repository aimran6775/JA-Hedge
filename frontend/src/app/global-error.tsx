"use client";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en" className="dark">
      <body style={{ background: "#050508", color: "#f0f0f5", fontFamily: "Inter, system-ui, sans-serif", padding: "2rem" }}>
        <div style={{ maxWidth: 600, margin: "4rem auto" }}>
          <h1 style={{ fontSize: 20, marginBottom: 16, color: "#ef4444" }}>Dashboard Error</h1>
          <pre style={{ 
            background: "rgba(255,255,255,0.05)", 
            padding: 16, 
            borderRadius: 8, 
            overflow: "auto",
            fontSize: 13,
            lineHeight: 1.5,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}>
            {error.message}
            {"\n\n"}
            {error.stack}
          </pre>
          {error.digest && (
            <p style={{ marginTop: 12, fontSize: 12, color: "#5a5a72" }}>
              Digest: {error.digest}
            </p>
          )}
          <button
            onClick={reset}
            style={{
              marginTop: 16,
              padding: "8px 20px",
              background: "rgba(16,185,129,0.2)",
              color: "#10b981",
              border: "1px solid rgba(16,185,129,0.3)",
              borderRadius: 8,
              cursor: "pointer",
              fontSize: 14,
            }}
          >
            Retry
          </button>
        </div>
      </body>
    </html>
  );
}
