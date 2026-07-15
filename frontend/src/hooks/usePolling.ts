import { useEffect, useRef } from "react";

export type PollingSnapshot = {
  generated_at?: string;
  analysis_run_id?: string;
};

export function shouldAcceptSnapshot(
  lastRenderedAt: number,
  snapshot: PollingSnapshot,
): boolean {
  if (!snapshot.generated_at) {
    return true;
  }
  const generatedAt = Date.parse(snapshot.generated_at);
  return Number.isNaN(generatedAt) || generatedAt >= lastRenderedAt;
}

export function usePolling(
  callback: () => void | Promise<void>,
  intervalMs: number,
  enabled = true,
) {
  const callbackRef = useRef(callback);

  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    const id = window.setInterval(() => {
      void callbackRef.current();
    }, intervalMs);

    return () => window.clearInterval(id);
  }, [intervalMs, enabled]);
}
