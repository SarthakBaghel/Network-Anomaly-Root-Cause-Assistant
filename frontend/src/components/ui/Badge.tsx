import type { ComponentPropsWithoutRef, ReactNode } from "react";
import { AlertTriangleIcon, CheckCircleIcon, InfoIcon, XCircleIcon } from "../icons";

export type BadgeVariant = "success" | "warning" | "danger" | "info" | "neutral";

const VARIANT_CLASSES: Record<BadgeVariant, string> = {
  success: "border-accent-emerald/30 bg-accent-emerald/10 text-accent-emerald",
  warning: "border-accent-amber/30 bg-accent-amber/10 text-accent-amber",
  danger: "border-accent-red/30 bg-accent-red/10 text-accent-red",
  info: "border-accent-cyan/30 bg-accent-cyan/10 text-accent-cyan",
  neutral: "border-border-subtle bg-white/5 text-text-secondary",
};

const VARIANT_ICON: Record<BadgeVariant, ReactNode> = {
  success: <CheckCircleIcon className="h-3.5 w-3.5" />,
  warning: <AlertTriangleIcon className="h-3.5 w-3.5" />,
  danger: <XCircleIcon className="h-3.5 w-3.5" />,
  info: <InfoIcon className="h-3.5 w-3.5" />,
  neutral: <InfoIcon className="h-3.5 w-3.5" />,
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
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-wide ${VARIANT_CLASSES[variant]} ${className}`}
      {...rest}
    >
      {!hideIcon ? (icon ?? VARIANT_ICON[variant]) : null}
      {children}
    </span>
  );
}
