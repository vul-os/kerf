/**
 * LightingPlotPanel.jsx — Theatrical lighting plot + DMX patch panel.
 *
 * Features
 * ────────
 *   • Fixture list: type, position, channel, dimmer, wattage, colour, focus
 *   • DMX patch grid: per-universe address map with conflict highlighting
 *   • Circuit / dimmer schedule with per-circuit load and overload warning
 *   • Summary bar: fixture count, total load (W / A), universe count
 *
 * Props
 * ─────
 *   fixtures        {Array}   FixtureInstance list from lighting_plot_patch tool
 *   dmx_conflicts   {Array}   DMX conflict objects {universe, address_range, fixture_a, fixture_b, message}
 *   circuit_schedule {Array}  Circuit rows {dimmer, fixtures, total_wattage_W, channels, overloaded, overload_margin_W}
 *   total_wattage_W  {number}
 *   total_amperage_A {number}
 *   supply_voltage_V {number}
 *   universes_used   {Array<number>}
 *   patch_sheet      {Array}  PatchRow list
 *   magic_sheet      {Array}  MagicSheetEntry list
 *   onDispatch       {function} Called with {tool, params} when user triggers a check.
 *   className        {string}
 */

import { useMemo, useState } from 'react'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''

// ── Colour map for gels / filters ─────────────────────────────────────────

const GEL_COLOURS = {
  'R02':  '#ffd580',
  'R04':  '#ffb347',
  'R21':  '#ff8c69',
  'R27':  '#ff6b6b',
  'R32':  '#ff4040',
  'R80':  '#6699ff',
  'R81':  '#4488ff',
  'R83':  '#88aaff',
  'L201': '#ffd700',
  'L202': '#ffaa00',
  'L203': '#ff8800',
  'L119': '#cc44ff',
  'L120': '#aa33ff',
  'L161': '#44ccff',
  'L201': '#ffd700',
}

function gelColor(color) {
  if (!color || color === 'no color' || color === 'open') return '#f1f5f9'
  return GEL_COLOURS[color?.toUpperCase?.()] || '#e2e8f0'
}

// ── Sub-components ───────────────────────────────────────────────────────────

