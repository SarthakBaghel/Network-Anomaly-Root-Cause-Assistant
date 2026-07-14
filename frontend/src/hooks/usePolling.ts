import { useEffect, useRef, useState } from 'react'

export const FRONTEND_POLL_INTERVAL_MS = 1_500

export type PollingSnapshot = {
  generated_at?: string
  analysis_run_id?: string
}

export type PollingState<T> = {
  data: T | null
  error: Error | null
  isLoading: boolean
}

export function shouldAcceptSnapshot(
  lastRenderedAt: number,
  snapshot: PollingSnapshot,
): boolean {
  if (!snapshot.generated_at) {
    return true
  }
  const generatedAt = Date.parse(snapshot.generated_at)
  return Number.isNaN(generatedAt) || generatedAt >= lastRenderedAt
}

export function usePolling<T extends PollingSnapshot>(
  load: () => Promise<T>,
  options: { enabled?: boolean; intervalMs?: number } = {},
): PollingState<T> {
  const { enabled = true, intervalMs = FRONTEND_POLL_INTERVAL_MS } = options
  const [state, setState] = useState<PollingState<T>>({ data: null, error: null, isLoading: enabled })
  const lastRenderedAt = useRef(Number.NEGATIVE_INFINITY)

  useEffect(() => {
    if (!enabled) {
      setState((current) => ({ ...current, isLoading: false }))
      return undefined
    }

    let active = true
    lastRenderedAt.current = Number.NEGATIVE_INFINITY
    setState({ data: null, error: null, isLoading: true })
    const poll = async () => {
      try {
        const snapshot = await load()
        if (!active || !shouldAcceptSnapshot(lastRenderedAt.current, snapshot)) {
          return
        }
        const timestamp = snapshot.generated_at ? Date.parse(snapshot.generated_at) : Number.NaN
        if (!Number.isNaN(timestamp)) {
          lastRenderedAt.current = timestamp
        }
        // Deliberately replace the entire object. A new analysis run must never merge with an old run.
        setState({ data: snapshot, error: null, isLoading: false })
      } catch (error) {
        if (active) {
          setState((current) => ({
            ...current,
            error: error instanceof Error ? error : new Error('Polling failed.'),
            isLoading: false,
          }))
        }
      }
    }

    void poll()
    const timer = window.setInterval(() => void poll(), intervalMs)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [enabled, intervalMs, load])

  return state
}
