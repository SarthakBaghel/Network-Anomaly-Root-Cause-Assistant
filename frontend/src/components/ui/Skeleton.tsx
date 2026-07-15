type SkeletonProps = {
  className?: string;
};

export function Skeleton({ className = "h-4 w-full" }: SkeletonProps) {
  return <div className={`skeleton-shimmer ${className}`} />;
}

type PageSkeletonProps = {
  label: string;
};

export function PageSkeleton({ label }: PageSkeletonProps) {
  return (
    <div className="mx-auto max-w-6xl space-y-6 p-8" role="status" aria-live="polite">
      <span className="sr-only">{label}</span>
      <Skeleton className="h-10 w-72" />
      <Skeleton className="h-4 w-96 max-w-full" />
      <div className="grid gap-4 md:grid-cols-3">
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
      <Skeleton className="h-64 w-full" />
    </div>
  );
}
