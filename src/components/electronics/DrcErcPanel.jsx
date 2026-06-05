// DrcErcPanel.jsx — DRC/ERC results overlay panel.
//
// Displays violation list returned by the backend run_pcb_drc and run_erc tools.
// Shows coloured markers (error = red, warning = yellow) and a summary badge.
// Backend contracts:
//   POST /api/llm-tools/run_pcb_drc  {circuit_json: [...]}  → {violations, error_count, warning_count}
//   POST /api/llm-tools/run_erc      {circuit_json: [...]}  → {errors: [...], warnings: [...]}
//
// Props:
//   circuitJson      — array of CircuitJSON elements (board + schematic)
//   onClose          — () => void
//   onMarkerClick    — ({x, y, kind}) => void  (optional, scrolls canvas to violation)

import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, XCircle, CheckCircle2, X, RefreshCw } from 'lucide-react'

// ── severity colour helpers ───────────────────────────────────────────────────

function SeverityIcon({ severity, size = 14 }) {
  if (severity === 'error')
    return <XCircle size={size} className="text-red-400 shrink-0" />
  return <AlertTriangle size={size} className="text-yellow-400 shrink-0" />
}

// ── Individual violation row ─────────────────────────────────────────────────

function ViolationRow({ v, onClick }) {
  return (
    <button
      className="w-full text-left flex items-start gap-2 px-2 py-1.5 hover:bg-white/5 rounded transition-colors"
      onClick={() => onClick && onClick(v)}
      title={v.message}
    >
      <SeverityIcon severity={v.severity} />
      <div className="min-w-0">
        <span className="block text-[11px] text-gray-300 truncate">{v.message}</span>
        {(v.x != null && v.y != null) && (
          <span className="block text-[10px] text-gray-600">
            @ ({Number(v.x).toFixed(2)}, {Number(v.y).toFixed(2)}) mm
          </span>
        )}
      </div>
      {v.kind && (
        <span className="ml-auto text-[10px] text-gray-600 shrink-0">{v.kind}</span>
      )}
    </button>
  )
}

// ── ERC row ──────────────────────────────────────────────────────────────────

