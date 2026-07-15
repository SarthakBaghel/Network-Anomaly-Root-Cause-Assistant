type EvidenceScoreBarProps = {
  score: number;
  available?: number;
  expected?: number;
};

export function EvidenceScoreBar({ score, available, expected }: EvidenceScoreBarProps) {
  const clamped = Math.max(0, Math.min(100, score));
  const displayScore = (Math.round(clamped * 10) / 10).toFixed(1);
  const filledClass =
    clamped >= 85 ? "bg-accent-emerald" : clamped < 70 ? "bg-accent-amber" : "bg-slate-400";

  return (
    <div className="w-full min-w-36">
      <div className="mb-1.5 flex items-center justify-between gap-3">
        <span className="text-xs font-medium text-text-secondary">
          Evidence score
        </span>
        <span className="font-data text-xl font-semibold text-text-primary">{displayScore}</span>
      </div>
      <div
        className="h-1.5 w-full overflow-hidden rounded-sm bg-white/10"
        role="img"
        aria-label={`Evidence score ${displayScore} out of 100`}
      >
        <span className={`block h-full ${filledClass}`} style={{ width: `${clamped}%` }} />
      </div>
      {available !== undefined && expected !== undefined ? (
        <p className="font-data mt-1.5 text-xs text-text-muted">
          {available}/{expected} expected signals observed
        </p>
      ) : null}
    </div>
  );
}
