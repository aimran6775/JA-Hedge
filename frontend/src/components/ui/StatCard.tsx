import { cn, pnlColor } from "@/lib/utils";

interface StatCardProps {
  label: string;
  value: string | number;
  change?: number;
  prefix?: string;
  suffix?: string;
  className?: string;
}

export function StatCard({
  label,
  value,
  change,
  prefix = "",
  suffix = "",
  className,
}: StatCardProps) {
  return (
    <div
      className={cn(
        "rounded-lg border border-[var(--card-border)] bg-[var(--card)] p-4",
        className,
      )}
    >
      <p className="text-xs text-[var(--muted)]">{label}</p>
      <p className="mt-1 text-2xl font-bold tabular-nums text-white">
        {prefix}
        {typeof value === "number" ? value.toLocaleString() : value}
        {suffix}
      </p>
      {change !== undefined && (
        <p className={cn("mt-1 text-xs tabular-nums", pnlColor(change))}>
          {change > 0 ? "+" : ""}
          {change.toFixed(2)}
          {suffix || "%"}
        </p>
      )}
    </div>
  );
}
