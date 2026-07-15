import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { usePolling } from '../src/hooks/usePolling'

describe('usePolling', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('waits for each request, aborts the previous signal, and cancels on unmount', async () => {
    vi.useFakeTimers()
    const signals: AbortSignal[] = []
    const resolveCalls: Array<() => void> = []
    const callback = vi.fn((signal?: AbortSignal) => {
      signals.push(signal!)
      return new Promise<void>((resolve) => resolveCalls.push(resolve))
    })

    const { unmount } = renderHook(() => usePolling(callback, 100))
    await act(async () => Promise.resolve())
    expect(callback).toHaveBeenCalledTimes(1)

    await act(async () => vi.advanceTimersByTimeAsync(500))
    expect(callback).toHaveBeenCalledTimes(1)

    await act(async () => {
      resolveCalls[0]()
      await Promise.resolve()
    })
    await act(async () => vi.advanceTimersByTimeAsync(100))
    expect(callback).toHaveBeenCalledTimes(2)
    expect(signals[0].aborted).toBe(true)

    unmount()
    expect(signals[1].aborted).toBe(true)
  })
})
