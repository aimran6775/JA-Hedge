import { cn } from "@/lib/utils";

interface CardProps {
  title?: string;
  children: React.ReactNode;
  className?: string;
  action?: React.ReactNode;
  glow?: boolean;
}

export function Card({ title, children, className, action, glow }: CardProps) {
  return (
    <div
      className={cn(
        "rounded-2xl glass p-5 transition-all duration-300",
        glow && "glow-accent",
        className,
      )}
    >
      {(title || action) && (
        <div className="mb-4 flex items-center justify-between">
          {title && (
            <h3 className="text-sm font-semibold tracking-wide text-[var(--text-secondary)] uppercase">
              {title}
            </h3>
          )}
          {action}
        </div>
      )}
      {children}
    </div>
  );
}
