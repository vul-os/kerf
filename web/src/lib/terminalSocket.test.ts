/**
 * terminalSocket.test.ts — the terminal's wire protocol.
 *
 * Kept separate from the component so it can be tested without a DOM, a canvas
 * or a real socket. What matters here is that the client agrees with the server
 * about three things: where to connect, that control and data live on different
 * frame types, and that a refusal is not something to retry.
 */
import { afterEach, beforeEach, describe, it, expect } from 'vitest'
import {
  isRefusal,
  parseControl,
  recallSession,
  reconnectDelay,
  rememberSession,
  resizeMessage,
  sessionUrl,
} from './terminalSocket.js'

describe('sessionUrl', () => {
  it('upgrades http to ws and https to wss', () => {
    expect(sessionUrl('http://localhost:8080', { cols: 80, rows: 24 }))
      .toMatch(/^ws:\/\/localhost:8080\/api\/terminal\/session/)
    expect(sessionUrl('https://kerf.example', { cols: 80, rows: 24 }))
      .toMatch(/^wss:\/\/kerf\.example\/api\/terminal\/session/)
  })

  it('carries the window size so the first prompt is not drawn at 80 columns', () => {
    const url = new URL(sessionUrl('http://localhost:8080', { cols: 132, rows: 43 }))
    expect(url.searchParams.get('cols')).toBe('132')
    expect(url.searchParams.get('rows')).toBe('43')
  })

  it('asks for a specific session when re-attaching, and omits it otherwise', () => {
    const reattach = new URL(sessionUrl('http://x', { session: 'abc123', cols: 80, rows: 24 }))
    expect(reattach.searchParams.get('session')).toBe('abc123')

    const fresh = new URL(sessionUrl('http://x', { session: null, cols: 80, rows: 24 }))
    expect(fresh.searchParams.has('session')).toBe(false)
  })

  it('stays on the origin serving the page', () => {
    // A configurable host would be a way to point a terminal at the wrong
    // machine. The terminal is served by the process serving the app.
    expect(sessionUrl('http://192.168.1.9:8080', { cols: 80, rows: 24 }))
      .toContain('192.168.1.9:8080')
  })
})

describe('control frames', () => {
  it('reads the session hello', () => {
    const hello = parseControl(JSON.stringify({ type: 'session', id: 'deadbeef', reattached: true }))
    expect(hello).toEqual({ type: 'session', id: 'deadbeef', reattached: true })
  })

  it('treats a missing reattached flag as a fresh session', () => {
    expect(parseControl(JSON.stringify({ type: 'session', id: 'x' }))?.reattached).toBe(false)
  })

  it('returns null for anything it does not recognise', () => {
    // A server that grows a new control message must not take down a terminal
    // that is otherwise working.
    expect(parseControl('not json at all')).toBeNull()
    expect(parseControl(JSON.stringify({ type: 'something-new' }))).toBeNull()
    expect(parseControl(JSON.stringify({ type: 'session' }))).toBeNull()  // no id
    expect(parseControl('')).toBeNull()
  })

  it('builds a resize the server can read', () => {
    expect(JSON.parse(resizeMessage(120, 40))).toEqual({ type: 'resize', cols: 120, rows: 40 })
  })
})

describe('close handling', () => {
  it('treats a policy violation as a refusal', () => {
    // 1008 is what the server sends when a terminal is not allowed here.
    // Reconnecting would loop against a server that has already said no.
    expect(isRefusal(1008)).toBe(true)
  })

  it('treats an ordinary close as retryable', () => {
    // A session survives its socket, so these are worth reconnecting: the
    // shell is still there and the scrollback will be replayed.
    expect(isRefusal(1000)).toBe(false)
    expect(isRefusal(1006)).toBe(false)  // abnormal — wifi dropped
    expect(isRefusal(1011)).toBe(false)  // server error — may recover
  })
})

describe('reconnect backoff', () => {
  it('grows with each attempt', () => {
    const first = reconnectDelay(1)
    const later = reconnectDelay(5)
    expect(later).toBeGreaterThan(first)
  })

  it('is capped, so a long outage does not become an hour-long wait', () => {
    for (let attempt = 1; attempt <= 30; attempt++) {
      expect(reconnectDelay(attempt)).toBeLessThanOrEqual(15000 * 1.3)
    }
  })

  it('is never zero or negative, whatever it is handed', () => {
    for (const attempt of [0, -1, 1, 100]) {
      expect(reconnectDelay(attempt)).toBeGreaterThan(0)
    }
  })

  it('is jittered, so tabs waking together do not arrive together', () => {
    const samples = new Set(Array.from({ length: 20 }, () => reconnectDelay(4)))
    expect(samples.size).toBeGreaterThan(1)
  })
})

