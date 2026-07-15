import { forwardRef, type ComponentPropsWithoutRef, type ReactNode } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "success" | "warning";

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary:
    "border border-accent-cyan-strong bg-accent-cyan-strong text-slate-950 hover:bg-accent-cyan",
  secondary:
    "border border-border-strong bg-surface-strong text-text-primary hover:border-text-muted",
  ghost: "border border-transparent text-text-secondary hover:bg-white/5 hover:text-text-primary",
  danger:
    "border border-accent-red-strong bg-accent-red-strong text-white hover:bg-accent-red",
  success:
    "border border-accent-emerald-strong bg-accent-emerald-strong text-slate-950 hover:bg-accent-emerald",
  warning:
    "border border-accent-amber bg-accent-amber text-slate-950 hover:bg-amber-400",
};

type ButtonProps = ComponentPropsWithoutRef<"button"> & {
  variant?: ButtonVariant;
  icon?: ReactNode;
  loading?: boolean;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button({
    variant = "secondary",
    icon,
    loading = false,
    disabled,
    className = "",
    children,
    ...rest
  }, ref) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={`inline-flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-semibold transition-colors duration-150 disabled:pointer-events-none disabled:opacity-50 ${VARIANT_CLASSES[variant]} ${className}`}
      {...rest}
    >
      {loading ? (
        <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />
      ) : (
        icon
      )}
      {children}
    </button>
  );
});
