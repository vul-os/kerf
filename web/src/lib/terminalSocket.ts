/**
 * The WebSocket half of the terminal, kept out of the React component.
 *
 * Separated so the protocol can be tested without a DOM, a canvas or a real
 * socket: the component's job is to own an xterm instance, and this file's job
 * is to know that binary frames are PTY bytes and text frames are control.
 * That split is the protocol's own — a resize must never be readable as
 * keystrokes, whatever the payload happens to contain.
 */

export interface TerminalCapability {
  available: boolean
  reason: string
  platform: string
  sandboxed: boolean
  sessions: string[]
}

export interface SessionHello {
  type: 'session'
  id: string
  reattached: boolean
}

/**
 * The ws:// URL for a terminal session.
 *
 * Derived from the page's own origin rather than configured: the terminal is
 * served by the same process serving the app, and a separately-configured host
 * would be a way to point a terminal at the wrong machine.
 */
export function sessionUrl(
  origin: string,
  { session, cols, rows }: { session?: string | null; cols: number; rows: number },
): string {
  const url = new URL('/api/terminal/session', origin)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  if (session) url.searchParams.set('session', session)
  url.searchParams.set('cols', String(cols))
  url.searchParams.set('rows', String(rows))
  return url.toString()
}

/** A resize, as the server expects it. */
export function resizeMessage(cols: number, rows: number): string {
  return JSON.stringify({ type: 'resize', cols, rows })
}

/**
 * Parse a text frame from the server.
 *
 * Returns null for anything unrecognised rather than throwing: a server that
 * grows a new control message should not take down a terminal that is
 * otherwise working.
 */
export function parseControl(data: string): SessionHello | null {
  try {
    const parsed = JSON.parse(data)
    if (parsed && parsed.type === 'session' && typeof parsed.id === 'string') {
      return { type: 'session', id: parsed.id, reattached: !!parsed.reattached }
    }
  } catch {
    // Not JSON. Nothing sane to do with it.
  }
  return null
}

/**
 * Whether a close code should be shown to the user as a refusal rather than
 * as a dropped connection.
 *
 * 1008 is "policy violation", which is what the server sends when the
 * terminal is not allowed here. Reconnecting on that would loop forever
 * against a server that has already said no.
 */
export function isRefusal(code: number): boolean {
  return code === 1008
}

/**
 * Backoff before reconnecting, in ms.
 *
 * A session survives its socket, so reconnecting re-attaches to the same shell
 * — worth retrying, but not in a tight loop against a server that is down.
 */
export function reconnectDelay(attempt: number): number {
  const base = Math.min(1000 * 2 ** Math.max(0, attempt - 1), 15000)
  // Jitter so several tabs reconnecting after a laptop wakes do not arrive
  // together.
  return Math.round(base * (0.7 + Math.random() * 0.6))
}
