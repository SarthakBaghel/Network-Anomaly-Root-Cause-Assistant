import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

type StatCardAccent = "cyan" | "purple" | "emerald" | "amber" | "red";

const ACCENT_ICON_WRAP: Record<StatCardAccent, string> = {
  cyan: "bg-accent-cyan/10 text-accent-cyan",
  purple: "bg-accent-purple/10 text-accent-purple",
  emerald: "bg-accent-emerald/10 text-accent-emerald",
  amber: "bg-accent-amber/10 text-accent-amber",
  red: "bg-accent-red/10 text-accent-red",
};

type StatCardProps = {
  label: string;
  value: number;
  icon: ReactNode;
  accent?: StatCardAccent;
};

export function StatCard({ label, value, icon, accent = "cyan" }: StatCardProps) {
  const [display, setDisplay] = useState(0);
  const frameRef = useRef<number | null>(null);
  const displayRef = useRef(0);

  useEffect(() => {
    const startValue = displayRef.current;
    const startTime = performance.now();
    const duration = 800;

    function tick(now: number) {
      const progress = Math.min(1, (now - startTime) / duration);
      const eased = 1 - Math.pow(1 - progress, 3);
      const next = Math.round(startValue + (value - startValue) * eased);
      displayRef.current = next;
      setDisplay(next);
      if (progress < 1) {
        frameRef.current = requestAnimationFrame(tick);
      }
    }

    frameRef.current = requestAnimationFrame(tick);
    return () => {
      if (frameRef.current !== null) {
        cancelAnimationFrame(frameRef.current);
      }
    };
  }, [value]);

  return (
    <div className="glass-panel animate-fade-in-up flex items-center gap-4 p-5">
      <span
        className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl ${ACCENT_ICON_WRAP[accent]}`}
      >
        {icon}
      </span>
      <div>
        <p className="text-2xl font-bold tabular-nums text-text-primary">
          {display.toLocaleString()}
        </p>
        <p className="text-xs font-medium uppercase tracking-wide text-text-secondary">{label}</p>
      </div>
    </div>
  );
}
