import { useEffect, useRef, useState } from 'react'
import { AlertCircle, Loader2, TerminalSquare } from 'lucide-react'
import { FitAddon } from '@xterm/addon-fit'
import { Terminal } from '@xterm/xterm'
import '@xterm/xterm/css/xterm.css'
import { api } from '../lib/api.js'
import {
  isRefusal,
  parseControl,
  recallSession,
  reconnectDelay,
  rememberSession,
  resizeMessage,
  sessionUrl,
  type TerminalCapability,
} from '../lib/terminalSocket.js'

/**
 * A real terminal, with the `kerf` CLI already on its PATH.
 *
 * The shell runs as the OS user that started the server, with no sandbox — so
 * whether it is offered at all is the server's decision, not this component's.
 * It asks /api/terminal/capability first and renders the server's own reason
 * when the answer is no, rather than showing a terminal that would refuse to
 * connect.
 *
 * Sessions outlive their socket. A dropped connection re-attaches to the same
 * shell and is replayed the scrollback, so closing a laptop does not kill a
 * running build. A refusal is not retried: the server has already said no and
 * looping would only make that louder.
 */
export default function TerminalPanel() {
  const mountRef = useRef<HTMLDivElement | null>(null)
  const termRef = useRef<Terminal | null>(null)
  const socketRef = useRef<WebSocket | null>(null)
  // Seeded from storage, not null: this panel unmounts every time the user
  // looks at another tab, and a ref that starts empty re-attaches to nothing.
  const sessionRef = useRef<string | null>(recallSession())
  const attemptRef = useRef(0)
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const closedByUs = useRef(false)

  const [capability, setCapability] = useState<TerminalCapability | null>(null)
  const [status, setStatus] = useState<'connecting' | 'open' | 'closed' | 'refused'>('connecting')
  const [refusal, setRefusal] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api.terminalCapability()
      .then((cap) => { if (!cancelled) setCapability(cap) })
      .catch(() => {
        if (!cancelled) {
          setCapability({
            available: false,
            reason: 'Could not ask the server whether a terminal is available.',
            platform: '', sandboxed: false, sessions: [],
          })
        }
      })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!capability?.available || !mountRef.current) return

    const term = new Terminal({
      convertEol: false,
      cursorBlink: true,
      fontSize: 12,
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
      theme: {
        background: '#0a0b0d',
        foreground: '#cbd0dc',
        cursor: '#ffd633',
        selectionBackground: '#ffd63340',
      },
      // Enough to scroll back through a build without holding a session's
      // entire output in the tab.
      scrollback: 5000,
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(mountRef.current)
    fit.fit()
    termRef.current = term

    const encoder = new TextEncoder()
    let disposed = false

    const connect = () => {
      if (disposed) return
      setStatus('connecting')
      const socket = new WebSocket(sessionUrl(window.location.origin, {
        session: sessionRef.current,
        cols: term.cols,
        rows: term.rows,
      }))
      socket.binaryType = 'arraybuffer'
      socketRef.current = socket

      socket.onopen = () => {
        attemptRef.current = 0
        setStatus('open')
        term.focus()
      }

      socket.onmessage = (event) => {
        if (typeof event.data === 'string') {
          const hello = parseControl(event.data)
          if (hello) {
            sessionRef.current = hello.id
            rememberSession(hello.id)
            // A fresh session starts on a clean screen; a re-attached one is
            // about to be replayed its scrollback, so clearing first avoids
            // showing the same output twice.
            if (hello.reattached) term.clear()
          }
          return
        }
        term.write(new Uint8Array(event.data as ArrayBuffer))
      }

      socket.onclose = (event) => {
        socketRef.current = null
        if (disposed || closedByUs.current) return
        if (isRefusal(event.code)) {
          setStatus('refused')
          setRefusal(event.reason || 'The server refused a terminal session.')
          return
        }
        setStatus('closed')
        attemptRef.current += 1
        retryRef.current = setTimeout(connect, reconnectDelay(attemptRef.current))
      }
    }

    const send = (data: string) => {
      const socket = socketRef.current
      if (socket?.readyState === WebSocket.OPEN) socket.send(encoder.encode(data))
    }
    const inputSub = term.onData(send)

    const pushSize = () => {
      fit.fit()
      const socket = socketRef.current
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(resizeMessage(term.cols, term.rows))
      }
    }
    const observer = new ResizeObserver(pushSize)
    observer.observe(mountRef.current)

    connect()

    return () => {
      disposed = true
      closedByUs.current = true
      inputSub.dispose()
      observer.disconnect()
      if (retryRef.current) clearTimeout(retryRef.current)
      // Close the socket, not the session: the shell stays alive server-side
      // so re-opening the panel picks the same one back up.
      socketRef.current?.close()
      term.dispose()
      termRef.current = null
      closedByUs.current = false
    }
  }, [capability?.available])

  if (!capability) {
    return (
      <div className="h-full grid place-items-center text-sm text-ink-500">
        <span className="flex items-center gap-2">
          <Loader2 size={14} className="animate-spin" aria-hidden />
          Checking…
        </span>
      </div>
    )
  }

  if (!capability.available || status === 'refused') {
    return (
      <div className="h-full overflow-y-auto p-5">
        <div className="max-w-md mx-auto">
          <div className="flex items-center gap-2 mb-2">
            <TerminalSquare size={16} className="text-ink-400" aria-hidden />
            <h2 className="font-display text-base font-semibold tracking-tight">
              No terminal here
            </h2>
          </div>
          <div
            role="status"
            className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 text-[12px] text-amber-100 leading-relaxed"
          >
            <AlertCircle size={14} className="mt-0.5 shrink-0" aria-hidden />
            {/* The server's own words: it knows what it is bound to, and a
                second copy of that reasoning here is one that can drift. */}
            <span>{refusal || capability.reason}</span>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col bg-[#0a0b0d]">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-ink-800 shrink-0">
        <span className="flex items-center gap-1.5 text-[10px] font-mono uppercase tracking-[0.18em] text-ink-500">
          <TerminalSquare size={11} aria-hidden />
          Terminal
        </span>
        <span
          className={
            status === 'open'
              ? 'text-[10px] font-mono text-kerf-300'
              : 'text-[10px] font-mono text-amber-300'
          }
          role="status"
          aria-live="polite"
        >
          {status === 'open' ? 'connected' : status === 'connecting' ? 'connecting…' : 'reconnecting…'}
        </span>
      </div>
      <div ref={mountRef} className="flex-1 min-h-0 p-2" />
    </div>
  )
}
