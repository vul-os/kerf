/**
 * RiggingLoadPanel.jsx — Entertainment rigging load analysis panel.
 *
 * Features
 * ────────
 *   • Truss segments: visual span diagram with hoist markers + load bars
 *   • Hoist results table: reaction (N / kg), capacity, utilisation ratio,
 *     overload highlight
 *   • Bridle section: geometry summary + leg tension + overload status
 *
 * Props
 * ─────
 *   trusses         {Array}   TrussAnalysisResult list
 *   bridles         {Array}   BridleResult list
 *   any_overload    {boolean} True if any hoist or bridle exceeds capacity
 *   onDispatch      {function}
 *   className       {string}
 */

import { useState } from 'react'

const G = 9.81   // m/s²

// ── Colour helpers ────────────────────────────────────────────────────────────

function utilisationColour(ratio) {
  if (ratio === 0) return '#475569'
  if (ratio >= 1.0) return '#dc2626'
  if (ratio >= 0.8) return '#f59e0b'
  if (ratio >= 0.6) return '#facc15'
  return '#4ade80'
}

// ── Truss span diagram ────────────────────────────────────────────────────────

const DIAG_W = 560
const DIAG_H = 90
const TRUSS_Y = 50
const TRUSS_THICK = 12
const BEAM_COL = '#475569'
const HOIST_COL = '#7dd3fc'
const OVER_COL = '#f87171'

function TrussSpanDiagram({ truss }) {
  if (!truss) return null
  const span = truss.length_m || 1
  const px = x => 40 + (x / span) * (DIAG_W - 80)
  const hoists = truss.hoist_results || []
  const loads = truss.point_loads_debug || []   // optional debug data

  return (
    <svg width={DIAG_W} height={DIAG_H} style={{ display: 'block' }}>
      {/* Truss beam */}
      <rect
        x={40} y={TRUSS_Y - TRUSS_THICK / 2}
        width={DIAG_W - 80} height={TRUSS_THICK}
        fill={BEAM_COL} rx={2}
      />
      {/* End labels */}
      <text x={40} y={TRUSS_Y + 26} textAnchor="middle" fill="#64748b" fontSize={11}>0m</text>
      <text x={DIAG_W - 40} y={TRUSS_Y + 26} textAnchor="middle" fill="#64748b" fontSize={11}>
        {span}m
      </text>

      {/* Hoists */}
      {hoists.map((h, i) => {
        const xp = px(h.position_m)
        const col = h.overloaded ? OVER_COL : HOIST_COL
        return (
          <g key={i}>
            {/* Chain motor symbol: vertical line up */}
            <line x1={xp} y1={TRUSS_Y - TRUSS_THICK / 2} x2={xp} y2={10}
                  stroke={col} strokeWidth={2} />
            <circle cx={xp} cy={10} r={6} fill={col} />
            {/* Label below */}
            <text x={xp} y={TRUSS_Y + 26} textAnchor="middle" fill={col} fontSize={10}
                  fontWeight="bold">
              {h.label?.split(' ')[0] || `H${i + 1}`}
            </text>
            <text x={xp} y={TRUSS_Y + 38} textAnchor="middle" fill={col} fontSize={10}>
              {(h.reaction_N / G).toFixed(0)} kg
            </text>
          </g>
        )
      })}
    </svg>
  )
}

// ── Hoist results table ───────────────────────────────────────────────────────

