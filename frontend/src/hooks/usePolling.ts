import { useEffect, useRef } from "react";

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
