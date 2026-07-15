import { useId, type ReactNode } from "react";

type TooltipProps = {
  label: string;
  children: ReactNode;
  className?: string;
  testId?: string;
};

export function Tooltip({ label, children, className = "", testId }: TooltipProps) {
  const tooltipId = useId();
  return (
    <span
      tabIndex={0}
      data-testid={testId}
      aria-describedby={tooltipId}
      className={`group relative inline-flex rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-accent-cyan ${className}`}
    >
      {children}
      <span id={tooltipId} role="tooltip" className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 w-max max-w-xs -translate-x-1/2 rounded-md border border-border-strong bg-surface-strong px-3 py-2 text-xs font-medium text-text-primary opacity-0 shadow-glass transition-opacity duration-150 group-hover:opacity-100 group-focus-within:opacity-100">
        {label}
      </span>
    </span>
  );
}
