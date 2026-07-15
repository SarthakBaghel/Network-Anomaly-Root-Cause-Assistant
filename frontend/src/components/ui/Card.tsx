import type { ComponentPropsWithoutRef, ElementType, ReactNode } from "react";

type GlowVariant = "none" | "cyan" | "purple" | "emerald" | "red";

const GLOW_CLASSES: Record<GlowVariant, string> = {
  none: "",
  cyan: "hover:border-border-strong",
  purple: "hover:border-border-strong",
  emerald: "hover:border-border-strong",
  red: "hover:border-border-strong",
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
    "glass-panel p-5",
    interactive ? `transition-colors duration-150 ${GLOW_CLASSES[glow]}` : "",
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
