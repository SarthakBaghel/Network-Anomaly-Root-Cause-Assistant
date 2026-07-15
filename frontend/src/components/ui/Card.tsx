import type { ComponentPropsWithoutRef, ElementType, ReactNode } from "react";

type GlowVariant = "none" | "cyan" | "purple" | "emerald" | "red";

const GLOW_CLASSES: Record<GlowVariant, string> = {
  none: "",
  cyan: "hover:border-accent-cyan/40 hover:shadow-glow-cyan",
  purple: "hover:border-accent-purple/40 hover:shadow-glow-purple",
  emerald: "hover:border-accent-emerald/40 hover:shadow-glow-emerald",
  red: "hover:border-accent-red/40 hover:shadow-glow-red",
};

type CardProps = ComponentPropsWithoutRef<"div"> & {
  as?: ElementType;
  interactive?: boolean;
  glow?: GlowVariant;
  children: ReactNode;
};

export function Card({
  as: Component = "div",
  interactive = false,
  glow = "cyan",
  className = "",
  children,
  ...rest
}: CardProps) {
  const classes = [
    "glass-panel animate-fade-in-up p-6",
    interactive ? `transition-all duration-300 ${GLOW_CLASSES[glow]}` : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <Component className={classes} {...rest}>
      {children}
    </Component>
  );
}
