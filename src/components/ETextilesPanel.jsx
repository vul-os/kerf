// ETextilesPanel — display panel for textiles_etextiles tool results.
//
// Renders two modes:
//   'heater'     — I²R resistive-yarn heater: trace resistance, power, voltage drop
//   'led_layout' — parallel/series LED fabric network: branch currents, total power
//
// Props
// ─────
//   result      {Object|string|null}  — parsed output from textiles_etextiles tool
//   className   {string}              — extra CSS classes on root
//
// Exported pure helpers for vitest:
//   parseETextilesResult(raw)       → { kind, mode, data, error? }
//   fmtWatts(n)                     → "N.NN W" string
//   fmtOhms(n)                      → "N.NN Ω" string
//   fmtMilliamps(n)                 → "NNN mA" string

import { useMemo } from 'react'
import { Zap, CircuitBoard } from 'lucide-react'

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests)
// ---------------------------------------------------------------------------

/**
 * Parse raw textiles_etextiles tool result.
 * Returns { kind: 'ok'|'empty'|'invalid', mode, data, error? }
 */
export function parseETextilesResult(raw) {
  if (raw == null) return { kind: 'empty' }
  const obj = typeof raw === 'string'
    ? (() => { try { return JSON.parse(raw) } catch { return null } })()
    : raw
  if (!obj || typeof obj !== 'object') return { kind: 'invalid', error: 'Expected JSON object' }
  if (obj.error) return { kind: 'invalid', error: obj.error }
  if (obj.ok === false) return { kind: 'invalid', error: obj.error || 'Tool returned ok:false' }

  const mode = obj.mode ?? null
  if (!mode) return { kind: 'invalid', error: 'Missing mode field' }

  return { kind: 'ok', mode, data: obj }
}

/**
 * Format watts — "N.NN W" or "—".
 */
export function fmtWatts(n) {
  if (n == null || !Number.isFinite(n)) return '—'
  return `${n.toFixed(3)} W`
}

/**
 * Format ohms — "N.NN Ω" or "—".
 */
export function fmtOhms(n) {
  if (n == null || !Number.isFinite(n)) return '—'
  return `${n.toFixed(3)} Ω`
}

/**
 * Format milliamps — "NNN.N mA" or "—".
 */
export function fmtMilliamps(n) {
  if (n == null || !Number.isFinite(n)) return '—'
  return `${(n * 1000).toFixed(1)} mA`
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatGrid({ rows }) {
  return (
    <div
      className="grid grid-cols-2 gap-2 mt-2"
      data-testid="etextiles-stat-grid"
    >
      {rows.map(([label, value]) => (
        <div key={label} className="rounded-lg border border-ink-800 bg-ink-950/50 px-3 py-2">
          <p className="text-[10px] font-mono uppercase tracking-wider text-ink-500">{label}</p>
          <p className="mt-0.5 font-mono text-sm text-ink-200">{value}</p>
        </div>
      ))}
    </div>
  )
}

function HeaterView({ data }) {
  const rows = [
    ['Resistance', fmtOhms(data.resistance_ohm)],
    ['Power (I²R)', fmtWatts(data.power_w)],
    ['Voltage drop', data.voltage_drop_v != null ? `${data.voltage_drop_v.toFixed(3)} V` : '—'],
    ['Trace length', data.length_m != null ? `${data.length_m.toFixed(2)} m` : '—'],
  ]
  return (
    <div data-testid="etextiles-heater-view">
      <p className="text-xs text-ink-400 mb-1">
        Resistive-yarn heater trace — I²R power dissipation
      </p>
      <StatGrid rows={rows} />
    </div>
  )
}

function LEDLayoutView({ data }) {
  const totalPower = data.total_power_w ?? data.total_current_a != null
    ? (data.total_current_a * (data.vsupply ?? 0))
    : null

  const rows = [
    ['Branches', String(data.n_branches ?? data.n_parallel ?? '—')],
    ['LEDs total', String(data.total_leds ?? '—')],
    ['Total current', fmtMilliamps(data.total_current_a)],
    ['Total power', fmtWatts(data.total_power_w ?? totalPower)],
  ]

  const branchCurrents = data.branch_currents_a ?? []

  return (
    <div data-testid="etextiles-led-layout-view">
      <p className="text-xs text-ink-400 mb-1">
        LED fabric network — Kirchhoff KVL/KCL solution
      </p>
      <StatGrid rows={rows} />
      {branchCurrents.length > 0 && (
        <div className="mt-2" data-testid="etextiles-branch-currents">
          <p className="text-[10px] font-mono uppercase tracking-wider text-ink-500 mb-1">
            Branch currents
          </p>
          <div className="flex flex-wrap gap-1">
            {branchCurrents.map((i_a, idx) => (
              <span
                key={idx}
                className="rounded border border-ink-800 bg-ink-900/50 px-2 py-0.5 font-mono text-[11px] text-ink-300"
              >
                B{idx + 1}: {fmtMilliamps(i_a)}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * ETextilesPanel — renders e-textile heater or LED layout results.
 *
 * @param {Object} props
 * @param {Object|string|null} props.result  — textiles_etextiles output
 * @param {string} [props.className]
 */
export default function ETextilesPanel({ result = null, content, className = '' }) {
  // content prop (from panelRegistry) is a JSON string; parse and use as result
  const effectiveResult = useMemo(() => {
    if (content != null) {
      try { return JSON.parse(content) } catch { return result }
    }
    return result
  }, [result, content])
  const parsed = useMemo(() => parseETextilesResult(effectiveResult), [effectiveResult])

  if (parsed.kind === 'empty') {
    return (
      <div
        className={`flex flex-col items-center justify-center gap-2 py-10 text-ink-500 ${className}`}
        data-testid="etextiles-panel-empty"
      >
        <Zap size={28} className="opacity-40" />
        <p className="text-sm">No e-textile result yet.</p>
        <p className="text-xs opacity-60">
          Ask Kerf to design a conductive yarn heater or LED fabric layout.
        </p>
      </div>
    )
  }

  if (parsed.kind === 'invalid') {
    return (
      <div
        className={`rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400 ${className}`}
        data-testid="etextiles-panel-error"
      >
        Error: {parsed.error}
      </div>
    )
  }

  const modeLabel = parsed.mode === 'heater' ? 'Resistive heater'
    : parsed.mode === 'led_layout' ? 'LED fabric layout'
    : parsed.mode

  return (
    <div className={`flex flex-col gap-0 ${className}`} data-testid="etextiles-panel">
      {/* Header */}
      <div className="flex items-center gap-2 mb-2">
        <span className="grid place-items-center w-5 h-5 rounded bg-cyan-edge/10 border border-cyan-edge/20 text-cyan-edge">
          <CircuitBoard size={11} />
        </span>
        <span className="font-mono text-[11px] uppercase tracking-wider text-ink-400">
          e-textiles
        </span>
        <span
          className="ml-auto rounded-md border border-ink-700 bg-ink-900/60 px-2 py-0.5 font-mono text-[11px] text-ink-300"
          data-testid="etextiles-mode-label"
        >
          {modeLabel}
        </span>
      </div>

      {parsed.mode === 'heater'
        ? <HeaterView data={parsed.data} />
        : parsed.mode === 'led_layout'
        ? <LEDLayoutView data={parsed.data} />
        : (
          <p className="text-xs text-ink-400">
            Mode <code>{parsed.mode}</code> — raw data available.
          </p>
        )
      }
    </div>
  )
}