describe('remembering the session', () => {
  // A stub rather than jsdom: everything else in this file is deliberately
  // testable without a DOM, and one storage-shaped object is cheaper than an
  // environment.
  let store: Map<string, string>

  beforeEach(() => {
    store = new Map()
    Object.defineProperty(globalThis, 'sessionStorage', {
      configurable: true,
      value: {
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => void store.set(k, v),
        removeItem: (k: string) => void store.delete(k),
      },
    })
  })

  afterEach(() => {
    Reflect.deleteProperty(globalThis, 'sessionStorage')
  })

  it('survives the panel being unmounted and mounted again', () => {
    // The panel unmounts whenever the user looks at another tab in the same
    // drawer. Holding the id in a component ref meant the shell kept running
    // server-side while the browser could no longer reach it, and the user got
    // a fresh prompt with none of their state.
    rememberSession('abc123')
    expect(recallSession()).toBe('abc123')
  })

  it('reports nothing when there is nothing to remember', () => {
    expect(recallSession()).toBeNull()
  })

  it('can be cleared', () => {
    rememberSession('abc123')
    rememberSession(null)
    expect(recallSession()).toBeNull()
  })

  it('does not throw when storage is unavailable', () => {
    // Private-mode Safari and some embedded webviews throw on any access, and
    // so does any non-browser context this module gets imported into.
    Object.defineProperty(globalThis, 'sessionStorage', {
      configurable: true,
      get() { throw new Error('denied') },
    })
    expect(() => rememberSession('abc123')).not.toThrow()
    expect(recallSession()).toBeNull()
  })
})

describe('input while the socket is down', () => {
  // The panel owns the buffering, but the property is the protocol's: a
  // terminal that silently eats keystrokes during a reconnect is worse than
  // one that pauses. This pins the shape the panel implements — hold, then
  // flush in order, up to a bound.
  //
  // Modelled here rather than in a component test because it needs no DOM and
  // no canvas, which is the whole reason this module exists.
  function makeBuffer(limit: number) {
    const pending: string[] = []
    let bytes = 0
    let open = false
    const sent: string[] = []
    return {
      send(data: string) {
        if (open) { sent.push(data); return }
        if (bytes + data.length > limit) return
        pending.push(data)
        bytes += data.length
      },
      openSocket() {
        open = true
        while (pending.length) sent.push(pending.shift() as string)
        bytes = 0
      },
      sent,
    }
  }

  it('delivers what was typed before the socket opened', () => {
    const b = makeBuffer(4096)
    b.send('e'); b.send('c'); b.send('h'); b.send('o')
    expect(b.sent).toEqual([])
    b.openSocket()
    expect(b.sent.join('')).toBe('echo')
  })

  it('keeps the order it was typed in', () => {
    const b = makeBuffer(4096)
    b.send('a')
    b.openSocket()
    b.send('b')
    expect(b.sent.join('')).toBe('ab')
  })

  it('stops holding once the buffer is full', () => {
    // A server that is down for an hour must not replay an hour of typing the
    // moment it comes back.
    const b = makeBuffer(4)
    b.send('abcd')
    b.send('efgh')
    b.openSocket()
    expect(b.sent.join('')).toBe('abcd')
  })
})

describe('a socket that has been replaced', () => {
  /**
   * Re-opening the panel closes one socket and opens another, and a close
   * event is asynchronous — so the old socket's onclose can land *after* the
   * new one is live. The handlers used to act on the shared state
   * unconditionally, which meant the stale close nulled the reference to the
   * connection that had replaced it: the terminal reported "connected" and
   * swallowed every keystroke.
   *
   * Modelled here because the real thing needs a WebSocket, a DOM and a race.
   * What is pinned is the rule the component follows: a handler acts only if
   * its own socket is still the current one.
   */
  function makeRefHolder() {
    const state = { current: null as object | null, reconnects: 0, cleared: 0 }
    const open = (socket: object) => { state.current = socket }
    const close = (socket: object) => {
      const wasCurrent = state.current === socket
      if (wasCurrent) { state.current = null; state.cleared++ }
      if (!wasCurrent) return
      state.reconnects++
    }
    return { state, open, close }
  }

  it('a stale close leaves the live connection alone', () => {
    const { state, open, close } = makeRefHolder()
    const first = {}
    const second = {}

    open(first)
    open(second)   // the panel remounted before `first` finished closing
    close(first)   // ...and only now does the old close arrive

    expect(state.current).toBe(second)
    expect(state.cleared).toBe(0)
  })

  it('a stale close does not schedule a reconnect over a live connection', () => {
    const { state, open, close } = makeRefHolder()
    const first = {}
    const second = {}

    open(first)
    open(second)
    close(first)

    expect(state.reconnects).toBe(0)
  })

  it('the current socket closing still clears and reconnects', () => {
    const { state, open, close } = makeRefHolder()
    const only = {}

    open(only)
    close(only)

    expect(state.current).toBeNull()
    expect(state.reconnects).toBe(1)
  })
})
