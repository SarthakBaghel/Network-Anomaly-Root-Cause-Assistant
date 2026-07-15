import type { ComponentPropsWithoutRef, ReactNode } from "react";

export type BadgeVariant = "success" | "warning" | "danger" | "info" | "neutral";

const VARIANT_CLASSES: Record<BadgeVariant, string> = {
  success: "border-border-subtle border-l-accent-emerald text-accent-emerald",
  warning: "border-border-subtle border-l-accent-amber text-accent-amber",
  danger: "border-border-subtle border-l-accent-red text-accent-red",
  info: "border-border-subtle border-l-accent-cyan text-accent-cyan",
  neutral: "border-border-subtle border-l-text-muted text-text-secondary",
};

type BadgeProps = Omit<ComponentPropsWithoutRef<"span">, "children"> & {
  variant?: BadgeVariant;
  icon?: ReactNode;
  hideIcon?: boolean;
  children: ReactNode;
};

export function Badge({
  variant = "neutral",
  icon,
  hideIcon = false,
  className = "",
  children,
  ...rest
}: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded border border-l-2 bg-surface-strong px-2 py-0.5 text-[0.7rem] font-semibold uppercase tracking-wide ${VARIANT_CLASSES[variant]} ${className}`}
      {...rest}
    >
      {!hideIcon ? icon : null}
      {children}
    </span>
  );
}