function SummaryBar({ totalFixtures, totalWattage, totalAmperage, voltage, universes, conflicts }) {
  const hasConflicts = conflicts?.length > 0
  return (
    <div style={{
      display: 'flex', gap: 20, flexWrap: 'wrap', alignItems: 'center',
      background: '#0f172a', borderRadius: 8, padding: '10px 16px',
      fontSize: 13, color: '#94a3b8',
    }}>
      <Stat label="Fixtures" value={totalFixtures} />
      <Stat label="Total load" value={`${totalWattage?.toFixed(0)} W`} />
      <Stat label="Amperage" value={`${totalAmperage?.toFixed(1)} A @ ${voltage}V`} />
      <Stat label="Universes" value={universes?.join(', ') || '—'} />
      {hasConflicts && (
        <span style={{
          background: '#dc2626', color: '#fff', borderRadius: 6,
          padding: '2px 10px', fontWeight: 700, fontSize: 12,
        }}>
          {conflicts.length} DMX CONFLICT{conflicts.length > 1 ? 'S' : ''}
        </span>
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

// ── Fixture list table ────────────────────────────────────────────────────────

function FixtureTable({ rows }) {
  if (!rows?.length) return <Empty text="No fixtures patched" />
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ background: '#1e293b', color: '#94a3b8', textAlign: 'left' }}>
            {['Ch', 'Dim', 'ID', 'Type', 'Position', 'Uni', 'Addr', 'Wattage', 'Colour', 'Focus'].map(h => (
              <th key={h} style={{ padding: '6px 10px', fontWeight: 600 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={row.fixture_ids?.[0] || i} style={{
              background: i % 2 === 0 ? '#0f172a' : '#1a2234',
              color: '#cbd5e1',
            }}>
              <td style={tdStyle}>{row.channel || '—'}</td>
              <td style={tdStyle}>{row.dimmer || '—'}</td>
              <td style={{ ...tdStyle, fontFamily: 'monospace', color: '#7dd3fc' }}>
                {row.fixture_ids?.join(', ')}
              </td>
              <td style={tdStyle}>{row.fixture_type}</td>
              <td style={tdStyle}>{row.position} #{row.unit_number}</td>
              <td style={tdStyle}>{row.dmx_universe}</td>
              <td style={{ ...tdStyle, fontFamily: 'monospace' }}>
                {row.dmx_address}
                {row.dmx_end_address > row.dmx_address ? `–${row.dmx_end_address}` : ''}
              </td>
              <td style={tdStyle}>{row.wattage_W}W</td>
              <td style={tdStyle}>
                <span style={{
                  display: 'inline-flex', alignItems: 'center', gap: 5,
                }}>
                  <span style={{
                    width: 12, height: 12, borderRadius: 2,
                    background: gelColor(row.color), border: '1px solid #334155',
                    display: 'inline-block',
                  }} />
                  {row.color}
                </span>
              </td>
              <td style={{ ...tdStyle, color: '#94a3b8' }}>{row.focus_note || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const tdStyle = { padding: '5px 10px', verticalAlign: 'middle' }

// ── DMX conflict panel ────────────────────────────────────────────────────────

function ConflictPanel({ conflicts }) {
  if (!conflicts?.length) return (
    <div style={{ color: '#4ade80', fontSize: 13, padding: '8px 0' }}>
      No DMX conflicts detected.
    </div>
  )
  return (
    <div>
      {conflicts.map((c, i) => (
        <div key={i} style={{
          background: '#3f0000', border: '1px solid #dc2626',
          borderRadius: 6, padding: '8px 12px', marginBottom: 6, fontSize: 13,
        }}>
          <span style={{ color: '#f87171', fontWeight: 700 }}>
            Conflict Universe {c.universe} — addresses {c.address_range?.[0]}–{c.address_range?.[1]}
          </span>
          <br />
          <span style={{ color: '#fca5a5' }}>{c.message}</span>
        </div>
      ))}
    </div>
  )
}

// ── Circuit / dimmer schedule ─────────────────────────────────────────────────

function CircuitTable({ rows }) {
  if (!rows?.length) return <Empty text="No circuits defined" />
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ background: '#1e293b', color: '#94a3b8', textAlign: 'left' }}>
            {['Dimmer', 'Channels', 'Fixtures', 'Wattage', 'Amperage', 'Status'].map(h => (
              <th key={h} style={{ padding: '6px 10px', fontWeight: 600 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const over = row.overloaded
            return (
              <tr key={row.dimmer} style={{
                background: over ? '#3f0000' : (i % 2 === 0 ? '#0f172a' : '#1a2234'),
                color: '#cbd5e1',
              }}>
                <td style={{ ...tdStyle, fontFamily: 'monospace', fontWeight: 700 }}>
                  D{row.dimmer}
                </td>
                <td style={tdStyle}>{row.channels?.join(', ') || '—'}</td>
                <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: 12 }}>
                  {row.fixtures?.join(', ')}
                </td>
                <td style={tdStyle}>{row.total_wattage_W?.toFixed(0)} W</td>
                <td style={tdStyle}>{row.total_amperage_A?.toFixed(1)} A</td>
                <td style={tdStyle}>
                  {over ? (
                    <span style={{ color: '#f87171', fontWeight: 700 }}>
                      OVERLOAD {Math.abs(row.overload_margin_W).toFixed(0)} W over
                    </span>
                  ) : (
                    <span style={{ color: '#4ade80' }}>
                      OK ({row.overload_margin_W?.toFixed(0)} W headroom)
                    </span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ── Shared helpers ────────────────────────────────────────────────────────────

function Empty({ text }) {
  return <div style={{ color: '#475569', fontSize: 13, padding: '12px 0' }}>{text}</div>
}

function Tab({ label, active, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: '6px 14px', borderRadius: '6px 6px 0 0', border: 'none', cursor: 'pointer',
        background: active ? '#1e293b' : 'transparent',
        color: active ? '#e2e8f0' : '#64748b',
        fontWeight: active ? 700 : 400,
        fontSize: 13, transition: 'all 0.15s',
      }}
    >
      {label}
    </button>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

export default function LightingPlotPanel({
  fixtures = [],
  dmx_conflicts = [],
  circuit_schedule = [],
  total_wattage_W = 0,
  total_amperage_A = 0,
  supply_voltage_V = 120,
  universes_used = [],
  patch_sheet = [],
  magic_sheet = [],
  onDispatch,
  className = '',
}) {
  const [tab, setTab] = useState('patch')
  const [checking, setChecking] = useState(false)

  const TABS = [
    { key: 'patch',    label: 'Patch Sheet' },
    { key: 'circuits', label: 'Circuit Schedule' },
    { key: 'conflicts',label: `DMX Conflicts${dmx_conflicts.length ? ` (${dmx_conflicts.length})` : ''}` },
  ]

  async function handleCheck() {
    if (!onDispatch) return
    setChecking(true)
    try {
      await onDispatch({
        tool: 'lighting_dmx_check',
        params: { fixtures: patch_sheet.map(r => ({
          fixture_id: r.fixture_ids?.[0],
          dmx_universe: r.dmx_universe,
          dmx_address: r.dmx_address,
          dmx_footprint: r.dmx_end_address - r.dmx_address + 1,
        })) },
      })
    } finally {
      setChecking(false)
    }
  }

  return (
    <div
      className={className}
      style={{
        background: '#020817', color: '#e2e8f0',
        borderRadius: 10, padding: 16,
        fontFamily: '"Inter", "SF Pro Display", system-ui, sans-serif',
        minWidth: 600,
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: '#f1f5f9' }}>
          Lighting Plot
        </span>
        <span style={{ color: '#475569', fontSize: 13 }}>
          {fixtures.length || patch_sheet.length} fixtures
        </span>
        <div style={{ flex: 1 }} />
        <button
          onClick={handleCheck}
          disabled={checking}
          style={{
            padding: '4px 14px', borderRadius: 6, border: '1px solid #334155',
            background: checking ? '#1e293b' : '#0f172a',
            color: '#7dd3fc', cursor: checking ? 'default' : 'pointer', fontSize: 13,
          }}
        >
          {checking ? 'Checking…' : 'Check DMX'}
        </button>
      </div>

      {/* Summary bar */}
      <SummaryBar
        totalFixtures={fixtures.length || patch_sheet.length}
        totalWattage={total_wattage_W}
        totalAmperage={total_amperage_A}
        voltage={supply_voltage_V}
        universes={universes_used}
        conflicts={dmx_conflicts}
      />

      {/* Tabs */}
      <div style={{ borderBottom: '1px solid #1e293b', marginTop: 16, marginBottom: 0 }}>
        {TABS.map(t => (
          <Tab key={t.key} label={t.label} active={tab === t.key} onClick={() => setTab(t.key)} />
        ))}
      </div>

      {/* Tab content */}
      <div style={{ background: '#0f172a', borderRadius: '0 6px 6px 6px', padding: 12 }}>
        {tab === 'patch'    && <FixtureTable rows={patch_sheet} />}
        {tab === 'circuits' && <CircuitTable rows={circuit_schedule} />}
        {tab === 'conflicts' && <ConflictPanel conflicts={dmx_conflicts} />}
      </div>
    </div>
  )
}
