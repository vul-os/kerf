// DerivedCacheOverlay.jsx — dev toggle showing derived-artifact cache stats.
//
// Displays a floating badge that tracks derived-artifact cache hits and misses
// for the current session. Click the badge to expand a panel showing per-kind
// counts, last payload size, and last age (seconds since server last_accessed_at).
//
// Usage: mount unconditionally in development-relevant layouts. The component
// is self-contained and does not import any production-critical store state —
// it subscribes directly to the assembly.js event bus (addDerivedCacheListener).
//
// Toggle: the badge is always visible when rendered. Production builds can
// gate the import behind `import.meta.env.DEV` at the call site.

import { useEffect, useReducer, useRef, useState } from 'react'
import { Database, X } from 'lucide-react'
import { addDerivedCacheListener } from '../lib/assembly.js'

// ---------------------------------------------------------------------------
// State reducer
// ---------------------------------------------------------------------------

const INITIAL_STATE = {
  // session totals
  hits: 0,
  misses: 0,
  // per-kind last event: derivedKind → { hit, payloadSize, age, timestamp }
  byKind: {},
  // flat log (last N)
  log: [],
}

const MAX_LOG = 20

function statsReducer(state, evt) {
  const { hit, derivedKind, payloadSize, age, timestamp } = evt
  const entry = { hit, derivedKind, payloadSize, age, timestamp }
  return {
    hits: state.hits + (hit ? 1 : 0),
    misses: state.misses + (hit ? 0 : 1),
    byKind: { ...state.byKind, [derivedKind]: entry },
    log: [entry, ...state.log].slice(0, MAX_LOG),
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function HitBadge({ hit }) {
  return hit
    ? <span className="inline-block px-1 rounded text-[9px] font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">HIT</span>
    : <span className="inline-block px-1 rounded text-[9px] font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/30">MISS</span>
}

function KindRow({ kind, entry }) {
  const ageStr = entry.age != null ? `${entry.age}s ago` : '—'
  const sizeStr = entry.payloadSize != null ? formatBytes(entry.payloadSize) : '—'
  return (
    <tr className="border-b border-white/5">
      <td className="py-0.5 pr-2 text-white/60 text-[10px] font-mono whitespace-nowrap">{kind}</td>
      <td className="py-0.5 pr-2"><HitBadge hit={entry.hit} /></td>
      <td className="py-0.5 pr-2 text-[10px] text-white/60 text-right tabular-nums">{sizeStr}</td>
      <td className="py-0.5 text-[10px] text-white/50 text-right tabular-nums">{ageStr}</td>
    </tr>
  )
}

function formatBytes(n) {
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} kB`
  return `${(n / (1024 * 1024)).toFixed(2)} MB`
}

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * DerivedCacheOverlay — floating dev panel for derived-artifact cache stats.
 *
 * Props:
 *   position  — 'bottom-left' | 'bottom-right' (default 'bottom-right')
 *   defaultOpen — start expanded (default false)
 */
export default function DerivedCacheOverlay({ position = 'bottom-right', defaultOpen = false }) {
  const [stats, dispatch] = useReducer(statsReducer, INITIAL_STATE)
  const [open, setOpen] = useState(defaultOpen)
  const panelRef = useRef(null)

  useEffect(() => {
    return addDerivedCacheListener(dispatch)
  }, [])

  const total = stats.hits + stats.misses
  const hitRate = total > 0 ? Math.round((stats.hits / total) * 100) : null

  const posClass = position === 'bottom-left'
    ? 'bottom-4 left-4'
    : 'bottom-4 right-4'

  return (
    <div
      ref={panelRef}
      className={`fixed z-[9999] ${posClass} flex flex-col items-end gap-1`}
      data-component="DerivedCacheOverlay"
    >
      {open && (
        <div className="bg-zinc-900/95 border border-white/10 rounded-lg shadow-2xl w-72 text-white overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between px-3 py-2 border-b border-white/10 bg-white/5">
            <div className="flex items-center gap-1.5">
              <Database size={12} className="text-white/60" />
              <span className="text-[11px] font-semibold text-white/80">Derived Cache</span>
            </div>
            <button
              onClick={() => setOpen(false)}
              className="text-white/40 hover:text-white transition-colors"
              aria-label="Close"
            >
              <X size={12} />
            </button>
          </div>

          {/* Totals */}
          <div className="flex items-center gap-3 px-3 py-2 border-b border-white/5">
            <div className="text-center">
              <div className="text-[18px] font-bold text-emerald-400 tabular-nums leading-none">{stats.hits}</div>
              <div className="text-[9px] text-white/40 uppercase tracking-wider mt-0.5">hits</div>
            </div>
            <div className="text-center">
              <div className="text-[18px] font-bold text-amber-400 tabular-nums leading-none">{stats.misses}</div>
              <div className="text-[9px] text-white/40 uppercase tracking-wider mt-0.5">misses</div>
            </div>
            {hitRate != null && (
              <div className="ml-auto text-right">
                <div className="text-[15px] font-semibold text-white/70 tabular-nums leading-none">{hitRate}%</div>
                <div className="text-[9px] text-white/40 uppercase tracking-wider mt-0.5">hit rate</div>
              </div>
            )}
          </div>

          {/* Per-kind table */}
          {Object.keys(stats.byKind).length > 0 && (
            <div className="px-3 py-2 border-b border-white/5">
              <div className="text-[9px] text-white/40 uppercase tracking-wider mb-1.5">By kind</div>
              <table className="w-full border-collapse">
                <thead>
                  <tr>
                    <th className="text-left text-[9px] text-white/30 font-normal pb-0.5">kind</th>
                    <th className="text-left text-[9px] text-white/30 font-normal pb-0.5">result</th>
                    <th className="text-right text-[9px] text-white/30 font-normal pb-0.5">size</th>
                    <th className="text-right text-[9px] text-white/30 font-normal pb-0.5">age</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(stats.byKind).map(([kind, entry]) => (
                    <KindRow key={kind} kind={kind} entry={entry} />
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Log */}
          {stats.log.length > 0 && (
            <div className="px-3 py-2 max-h-40 overflow-y-auto">
              <div className="text-[9px] text-white/40 uppercase tracking-wider mb-1.5">Recent events</div>
              {stats.log.map((e, i) => (
                <div key={i} className="flex items-center gap-1.5 py-0.5">
                  <HitBadge hit={e.hit} />
                  <span className="text-[9px] font-mono text-white/50 truncate flex-1">{e.derivedKind}</span>
                  {e.payloadSize != null && (
                    <span className="text-[9px] text-white/40 tabular-nums">{formatBytes(e.payloadSize)}</span>
                  )}
                  <span className="text-[9px] text-white/30 tabular-nums">{formatTime(e.timestamp)}</span>
                </div>
              ))}
            </div>
          )}

          {total === 0 && (
            <div className="px-3 py-4 text-center text-[11px] text-white/30">
              No cache lookups yet this session.
            </div>
          )}
        </div>
      )}

      {/* Toggle badge */}
      <button
        onClick={() => setOpen((v) => !v)}
        className={[
          'flex items-center gap-1.5 px-2 py-1 rounded-full text-[10px] font-semibold',
          'border shadow-lg transition-all',
          total === 0
            ? 'bg-zinc-800/90 border-white/10 text-white/50'
            : stats.hits > stats.misses
              ? 'bg-emerald-900/80 border-emerald-500/30 text-emerald-300'
              : 'bg-amber-900/80 border-amber-500/30 text-amber-300',
        ].join(' ')}
        aria-label="Toggle derived cache stats"
        title="Derived-artifact cache stats"
      >
        <Database size={10} />
        {total > 0 ? (
          <span>{stats.hits}H / {stats.misses}M</span>
        ) : (
          <span>cache</span>
        )}
      </button>
    </div>
  )
}
