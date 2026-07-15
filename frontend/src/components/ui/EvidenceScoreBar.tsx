const SEGMENT_COUNT = 20;

type EvidenceScoreBarProps = {
  score: number;
};

export function EvidenceScoreBar({ score }: EvidenceScoreBarProps) {
  const clamped = Math.max(0, Math.min(100, score));
  const displayScore = (Math.round(clamped * 10) / 10).toFixed(1);
  const filledSegments = Math.round((clamped / 100) * SEGMENT_COUNT);
  const filledClass =
    clamped >= 75 ? "bg-accent-emerald" : clamped >= 45 ? "bg-accent-amber" : "bg-accent-red";

  return (
    <div className="w-full min-w-36">
      <div className="mb-1.5 flex items-center justify-between gap-3">
        <span className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
          Evidence score
        </span>
        <span className="text-sm font-bold tabular-nums text-text-primary">{displayScore}</span>
      </div>
      <div
        className="flex h-2 w-full items-center gap-0.5"
        role="img"
        aria-label={`Evidence score ${displayScore} out of 100`}
      >
        {Array.from({ length: SEGMENT_COUNT }, (_, index) => (
          <span
            key={index}
            className={`h-full flex-1 rounded-full ${index < filledSegments ? filledClass : "bg-white/10"}`}
          />
        ))}
      </div>
    </div>
  );
}