function ErcRow({ item, onClick }) {
  const severity = item.severity === 'error' ? 'error' : 'warning'
  return (
    <button
      className="w-full text-left flex items-start gap-2 px-2 py-1.5 hover:bg-white/5 rounded transition-colors"
      onClick={() => onClick && onClick(item)}
    >
      <SeverityIcon severity={severity} />
      <div className="min-w-0">
        <span className="block text-[11px] text-gray-300 truncate">{item.message}</span>
        {item.net_id && (
          <span className="block text-[10px] text-gray-600">net: {item.net_id}</span>
        )}
        {item.component_id && (
          <span className="block text-[10px] text-gray-600">ref: {item.component_id}</span>
        )}
      </div>
      {item.kind && (
        <span className="ml-auto text-[10px] text-gray-600 shrink-0">{item.kind}</span>
      )}
    </button>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

export default function DrcErcPanel({ circuitJson, onClose, onMarkerClick }) {
  const [tab, setTab] = useState('drc')
  const [drcResult, setDrcResult] = useState(null)
  const [ercResult, setErcResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const abortRef = useRef(null)

  const runChecks = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort()
    const ac = new AbortController()
    abortRef.current = ac

    setLoading(true)
    setError(null)

    const board = Array.isArray(circuitJson) ? circuitJson : []

    try {
      const [drcRes, ercRes] = await Promise.allSettled([
        fetch('/api/llm-tools/run_pcb_drc', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ circuit_json: board }),
          signal: ac.signal,
        }).then((r) => r.json()),
        fetch('/api/llm-tools/run_erc', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ circuit_json: board }),
          signal: ac.signal,
        }).then((r) => r.json()),
      ])

      if (!ac.signal.aborted) {
        if (drcRes.status === 'fulfilled') {
          const d = drcRes.value
          setDrcResult(d?.result ?? d)
        } else {
          setDrcResult(null)
        }
        if (ercRes.status === 'fulfilled') {
          const e = ercRes.value
          setErcResult(e?.result ?? e)
        } else {
          setErcResult(null)
        }
      }
    } catch (err) {
      if (!ac.signal.aborted) {
        setError('Backend offline — DRC/ERC requires a running Kerf server.')
        // Show mock demo data
        setDrcResult({
          violations: [
            {
              kind: 'demo',
              severity: 'warning',
              message: 'Demo mode: connect backend to see real DRC violations.',
              x: 0, y: 0,
            },
          ],
          error_count: 0,
          warning_count: 1,
        })
        setErcResult({
          errors: [],
          warnings: [
            {
              kind: 'demo',
              severity: 'warning',
              message: 'Demo mode: connect backend to see real ERC violations.',
            },
          ],
        })
      }
    } finally {
      if (!ac.signal.aborted) setLoading(false)
    }
  }, [circuitJson])

  // Run once on mount
  useEffect(() => {
    runChecks()
    return () => abortRef.current?.abort()
  }, [runChecks])

  const drcViolations = drcResult?.violations ?? []
  const drcErrors     = drcResult?.error_count   ?? drcViolations.filter((v) => v.severity === 'error').length
  const drcWarnings   = drcResult?.warning_count ?? drcViolations.filter((v) => v.severity === 'warning').length

  const ercErrors   = ercResult?.errors   ?? []
  const ercWarnings = ercResult?.warnings ?? []
  const ercErrorCnt   = ercErrors.length
  const ercWarningCnt = ercWarnings.length

  const drcOk = drcErrors === 0 && drcWarnings === 0
  const ercOk = ercErrorCnt === 0 && ercWarningCnt === 0

  return (
    <div
      data-testid="drc-erc-panel"
      className="flex flex-col bg-[#0d1117] border border-white/10 rounded-lg shadow-2xl text-xs font-mono"
      style={{ width: 380, maxHeight: 480 }}
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-white/10 bg-[#161b22] rounded-t-lg">
        <span className="font-semibold text-gray-200 text-[12px]">DRC / ERC Results</span>
        <div className="flex items-center gap-1.5 ml-1">
          {drcOk
            ? <CheckCircle2 size={13} className="text-emerald-400" />
            : <XCircle size={13} className="text-red-400" />}
          <span className={drcErrors > 0 ? 'text-red-400' : 'text-gray-500'}>
            {drcErrors}E
          </span>
          <span className={drcWarnings > 0 ? 'text-yellow-400' : 'text-gray-500'}>
            {drcWarnings}W
          </span>
          <span className="text-gray-600 mx-1">|</span>
          {ercOk
            ? <CheckCircle2 size={13} className="text-emerald-400" />
            : <XCircle size={13} className="text-red-400" />}
          <span className={ercErrorCnt > 0 ? 'text-red-400' : 'text-gray-500'}>
            {ercErrorCnt}E
          </span>
          <span className={ercWarningCnt > 0 ? 'text-yellow-400' : 'text-gray-500'}>
            {ercWarningCnt}W
          </span>
        </div>

        <div className="flex items-center gap-1 ml-auto">
          <button
            data-testid="drc-erc-refresh"
            onClick={runChecks}
            disabled={loading}
            title="Re-run checks"
            className="p-1 rounded hover:bg-white/10 text-gray-500 hover:text-white transition-colors disabled:opacity-40"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          </button>
          <button
            data-testid="drc-erc-close"
            onClick={onClose}
            className="p-1 rounded hover:bg-white/10 text-gray-500 hover:text-white transition-colors"
          >
            <X size={12} />
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-white/10">
        {[
          { key: 'drc', label: `DRC (${drcErrors + drcWarnings})` },
          { key: 'erc', label: `ERC (${ercErrorCnt + ercWarningCnt})` },
        ].map(({ key, label }) => (
          <button
            key={key}
            data-testid={`drc-erc-tab-${key}`}
            onClick={() => setTab(key)}
            className={[
              'px-4 py-1.5 text-xs font-medium transition-colors border-b-2',
              tab === key
                ? 'border-indigo-500 text-indigo-300'
                : 'border-transparent text-gray-500 hover:text-gray-300',
            ].join(' ')}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-1" data-testid="drc-erc-list">
        {loading && (
          <div className="flex items-center justify-center py-8 text-gray-500">
            <RefreshCw size={14} className="animate-spin mr-2" />
            Running checks…
          </div>
        )}

        {!loading && error && tab === 'drc' && (
          <p className="px-2 py-2 text-yellow-500 text-[11px]">{error}</p>
        )}

        {!loading && tab === 'drc' && (
          <>
            {drcViolations.length === 0 ? (
              <div className="flex items-center gap-2 px-2 py-4 text-emerald-400">
                <CheckCircle2 size={14} />
                <span>No DRC violations</span>
              </div>
            ) : (
              drcViolations.map((v, i) => (
                <ViolationRow key={i} v={v} onClick={onMarkerClick} />
              ))
            )}
          </>
        )}

        {!loading && tab === 'erc' && (
          <>
            {ercErrors.length === 0 && ercWarnings.length === 0 ? (
              <div className="flex items-center gap-2 px-2 py-4 text-emerald-400">
                <CheckCircle2 size={14} />
                <span>No ERC violations</span>
              </div>
            ) : (
              <>
                {ercErrors.map((v, i) => (
                  <ErcRow key={`e${i}`} item={v} onClick={onMarkerClick} />
                ))}
                {ercWarnings.map((v, i) => (
                  <ErcRow key={`w${i}`} item={v} onClick={onMarkerClick} />
                ))}
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}
