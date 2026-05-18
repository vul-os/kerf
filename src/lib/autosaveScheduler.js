// autosaveScheduler — shared throttle/flush scheduler for L2 server autosave.
//
// markDirty(workspaceId, filePath) is the single entry-point called by editors
// on every change. The scheduler coordinates two timers per (workspace, file)
// key:
//
//   idle timer  — fires 2 s after the LAST markDirty call (debounce)
//   hard timer  — fires every 30 s regardless of edit frequency (hard cap)
//
// Flush pipeline:
//   1. Read bytes from IDB via stash(workspaceId, filePath)
//   2. POST /workspaces/{workspaceId}/files/{filePath}/revisions
//   3. On 2xx  → emit `saved`, call markFlushed(workspaceId, filePath)
//   4. On fail → emit `error`, keep key dirty, retry with exponential backoff
//                (2 s → 4 s → 8 s … capped at 30 s)
//
// In-flight guard: if markDirty arrives while a flush is in flight, we queue
// exactly one follow-up flush (not multiple) and fire it after the current
// settles.

import { stash, markFlushed } from './localStash'
import { autosaveStatus } from './autosaveStatusEvents'

const IDLE_DELAY_MS   = 2_000
const HARD_INTERVAL_MS = 30_000
const BACKOFF_BASE_MS  = 2_000
const BACKOFF_MAX_MS   = 30_000

// State shape per key:
// {
//   idleTimer:    number | null,
//   hardTimer:    number | null,
//   inFlight:     boolean,
//   pendingFlush: boolean,   // queued while in-flight
//   backoffMs:    number,
//   backoffTimer: number | null,
// }
const _keys = new Map()

function keyOf(workspaceId, filePath) {
  return `${workspaceId}\x00${filePath}`
}

function getOrInit(workspaceId, filePath) {
  const k = keyOf(workspaceId, filePath)
  if (!_keys.has(k)) {
    _keys.set(k, {
      idleTimer: null,
      hardTimer: null,
      inFlight: false,
      pendingFlush: false,
      backoffMs: BACKOFF_BASE_MS,
      backoffTimer: null,
    })
  }
  return _keys.get(k)
}

function cancelIdle(state) {
  if (state.idleTimer !== null) {
    clearTimeout(state.idleTimer)
    state.idleTimer = null
  }
}

function cancelBackoff(state) {
  if (state.backoffTimer !== null) {
    clearTimeout(state.backoffTimer)
    state.backoffTimer = null
  }
}

async function flush(workspaceId, filePath) {
  const state = getOrInit(workspaceId, filePath)

  if (state.inFlight) {
    // Queue exactly one follow-up; don't pile them up.
    state.pendingFlush = true
    return
  }

  // Cancel idle timer — we're flushing now.
  cancelIdle(state)

  state.inFlight = true
  autosaveStatus.emit('saving', { workspaceId, filePath })

  let bytes
  try {
    bytes = await stash(workspaceId, filePath)
  } catch (err) {
    state.inFlight = false
    handleFlushError(workspaceId, filePath, state)
    return
  }

  const url = `/workspaces/${workspaceId}/files/${encodeURIComponent(filePath)}/revisions`
  let res
  try {
    res = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/octet-stream' },
      body: bytes,
    })
  } catch (err) {
    state.inFlight = false
    handleFlushError(workspaceId, filePath, state)
    return
  }

  state.inFlight = false

  if (res.ok) {
    handleFlushSuccess(workspaceId, filePath, state)
  } else {
    handleFlushError(workspaceId, filePath, state)
  }
}

function handleFlushSuccess(workspaceId, filePath, state) {
  state.backoffMs = BACKOFF_BASE_MS
  cancelBackoff(state)

  autosaveStatus.emit('saved', { workspaceId, filePath })
  markFlushed(workspaceId, filePath)

  if (state.pendingFlush) {
    state.pendingFlush = false
    // A new dirty arrived while we were saving — flush it after idle delay.
    scheduleIdle(workspaceId, filePath, state)
  }
}

function handleFlushError(workspaceId, filePath, state) {
  autosaveStatus.emit('error', { workspaceId, filePath })

  // Don't call markFlushed — keep dirty state intact.

  const delay = state.backoffMs
  state.backoffMs = Math.min(state.backoffMs * 2, BACKOFF_MAX_MS)

  cancelBackoff(state)
  state.backoffTimer = setTimeout(() => {
    state.backoffTimer = null
    if (state.pendingFlush || !state.inFlight) {
      state.pendingFlush = false
      flush(workspaceId, filePath)
    }
  }, delay)
}

function scheduleIdle(workspaceId, filePath, state) {
  cancelIdle(state)
  state.idleTimer = setTimeout(() => {
    state.idleTimer = null
    flush(workspaceId, filePath)
  }, IDLE_DELAY_MS)
}

function ensureHardTimer(workspaceId, filePath, state) {
  if (state.hardTimer !== null) return
  state.hardTimer = setInterval(() => {
    flush(workspaceId, filePath)
  }, HARD_INTERVAL_MS)
}

/**
 * markDirty(workspaceId, filePath)
 *
 * Call this on every editor change. Thread-safe (single-threaded JS); idempotent
 * when called rapidly — only the last idle timer survives.
 */
export function markDirty(workspaceId, filePath) {
  const state = getOrInit(workspaceId, filePath)

  autosaveStatus.emit('dirty', { workspaceId, filePath })

  if (state.inFlight) {
    // While a flush is in flight, queue exactly one follow-up.
    state.pendingFlush = true
    return
  }

  // Restart the idle debounce.
  scheduleIdle(workspaceId, filePath, state)

  // Ensure the hard timer is ticking.
  ensureHardTimer(workspaceId, filePath, state)
}

/**
 * _resetForTesting() — clear all internal state between test cases.
 * Not exported in production builds; vitest imports it directly.
 */
export function _resetForTesting() {
  for (const state of _keys.values()) {
    cancelIdle(state)
    cancelBackoff(state)
    if (state.hardTimer !== null) {
      clearInterval(state.hardTimer)
      state.hardTimer = null
    }
  }
  _keys.clear()
}
