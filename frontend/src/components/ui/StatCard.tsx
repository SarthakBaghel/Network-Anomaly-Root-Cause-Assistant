type StatCardAccent = "cyan" | "purple" | "emerald" | "amber" | "red";

const ACCENT_BORDER: Record<StatCardAccent, string> = {
  cyan: "border-l-accent-cyan",
  purple: "border-l-accent-purple",
  emerald: "border-l-accent-emerald",
  amber: "border-l-accent-amber",
  red: "border-l-accent-red",
};

type StatCardProps = {
  label: string;
  value: number;
  accent?: StatCardAccent;
};

export function StatCard({ label, value, accent = "cyan" }: StatCardProps) {
  return (
    <div className={`glass-panel border-l-2 p-4 ${ACCENT_BORDER[accent]}`}>
      <p className="text-xs font-medium text-text-secondary">{label}</p>
      <p className="font-data mt-1 text-2xl font-semibold text-text-primary">
        {value.toLocaleString()}
      </p>
    </div>
  );
}
