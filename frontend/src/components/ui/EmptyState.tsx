import type { ReactNode } from "react";

type EmptyStateProps = {
  icon?: ReactNode;
  message: string;
};

export function EmptyState({ icon, message }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-border-subtle bg-white/[0.02] px-4 py-6 text-center">
      {icon ? <span className="text-text-muted">{icon}</span> : null}
      <p className="text-sm text-text-secondary">{message}</p>
    </div>
  );
}
