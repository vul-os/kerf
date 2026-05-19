import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ── Mock localStash ────────────────────────────────────────────────────────

const mockStash = vi.fn()
const mockGetBytes = vi.fn()
const mockMarkFlushed = vi.fn()

vi.mock('./localStash', () => ({
  stash: (...args) => mockStash(...args),
  getBytes: (...args) => mockGetBytes(...args),
  markFlushed: (...args) => mockMarkFlushed(...args),
}))

// ── Import SUT after mocks are registered ──────────────────────────────────

import { markDirty, _resetForTesting } from './autosaveScheduler'
import { autosaveStatus } from './autosaveStatusEvents'

// ── Helpers ────────────────────────────────────────────────────────────────

const WS   = 'ws-1'
const FILE = 'model.json'

/** Collect event names from autosaveStatus in order. */
function collectEvents(types) {
  const log = []
  const handlers = {}
  for (const t of types) {
    const h = () => log.push(t)
    handlers[t] = h
    autosaveStatus.addEventListener(t, h)
  }
  return {
    log,
    cleanup: () => {
      for (const t of types) autosaveStatus.removeEventListener(t, handlers[t])
    },
  }
}

/** Make fetch resolve with an ok response. */
function mockFetchOk() {
  global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200 })
}

/** Make fetch resolve with a server error. */
function mockFetchErr() {
  global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 500 })
}

/** Make fetch reject (network error). */
function mockFetchNetworkError() {
  global.fetch = vi.fn().mockRejectedValue(new Error('network'))
}

// ── Setup / teardown ───────────────────────────────────────────────────────

beforeEach(() => {
  vi.useFakeTimers()
  mockStash.mockReset()
  mockGetBytes.mockReset()
  mockMarkFlushed.mockReset()
  _resetForTesting()
  // Default: stash is a fire-and-forget write; getBytes returns some bytes; fetch succeeds
  mockStash.mockResolvedValue(undefined)
  mockGetBytes.mockResolvedValue(new Uint8Array([1, 2, 3]))
  mockFetchOk()
})

afterEach(() => {
  vi.useRealTimers()
})

// ── Tests ──────────────────────────────────────────────────────────────────

describe('autosaveScheduler — idle 2 s triggers flush', () => {
  it('flushes after 2 s of inactivity', async () => {
    const { log, cleanup } = collectEvents(['dirty', 'saving', 'saved'])

    markDirty(WS, FILE, new Uint8Array([1, 2, 3]))
    expect(log).toEqual(['dirty'])

    // Advance past idle delay
    await vi.advanceTimersByTimeAsync(2_000)

    expect(log).toEqual(['dirty', 'saving', 'saved'])
    expect(mockMarkFlushed).toHaveBeenCalledOnce()
    cleanup()
  })

  it('resets idle timer on subsequent markDirty calls (debounce)', async () => {
    const { log, cleanup } = collectEvents(['saving'])

    markDirty(WS, FILE, new Uint8Array([1, 2, 3]))
    await vi.advanceTimersByTimeAsync(1_000)
    markDirty(WS, FILE, new Uint8Array([1, 2, 3])) // reset
    await vi.advanceTimersByTimeAsync(1_000)
    // Still only 2 s total from second call — not yet flushed (1 s remaining)
    expect(log).toHaveLength(0)

    await vi.advanceTimersByTimeAsync(1_001)
    expect(log).toEqual(['saving'])
    cleanup()
  })
})

describe('autosaveScheduler — continuous edits trigger 30 s hard flush', () => {
  it('hard timer fires at 30 s even with continuous edits', async () => {
    const { log, cleanup } = collectEvents(['saving', 'saved'])

    // Keep resetting the idle timer every second for 29 s
    for (let i = 0; i < 29; i++) {
      markDirty(WS, FILE, new Uint8Array([1, 2, 3]))
      await vi.advanceTimersByTimeAsync(1_000)
    }
    // 29 s in — idle timer not yet fired, hard timer not yet fired
    expect(log).toHaveLength(0)

    // Advance 1 more second → 30 s → hard timer fires
    markDirty(WS, FILE, new Uint8Array([1, 2, 3]))
    await vi.advanceTimersByTimeAsync(1_001)

    // Hard flush should have happened
    expect(log).toContain('saving')
    expect(log).toContain('saved')
    cleanup()
  })
})

describe('autosaveScheduler — failure path', () => {
  it('emits error, does NOT call markFlushed, and retries', async () => {
    mockFetchErr()
    const { log, cleanup } = collectEvents(['saving', 'saved', 'error'])

    markDirty(WS, FILE, new Uint8Array([1, 2, 3]))
    await vi.advanceTimersByTimeAsync(2_000) // idle flush fires

    expect(log).toEqual(['saving', 'error'])
    expect(mockMarkFlushed).not.toHaveBeenCalled()

    // Now make fetch succeed for the retry
    mockFetchOk()
    // Backoff base is 2 s → retry fires after 2 s
    await vi.advanceTimersByTimeAsync(2_000)

    expect(log).toContain('saved')
    expect(mockMarkFlushed).toHaveBeenCalledOnce()
    cleanup()
  })

  it('emits error on network failure and does NOT call markFlushed', async () => {
    mockFetchNetworkError()
    const { log, cleanup } = collectEvents(['saving', 'error'])

    markDirty(WS, FILE, new Uint8Array([1, 2, 3]))
    await vi.advanceTimersByTimeAsync(2_000)

    expect(log).toEqual(['saving', 'error'])
    expect(mockMarkFlushed).not.toHaveBeenCalled()
    cleanup()
  })

  it('applies exponential backoff capped at 30 s', async () => {
    // Fail repeatedly and check backoff grows but caps
    mockFetchErr()

    markDirty(WS, FILE, new Uint8Array([1, 2, 3]))
    await vi.advanceTimersByTimeAsync(2_000) // first flush → error → backoff 2 s

    // First retry at +2 s
    await vi.advanceTimersByTimeAsync(2_001) // retry → error → backoff 4 s

    // Second retry at +4 s
    await vi.advanceTimersByTimeAsync(4_001) // retry → error → backoff 8 s

    // Third retry at +8 s
    await vi.advanceTimersByTimeAsync(8_001) // retry → error → backoff 16 s

    // Fourth retry at +16 s
    await vi.advanceTimersByTimeAsync(16_001) // retry → error → backoff should cap at 30 s

    // Fifth retry at +30 s (capped)
    mockFetchOk()
    await vi.advanceTimersByTimeAsync(30_001)

    expect(mockMarkFlushed).toHaveBeenCalledOnce()
  })
})