function HoistTable({ hoists }) {
  if (!hoists?.length) return null
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
      <thead>
        <tr style={{ background: '#1e293b', color: '#94a3b8', textAlign: 'left' }}>
          {['Hoist', 'Position', 'Reaction (N)', 'Reaction (kg)', 'Capacity (N)', 'Util', 'Status'].map(h => (
            <th key={h} style={{ padding: '6px 10px', fontWeight: 600 }}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {hoists.map((h, i) => {
          const col = utilisationColour(h.utilisation_ratio)
          const over = h.overloaded
          return (
            <tr key={i} style={{
              background: over ? '#3f0000' : (i % 2 === 0 ? '#0f172a' : '#1a2234'),
              color: '#cbd5e1',
            }}>
              <td style={{ padding: '5px 10px', fontWeight: 700, color: over ? '#f87171' : '#7dd3fc' }}>
                {h.label}
              </td>
              <td style={{ padding: '5px 10px', fontFamily: 'monospace' }}>{h.position_m} m</td>
              <td style={{ padding: '5px 10px', fontFamily: 'monospace', fontWeight: 600 }}>
                {h.reaction_N?.toFixed(1)}
              </td>
              <td style={{ padding: '5px 10px', fontFamily: 'monospace' }}>
                {(h.reaction_N / G).toFixed(1)}
              </td>
              <td style={{ padding: '5px 10px', fontFamily: 'monospace' }}>
                {h.hoist_capacity_N > 0 ? h.hoist_capacity_N : '—'}
              </td>
              <td style={{ padding: '5px 10px' }}>
                {h.hoist_capacity_N > 0 ? (
                  <span style={{ color: col, fontWeight: 700 }}>
                    {(h.utilisation_ratio * 100).toFixed(0)}%
                    <UtilBar ratio={h.utilisation_ratio} />
                  </span>
                ) : '—'}
              </td>
              <td style={{ padding: '5px 10px' }}>
                {over ? (
                  <span style={{ color: '#f87171', fontWeight: 700 }}>
                    OVERLOAD {Math.abs(h.overload_margin_N).toFixed(0)} N over
                  </span>
                ) : h.hoist_capacity_N > 0 ? (
                  <span style={{ color: '#4ade80' }}>
                    OK ({h.overload_margin_N?.toFixed(0)} N headroom)
                  </span>
                ) : (
                  <span style={{ color: '#475569' }}>No capacity set</span>
                )}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function UtilBar({ ratio }) {
  const clamped = Math.min(ratio, 1.0)
  return (
    <span style={{
      display: 'inline-block', width: 48, height: 6, background: '#1e293b',
      borderRadius: 3, marginLeft: 6, verticalAlign: 'middle', overflow: 'hidden',
    }}>
      <span style={{
        display: 'block', width: `${clamped * 100}%`, height: '100%',
        background: utilisationColour(ratio), borderRadius: 3,
      }} />
    </span>
  )
}

// ── Bridle section ────────────────────────────────────────────────────────────

function BridleCard({ br }) {
  const over = br.overloaded
  return (
    <div style={{
      background: over ? '#3f0000' : '#0f172a',
      border: `1px solid ${over ? '#dc2626' : '#1e293b'}`,
      borderRadius: 8, padding: '12px 16px', marginBottom: 8,
    }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontWeight: 700, color: over ? '#f87171' : '#7dd3fc', fontSize: 14 }}>
          {br.label}
        </span>
        {over && (
          <span style={{ background: '#dc2626', color: '#fff', borderRadius: 4, padding: '1px 8px', fontSize: 12 }}>
            OVERLOAD
          </span>
        )}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, fontSize: 13 }}>
        <BridleStat label="Load" value={`${br.load_N?.toFixed(0)} N (${(br.load_N / G).toFixed(1)} kg)`} />
        <BridleStat label="Half-angle" value={`${br.half_angle_deg?.toFixed(1)}°`}
          warn={br.half_angle_deg > 60} />
        <BridleStat label="Leg tension" value={`${br.leg_tension_N?.toFixed(0)} N`}
          highlight={over} />
        <BridleStat label="Leg length" value={`${br.leg_length_m?.toFixed(2)} m`} />
        <BridleStat label="Spread" value={`${br.horizontal_spread_m} m`} />
        <BridleStat label="Height" value={`${br.vertical_height_m} m`} />
        {br.leg_capacity_N > 0 && (
          <BridleStat label="Leg WLL" value={`${br.leg_capacity_N} N`} />
        )}
        {br.leg_capacity_N > 0 && (
          <BridleStat
            label="Margin"
            value={`${br.overload_margin_N?.toFixed(0)} N`}
            highlight={over}
          />
        )}
      </div>
      {br.warnings?.length > 0 && (
        <div style={{ marginTop: 8 }}>
          {br.warnings.map((w, i) => (
            <div key={i} style={{
              color: '#fbbf24', fontSize: 12, background: '#422006',
              borderRadius: 4, padding: '4px 8px', marginTop: 4,
            }}>
              {w}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function BridleStat({ label, value, highlight, warn }) {
  return (
    <div>
      <div style={{ color: '#64748b', fontSize: 11, marginBottom: 2 }}>{label}</div>
      <div style={{
        color: highlight ? '#f87171' : warn ? '#fbbf24' : '#e2e8f0',
        fontWeight: highlight || warn ? 700 : 400,
        fontFamily: 'monospace',
      }}>
        {value}
      </div>
    </div>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

export default function RiggingLoadPanel({
  trusses = [],
  bridles = [],
  any_overload = false,
  onDispatch,
  className = '',
}) {
  const [selectedTruss, setSelectedTruss] = useState(0)

  const truss = trusses[selectedTruss]

  return (
    <div
      className={className}
      style={{
        background: '#020817', color: '#e2e8f0',
        borderRadius: 10, padding: 16,
        fontFamily: '"Inter", "SF Pro Display", system-ui, sans-serif',
        minWidth: 640,
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: '#f1f5f9' }}>
          Rigging Load Analysis
        </span>
        {any_overload && (
          <span style={{
            background: '#dc2626', color: '#fff', borderRadius: 6,
            padding: '2px 10px', fontWeight: 700, fontSize: 12,
          }}>
            OVERLOAD DETECTED
          </span>
        )}
        {!any_overload && trusses.length > 0 && (
          <span style={{ color: '#4ade80', fontSize: 13 }}>All within capacity</span>
        )}
      </div>

      {/* Truss selector */}
      {trusses.length > 1 && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
          {trusses.map((t, i) => (
            <button
              key={i}
              onClick={() => setSelectedTruss(i)}
              style={{
                padding: '4px 12px', borderRadius: 6, border: '1px solid #334155',
                background: selectedTruss === i ? '#1e293b' : 'transparent',
                color: t.overloaded_hoists?.length ? '#f87171' : '#94a3b8',
                cursor: 'pointer', fontSize: 13,
              }}
            >
              {t.label}
              {t.overloaded_hoists?.length > 0 && ' ⚠'}
            </button>
          ))}
        </div>
      )}

      {/* Truss panel */}
      {truss && (
        <div style={{
          background: '#0f172a', borderRadius: 8, padding: 14, marginBottom: 14,
        }}>
          {/* Truss metadata */}
          <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', fontSize: 13, marginBottom: 12 }}>
            <Stat label="Truss" value={truss.label} />
            <Stat label="Length" value={`${truss.length_m} m`} />
            <Stat label="Type" value={truss.truss_type || 'Custom'} />
            <Stat label="Self-weight" value={`${truss.self_weight_N_per_m} N/m (${(truss.self_weight_N_per_m / G).toFixed(1)} kg/m)`} />
            <Stat label="Total load" value={`${truss.total_load_N?.toFixed(0)} N (${(truss.total_load_N / G).toFixed(1)} kg)`} />
          </div>

          {/* Span diagram */}
          <TrussSpanDiagram truss={truss} />

          {/* Hoist table */}
          <div style={{ marginTop: 10, overflowX: 'auto' }}>
            <HoistTable hoists={truss.hoist_results} />
          </div>

          {/* Equilibrium check */}
          <div style={{ marginTop: 10, fontSize: 12, color: truss.equilibrium_check ? '#4ade80' : '#f87171' }}>
            Equilibrium: {truss.equilibrium_check
              ? `✓ balanced (error ${truss.equilibrium_error_N?.toFixed(3)} N)`
              : `✗ error ${truss.equilibrium_error_N?.toFixed(3)} N`}
          </div>

          {/* Warnings */}
          {truss.warnings?.map((w, i) => (
            <div key={i} style={{
              color: '#fbbf24', fontSize: 12, background: '#422006',
              borderRadius: 4, padding: '4px 8px', marginTop: 4,
            }}>
              {w}
            </div>
          ))}
        </div>
      )}

      {/* Bridle section */}
      {bridles.length > 0 && (
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#94a3b8', marginBottom: 10 }}>
            Bridle Analysis
          </div>
          {bridles.map((br, i) => <BridleCard key={i} br={br} />)}
        </div>
      )}

      {trusses.length === 0 && bridles.length === 0 && (
        <div style={{ color: '#475569', fontSize: 13, padding: '20px 0', textAlign: 'center' }}>
          No rigging data. Use the rigging_load_analysis tool to compute hoist reactions.
        </div>
      )}
    </div>
  )
}

function Stat({ label, value }) {
  return (
    <div>
      <span style={{ color: '#64748b', marginRight: 4 }}>{label}:</span>
      <span style={{ color: '#e2e8f0', fontWeight: 600 }}>{value}</span>
    </div>
  )
}
