import type { ReactNode } from "react";

type TooltipProps = {
  label: string;
  children: ReactNode;
  className?: string;
};

export function Tooltip({ label, children, className = "" }: TooltipProps) {
  return (
    <span className={`group relative inline-flex ${className}`}>
      {children}
      <span className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 w-max max-w-xs -translate-x-1/2 scale-95 rounded-xl border border-border-subtle bg-surface-strong px-3 py-2 text-xs font-medium text-text-primary opacity-0 shadow-glass backdrop-blur-xl transition-all duration-200 group-hover:scale-100 group-hover:opacity-100">
        {label}
      </span>
    </span>
  );
}