describe('autosaveScheduler — success path', () => {
  it('emits saving then saved in order, and calls markFlushed exactly once', async () => {
    const { log, cleanup } = collectEvents(['saving', 'saved'])

    markDirty(WS, FILE, new Uint8Array([1, 2, 3]))
    await vi.advanceTimersByTimeAsync(2_000)

    expect(log).toEqual(['saving', 'saved'])
    expect(mockMarkFlushed).toHaveBeenCalledOnce()
    expect(mockMarkFlushed).toHaveBeenCalledWith(WS, FILE)
    cleanup()
  })

  it('reads bytes via getBytes when flushing to server', async () => {
    markDirty(WS, FILE, new Uint8Array([1, 2, 3]))
    await vi.advanceTimersByTimeAsync(2_000)

    expect(mockGetBytes).toHaveBeenCalledWith(WS, FILE)
  })

  it('stash is called with bytes on markDirty', async () => {
    const bytes = new Uint8Array([7, 8, 9])
    markDirty(WS, FILE, bytes)
    // Allow the fire-and-forget stash promise to settle.
    await Promise.resolve()

    expect(mockStash).toHaveBeenCalledWith(WS, FILE, bytes)
  })
})

describe('autosaveScheduler — queued edit during in-flight flush', () => {
  it('triggers exactly one follow-up flush after in-flight settles', async () => {
    // First fetch call is manually controlled; subsequent calls resolve immediately.
    let resolveFetch
    let callCount = 0
    global.fetch = vi.fn().mockImplementation(() => {
      callCount++
      if (callCount === 1) {
        return new Promise((res) => { resolveFetch = () => res({ ok: true, status: 200 }) })
      }
      return Promise.resolve({ ok: true, status: 200 })
    })

    const { log, cleanup } = collectEvents(['saving', 'saved', 'dirty'])

    markDirty(WS, FILE, new Uint8Array([1, 2, 3]))
    // Advance past idle delay to start the in-flight flush
    await vi.advanceTimersByTimeAsync(2_000)

    // At this point 'saving' should have been emitted and fetch is pending
    expect(log).toContain('saving')
    expect(log.filter(e => e === 'saving')).toHaveLength(1)

    // markDirty while in-flight — should queue exactly one follow-up (not three)
    markDirty(WS, FILE, new Uint8Array([1, 2, 3]))
    markDirty(WS, FILE, new Uint8Array([1, 2, 3]))
    markDirty(WS, FILE, new Uint8Array([1, 2, 3]))

    // Resolve the first in-flight fetch — triggers handleFlushSuccess + scheduleIdle
    resolveFetch()
    // Drain the promise chain inside flush() so handleFlushSuccess() runs
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()

    // Now advance past the idle delay for the queued follow-up flush
    await vi.advanceTimersByTimeAsync(2_001)
    // Give async fetch chain time to settle
    await Promise.resolve()
    await Promise.resolve()

    // Should have saved exactly twice: initial + one follow-up (not three)
    expect(log.filter(e => e === 'saved')).toHaveLength(2)
    expect(log.filter(e => e === 'saving')).toHaveLength(2)
    expect(mockMarkFlushed).toHaveBeenCalledTimes(2)
    cleanup()
  })
})

describe('autosaveScheduler — arity-bug regression (T-309)', () => {
  it('flush() uses getBytes() not stash(); does not crash with wrong arity', async () => {
    // This is the regression guard: the old code called stash(ws, file) with 2
    // args expecting bytes back — which always returned undefined, causing the
    // fetch body to be undefined and network errors.
    // The fix: flush() calls getBytes(ws, file) instead.

    markDirty(WS, FILE, new Uint8Array([42]))
    await vi.advanceTimersByTimeAsync(2_000)

    // getBytes must have been called (not stash) to read bytes for the server.
    expect(mockGetBytes).toHaveBeenCalledWith(WS, FILE)
    // fetch must have been called — confirms no early exit from undefined bytes.
    expect(global.fetch).toHaveBeenCalledOnce()
  })

  it('multiple markDirty calls debounce: only one flush fires after idle period', async () => {
    const { log, cleanup } = collectEvents(['saving'])

    markDirty(WS, FILE, new Uint8Array([1]))
    markDirty(WS, FILE, new Uint8Array([2]))
    markDirty(WS, FILE, new Uint8Array([3]))

    // No flush yet
    expect(log).toHaveLength(0)

    await vi.advanceTimersByTimeAsync(2_000)

    // Exactly one saving event — debounce collapsed the three calls.
    expect(log.filter(e => e === 'saving')).toHaveLength(1)
    cleanup()
  })
})
