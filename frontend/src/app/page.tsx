export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-8">
      <div className="flex flex-col items-center gap-2">
        <h1 className="text-4xl font-bold tracking-tight text-white">
          JA Hedge
        </h1>
        <p className="text-lg text-[var(--muted)]">
          AI-Powered Event Contract Trading
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3 mt-8 w-full max-w-3xl">
        <StatusCard
          label="Backend"
          endpoint="/api/health"
          description="FastAPI + Kalshi Client"
        />
        <StatusCard
          label="Database"
          endpoint="/api/health"
          description="TimescaleDB"
        />
        <StatusCard
          label="AI Engine"
          endpoint="/api/health"
          description="ML Pipeline"
        />
      </div>

      <p className="text-sm text-[var(--muted)] mt-12">
        Dashboard coming in Phase 13 →
      </p>
    </main>
  );
}

function StatusCard({
  label,
  description,
}: {
  label: string;
  endpoint: string;
  description: string;
}) {
  return (
    <div className="rounded-lg border border-[var(--card-border)] bg-[var(--card)] p-5">
      <div className="flex items-center gap-2 mb-2">
        <span className="h-2 w-2 rounded-full bg-yellow-500" />
        <span className="text-sm font-medium text-white">{label}</span>
      </div>
      <p className="text-xs text-[var(--muted)]">{description}</p>
    </div>
  );
}
