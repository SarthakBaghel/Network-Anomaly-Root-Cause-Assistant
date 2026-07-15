import { useEffect, useRef } from "react";

export const FRONTEND_POLL_INTERVAL_MS = 1_500;

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
  callback: (signal?: AbortSignal) => void | Promise<void>,
  intervalMs = FRONTEND_POLL_INTERVAL_MS,
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

    let active = true;
    let timeoutId: number | undefined;
    let controller: AbortController | undefined;
    const run = async () => {
      controller?.abort();
      controller = new AbortController();
      try {
        await callbackRef.current(controller.signal);
      } finally {
        if (active) timeoutId = window.setTimeout(run, intervalMs);
      }
    };
    void run();

    return () => {
      active = false;
      controller?.abort();
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
    };
  }, [intervalMs, enabled]);
}
