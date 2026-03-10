import { cn, pnlColor } from "@/lib/utils";
import { IconTrendUp, IconTrendDown } from "@/components/ui/Icons";

interface StatCardProps {
  label: string;
  value: string | number;
  change?: number;
  trend?: "up" | "down";
  prefix?: string;
  suffix?: string;
  className?: string;
  icon?: React.ReactNode;
}

export function StatCard({
  label,
  value,
  change,
  trend,
  prefix = "",
  suffix = "",
  className,
  icon,
}: StatCardProps) {
  return (
    <div
      className={cn(
        "group relative rounded-2xl glass p-5 transition-all duration-300 hover:border-white/10",
        className,
      )}
    >
      {/* Subtle gradient on hover */}
      <div className="absolute inset-0 rounded-2xl opacity-0 group-hover:opacity-100 transition-opacity duration-500 bg-gradient-to-br from-accent/5 to-transparent pointer-events-none" />

      <div className="relative">
        <div className="flex items-center justify-between">
          <p className="text-xs font-medium tracking-wider uppercase text-[var(--text-muted)]">
            {label}
          </p>
          {icon && <div className="text-[var(--text-muted)]">{icon}</div>}
        </div>
        <p className="mt-2 text-2xl font-bold tabular-nums text-[var(--text-primary)]">
          {prefix}
          {typeof value === "number" ? value.toLocaleString() : value}
          {suffix}
        </p>
        {change !== undefined && (
          <div className={cn("mt-2 flex items-center gap-1 text-xs tabular-nums", pnlColor(change))}>
            {change >= 0 ? <IconTrendUp size={14} /> : <IconTrendDown size={14} />}
            <span>
              {change > 0 ? "+" : ""}
              {change.toFixed(2)}
              {suffix || "%"}
            </span>
          </div>
        )}
        {!change && trend && (
          <div className={cn("mt-2 flex items-center gap-1 text-xs", trend === "up" ? "text-accent" : "text-loss")}>
            {trend === "up" ? <IconTrendUp size={14} /> : <IconTrendDown size={14} />}
          </div>
        )}
      </div>
    </div>
  );
}
