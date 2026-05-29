/**
 * SerialMonitor.jsx — live serial output panel (board → server → poll/SSE).
 *
 * Calls POST /firmware/monitor via firmwareBridge.monitorFirmware() to take
 * a snapshot of the board's serial output. A "Stream" toggle re-polls every
 * POLL_INTERVAL_MS while active, appending new lines to the display buffer.
 *
 * Matching the PlatformIO / Arduino IDE serial monitor parity item:
 *   - Port + baud-rate configuration
 *   - Send arbitrary text to the board (POST /firmware/monitor with tx_line)
 *   - Autoscroll toggle
 *   - Clear button
 *
 * Props:
 *   fwConfig  {object|null}  — parsed kerf.fw.json (for port + baud defaults)
 *   projectId {string}       — for constructing the API path
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Activity, Send, Trash2, ChevronsDown, Square, Play } from 'lucide-react'
import { monitorFirmware } from '../../lib/firmwareBridge.js'

const POLL_INTERVAL_MS = 2000
const MAX_LINES = 500  // keep buffer bounded

export default function SerialMonitor({ fwConfig = null, projectId = null }) {
  const [lines, setLines] = useState([])
  const [streaming, setStreaming] = useState(false)
  const [autoScroll, setAutoScroll] = useState(true)
  const [port, setPort] = useState(fwConfig?.upload?.port || '')
  const [baud, setBaud] = useState(fwConfig?.monitor?.baud || 9600)
  const [txLine, setTxLine] = useState('')
  const [error, setError] = useState(null)
  const bottomRef = useRef(null)
  const pollRef = useRef(null)

  // Autoscroll.
  useEffect(() => {
    if (autoScroll) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [lines, autoScroll])

  // Poll the backend for serial data.
  const doPoll = useCallback(async () => {
    const result = await monitorFirmware(fwConfig, port || null, baud)
    if (!result.ok) {
      setError(result.errors?.[0] || 'Monitor error')
      setStreaming(false)
      return
    }
    setError(null)
    if (result.lines?.length) {
      setLines((prev) => {
        const next = [...prev, ...result.lines]
        return next.length > MAX_LINES ? next.slice(next.length - MAX_LINES) : next
      })
    }
  }, [fwConfig, port, baud])

  // Start / stop streaming.
  useEffect(() => {
    if (!streaming) {
      if (pollRef.current) clearInterval(pollRef.current)
      return
    }
    doPoll()
    pollRef.current = setInterval(doPoll, POLL_INTERVAL_MS)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [streaming, doPoll])

  async function handleSend(e) {
    e.preventDefault()
    if (!txLine.trim()) return
    // Fire the monitor endpoint with a tx_line field — backend echoes it.
    await monitorFirmware({ ...(fwConfig || {}), tx_line: txLine }, port || null, baud)
    setTxLine('')
  }

  function handleClear() {
    setLines([])
    setError(null)
  }

  return (
    <div
      className="flex flex-col h-full min-h-0 bg-ink-950 border border-ink-800 rounded-md overflow-hidden"
      data-testid="serial-monitor"
    >
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-ink-800 bg-ink-900/60 flex-shrink-0 flex-wrap">
        <Activity size={12} className="text-green-300 flex-shrink-0" />
        <span className="text-[11px] text-ink-300 font-medium">Serial Monitor</span>

        {/* Port */}
        <input
          type="text"
          value={port}
          onChange={(e) => setPort(e.target.value)}
          placeholder="/dev/ttyUSB0"
          className="w-32 bg-ink-800 border border-ink-700 rounded px-1.5 py-0.5 text-[10px] font-mono text-ink-100 outline-none focus:border-kerf-300/60"
          aria-label="Serial port"
        />

        {/* Baud */}
        <select
          value={baud}
          onChange={(e) => setBaud(Number(e.target.value))}
          className="bg-ink-800 border border-ink-700 rounded px-1.5 py-0.5 text-[10px] text-ink-100 outline-none focus:border-kerf-300/60"
          aria-label="Baud rate"
        >
          {[9600, 19200, 38400, 57600, 115200, 230400].map((b) => (
            <option key={b} value={b}>{b}</option>
          ))}
        </select>

        <div className="flex-1" />

        {/* Autoscroll toggle */}
        <button
          type="button"
          title={autoScroll ? 'Disable autoscroll' : 'Enable autoscroll'}
          onClick={() => setAutoScroll((v) => !v)}
          className={`p-0.5 rounded transition-colors ${
            autoScroll ? 'text-kerf-300 bg-kerf-300/10' : 'text-ink-500 hover:text-ink-300'
          }`}
        >
          <ChevronsDown size={12} />
        </button>

        {/* Clear */}
        <button
          type="button"
          title="Clear"
          onClick={handleClear}
          className="p-0.5 rounded text-ink-500 hover:text-ink-300 transition-colors"
        >
          <Trash2 size={12} />
        </button>

        {/* Stream toggle */}
        <button
          type="button"
          onClick={() => setStreaming((v) => !v)}
          title={streaming ? 'Stop streaming' : 'Start streaming'}
          className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium border transition-colors ${
            streaming
              ? 'bg-red-900/40 border-red-700/60 text-red-300 hover:bg-red-900/60'
              : 'bg-green-900/30 border-green-700/50 text-green-300 hover:bg-green-900/50'
          }`}
        >
          {streaming ? <Square size={10} /> : <Play size={10} />}
          {streaming ? 'Stop' : 'Stream'}
        </button>
      </div>

      {/* Output */}
      <div className="flex-1 min-h-0 overflow-y-auto font-mono text-[11px] leading-relaxed p-2 space-y-0.5">
        {error && (
          <div className="mb-2 rounded bg-red-950/60 border border-red-700/40 px-2 py-1 text-red-300">
            {error}
          </div>
        )}
        {lines.length === 0 && !streaming && !error && (
          <span className="text-ink-600 italic">
            No data yet. Connect a board and click Stream.
          </span>
        )}
        {lines.map((line, i) => (
          <div key={i} className="text-green-200/90">
            {line || <span className="text-ink-700">&nbsp;</span>}
          </div>
        ))}
        {streaming && (
          <span className="text-kerf-300 animate-pulse text-[10px]">▋</span>
        )}
        <div ref={bottomRef} />
      </div>

      {/* TX input */}
      <form
        onSubmit={handleSend}
        className="flex items-center gap-2 px-3 py-2 border-t border-ink-800 bg-ink-900/40 flex-shrink-0"
      >
        <input
          type="text"
          value={txLine}
          onChange={(e) => setTxLine(e.target.value)}
          placeholder="Send to board…"
          className="flex-1 bg-ink-800 border border-ink-700 rounded px-2 py-1 text-[11px] font-mono text-ink-100 outline-none focus:border-kerf-300/60"
          aria-label="Transmit line"
        />
        <button
          type="submit"
          disabled={!txLine.trim()}
          className="flex items-center gap-1 px-2 py-1 rounded bg-kerf-300/10 border border-kerf-300/30 text-kerf-200 hover:bg-kerf-300/20 disabled:opacity-40 text-[10px]"
        >
          <Send size={10} />
          Send
        </button>
      </form>
    </div>
  )
}
