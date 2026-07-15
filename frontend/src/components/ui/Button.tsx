import { forwardRef, type ComponentPropsWithoutRef, type ReactNode } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "success" | "warning";

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary:
    "bg-gradient-to-r from-accent-cyan-strong to-accent-purple-strong text-slate-950 shadow-glow-cyan hover:brightness-110 hover:-translate-y-0.5",
  secondary:
    "border border-border-strong bg-surface text-text-primary hover:border-accent-cyan/40 hover:-translate-y-0.5",
  ghost: "border border-transparent text-text-secondary hover:bg-white/5 hover:text-text-primary",
  danger:
    "bg-gradient-to-r from-accent-red to-accent-red-strong text-white shadow-glow-red hover:brightness-110 hover:-translate-y-0.5",
  success:
    "bg-gradient-to-r from-accent-emerald to-accent-emerald-strong text-slate-950 shadow-glow-emerald hover:brightness-110 hover:-translate-y-0.5",
  warning:
    "bg-gradient-to-r from-accent-amber to-amber-500 text-slate-950 hover:brightness-110 hover:-translate-y-0.5",
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
      className={`inline-flex items-center justify-center gap-2 rounded-2xl px-4 py-2.5 text-sm font-semibold transition-all duration-200 disabled:pointer-events-none disabled:translate-y-0 disabled:opacity-50 ${VARIANT_CLASSES[variant]} ${className}`}
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
