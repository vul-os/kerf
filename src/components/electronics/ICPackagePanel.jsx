// ICPackagePanel.jsx — IC package / substrate design panel.
//
// Provides: substrate/BGA viewer (die + balls + bond wires/bumps + DRC list)
// and a creation form for wire-bond, flip-chip, and BGA-only packages.
//
// Backend contracts:
//   POST /api/llm-tools/ic_package_create  {name, package_type, die, substrate, bonds, ball_grid, net_map}
//   POST /api/llm-tools/ic_package_drc     {ic_package}
//
// References: IPC-7094A §3 (wire-bond), JEDEC JEP95 §4 (BGA), IPC-SM-785 §6 (flip-chip).
//
// Props:
//   onClose — () => void

import { useCallback, useState } from 'react'
import { Cpu, AlertTriangle, CheckCircle2, X, RefreshCw, Grid, Layers } from 'lucide-react'

// ── Demo package ──────────────────────────────────────────────────────────────

const DEMO_PACKAGE = {
  name: 'BGA256_14x14',
  package_type: 'wire_bond',
  die: {
    width_mm: 5.0,
    height_mm: 5.0,
    pad_pitch_um: 80.0,
    pads: [
      { id: 'P1', side: 'top', x_mm: 0.5, y_mm: 2.5 },
      { id: 'P2', side: 'top', x_mm: 1.0, y_mm: 2.5 },
      { id: 'P3', side: 'top', x_mm: 1.5, y_mm: 2.5 },
      { id: 'P4', side: 'top', x_mm: 4.5, y_mm: 2.5 },
      { id: 'P5', side: 'top', x_mm: 2.5, y_mm: 0.5 },
      { id: 'P6', side: 'top', x_mm: 2.5, y_mm: 4.5 },
    ],
  },
  substrate: { width_mm: 14.0, height_mm: 14.0, layers: 4, material: 'BT resin' },
  bonds: [
    { type: 'wire_bond', die_pad: 'P1', finger_id: 'F1', length_mm: 1.8, angle_deg: 5.0, wire_diameter_um: 25.0 },
    { type: 'wire_bond', die_pad: 'P2', finger_id: 'F2', length_mm: 1.5, angle_deg: -8.0, wire_diameter_um: 25.0 },
    { type: 'wire_bond', die_pad: 'P3', finger_id: 'F3', length_mm: 2.0, angle_deg: 12.0, wire_diameter_um: 25.0 },
    { type: 'wire_bond', die_pad: 'P4', finger_id: 'F4', length_mm: 1.6, angle_deg: -5.0, wire_diameter_um: 25.0 },
    { type: 'wire_bond', die_pad: 'P5', finger_id: 'F5', length_mm: 1.4, angle_deg: 0.0, wire_diameter_um: 25.0 },
    { type: 'wire_bond', die_pad: 'P6', finger_id: 'F6', length_mm: 1.9, angle_deg: 3.0, wire_diameter_um: 25.0 },
  ],
  ball_grid: {
    rows: 16, cols: 16, pitch_mm: 0.8, ball_diameter_mm: 0.45,
    balls: [
      { id: 'A1', row: 0, col: 0, net: 'GND' },
      { id: 'A2', row: 0, col: 1, net: 'VCC' },
      { id: 'B1', row: 1, col: 0, net: 'P1_net' },
      { id: 'B2', row: 1, col: 1, net: 'P2_net' },
      { id: 'C1', row: 2, col: 0, net: 'P3_net' },
      { id: 'C2', row: 2, col: 1, net: 'P4_net' },
      { id: 'D1', row: 3, col: 0, net: 'P5_net' },
      { id: 'D2', row: 3, col: 1, net: 'P6_net' },
    ],
  },
  net_map: { P1: 'B1', P2: 'B2', P3: 'C1', P4: 'C2', P5: 'D1', P6: 'D2' },
}

// ── Helpers ───────────────────────────────────────────────────────────────────

async function apiPost(endpoint, body) {
  try {
    const r = await fetch(`/api/llm-tools/${endpoint}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    })
    return r.ok ? r.json() : { error: `HTTP ${r.status}` }
  } catch (e) {
    return { error: e.message }
  }
}

// ── BGA Canvas Viewer ─────────────────────────────────────────────────────────

function BGAViewer({ pkg }) {
  if (!pkg) return null

  const bg   = pkg.ball_grid
  const die  = pkg.die
  const sub  = pkg.substrate

  const CANVAS_W = 340
  const CANVAS_H = 320
  const MARGIN   = 20

  // Scale: fit substrate into canvas
  const scaleX = (CANVAS_W - 2 * MARGIN) / (sub?.width_mm  ?? 14)
  const scaleY = (CANVAS_H - 2 * MARGIN) / (sub?.height_mm ?? 14)
  const scale  = Math.min(scaleX, scaleY)

  const sx = (mm) => MARGIN + mm * scale
  const sy = (mm) => MARGIN + mm * scale

  // Substrate rect
  const subW = (sub?.width_mm  ?? 14) * scale
  const subH = (sub?.height_mm ?? 14) * scale

  // Die rect (centered in substrate)
  const dieW = (die?.width_mm  ?? 5) * scale
  const dieH = (die?.height_mm ?? 5) * scale
  const dieX = MARGIN + ((sub?.width_mm  ?? 14) - (die?.width_mm  ?? 5)) / 2 * scale
  const dieY = MARGIN + ((sub?.height_mm ?? 14) - (die?.height_mm ?? 5)) / 2 * scale

  // BGA balls
  const balls = bg?.balls ?? []
  const pitch = (bg?.pitch_mm ?? 0.8) * scale
  const ballR = Math.min(pitch * 0.35, 6)

  // Bond wires: map from finger_id → die_pad x/y (approximate from die centre)
  const diePads = {}
  for (const p of die?.pads ?? []) {
    diePads[p.id] = {
      x: dieX + p.x_mm * scale,
      y: dieY + p.y_mm * scale,
    }
  }

  return (
    <svg width={CANVAS_W} height={CANVAS_H} className="bg-gray-900 rounded border border-white/10">
      {/* Substrate outline */}
      <rect x={MARGIN} y={MARGIN} width={subW} height={subH}
            fill="#1a2233" stroke="#3b82f6" strokeWidth={1.5} />
      <text x={MARGIN + 4} y={MARGIN + 11} fill="#60a5fa" fontSize={9}>
        Substrate {sub?.width_mm}×{sub?.height_mm} mm ({sub?.layers ?? 2}L {sub?.material ?? ''})
      </text>

      {/* BGA balls */}
      {balls.map((ball, i) => {
        const bx = MARGIN + 10 + ball.col * pitch
        const by = MARGIN + 10 + ball.row * pitch
        const isGnd = ball.net === 'GND'
        const isVcc = ball.net === 'VCC'
        return (
          <g key={i}>
            <circle cx={bx} cy={by} r={ballR}
                    fill={isGnd ? '#1e3a5f' : isVcc ? '#3b1e5f' : '#1e4a2a'}
                    stroke={isGnd ? '#60a5fa' : isVcc ? '#a855f7' : '#4ade80'}
                    strokeWidth={0.8} />
            <title>{ball.id} — {ball.net}</title>
          </g>
        )
      })}

      {/* Die outline */}
      <rect x={dieX} y={dieY} width={dieW} height={dieH}
            fill="#2d1e0f" stroke="#f59e0b" strokeWidth={1.5} />
      <text x={dieX + 3} y={dieY + 10} fill="#f59e0b" fontSize={8}>
        Die {die?.width_mm}×{die?.height_mm} mm
      </text>

      {/* Die pads */}
      {(die?.pads ?? []).map((p, i) => {
        const px = dieX + p.x_mm * scale
        const py = dieY + p.y_mm * scale
        return (
          <circle key={i} cx={px} cy={py} r={3}
                  fill="#f59e0b" stroke="#92400e" strokeWidth={0.5}>
            <title>{p.id}</title>
          </circle>
        )
      })}

      {/* Bond wires (schematic lines from die pad toward edge) */}
      {(pkg.bonds ?? []).filter(b => b.type === 'wire_bond').map((bond, i) => {
        const src = diePads[bond.die_pad]
        if (!src) return null
        // Draw wire toward nearest substrate edge at the given angle
        const angleRad = ((bond.angle_deg ?? 0) + (src.x > dieX + dieW / 2 ? 0 : 180)) * Math.PI / 180
        const wLen = (bond.length_mm ?? 1.5) * scale
        const ex = src.x + Math.cos(angleRad) * wLen
        const ey = src.y + Math.sin(angleRad) * wLen
        return (
          <line key={i} x1={src.x} y1={src.y} x2={ex} y2={ey}
                stroke="#fbbf24" strokeWidth={0.7} strokeOpacity={0.7}>
            <title>Wire {bond.die_pad}→{bond.finger_id} {bond.length_mm}mm</title>
          </line>
        )
      })}

      {/* Legend */}
      <g transform={`translate(${MARGIN}, ${CANVAS_H - 18})`}>
        <circle cx={5} cy={4} r={3} fill="#1e3a5f" stroke="#60a5fa" strokeWidth={0.8} />
        <text x={11} y={8} fill="#9ca3af" fontSize={8}>GND</text>
        <circle cx={40} cy={4} r={3} fill="#3b1e5f" stroke="#a855f7" strokeWidth={0.8} />
        <text x={46} y={8} fill="#9ca3af" fontSize={8}>VCC</text>
        <circle cx={75} cy={4} r={3} fill="#1e4a2a" stroke="#4ade80" strokeWidth={0.8} />
        <text x={81} y={8} fill="#9ca3af" fontSize={8}>Signal</text>
        <rect x={115} y={1} width={12} height={5} fill="#2d1e0f" stroke="#f59e0b" strokeWidth={0.8} />
        <text x={130} y={8} fill="#9ca3af" fontSize={8}>Die</text>
        <rect x={155} y={1} width={12} height={5} fill="#1a2233" stroke="#3b82f6" strokeWidth={0.8} />
        <text x={170} y={8} fill="#9ca3af" fontSize={8}>Substrate</text>
      </g>
    </svg>
  )
}

// ── Violation row ─────────────────────────────────────────────────────────────

function ViolRow({ v }) {
  return (
    <div className="flex items-start gap-2 px-2 py-1 text-[11px]">
      <AlertTriangle size={11} className="text-red-400 mt-0.5 shrink-0" />
      <div className="min-w-0">
        <span className="text-gray-300">{v.rule}</span>
        <div className="text-gray-500 leading-tight mt-0.5">{v.message}</div>
      </div>
    </div>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

export default function ICPackagePanel({ onClose }) {
  const [tab,       setTab]       = useState('viewer')
  const [loading,   setLoading]   = useState(false)
  const [pkg,       setPkg]       = useState(DEMO_PACKAGE)
  const [drcResult, setDrcResult] = useState(null)
  // Creation form state
  const [formName, setFormName]           = useState('MyBGA')
  const [formType, setFormType]           = useState('wire_bond')
  const [createError, setCreateError]     = useState(null)
  const [createResult, setCreateResult]   = useState(null)

  const runDrc = useCallback(async () => {
    setLoading(true)
    setDrcResult(null)
    const r = await apiPost('ic_package_drc', { ic_package: pkg })
    setLoading(false)
    if (r.error) setDrcResult({ error: r.error })
    else setDrcResult(r)
  }, [pkg])

  const createPkg = useCallback(async () => {
    setLoading(true)
    setCreateError(null)
    setCreateResult(null)
    const r = await apiPost('ic_package_create', {
      name: formName,
      package_type: formType,
      die: { width_mm: 4.0, height_mm: 4.0, pad_pitch_um: 100, pads: [] },
      substrate: { width_mm: 10.0, height_mm: 10.0, layers: 4, material: 'BT resin' },
      ball_grid: { rows: 8, cols: 8, pitch_mm: 1.0, balls: [] },
      net_map: {},
    })
    setLoading(false)
    if (r.error) setCreateError(r.error)
    else {
      setCreateResult(r.ic_package)
      setPkg(r.ic_package)
      setTab('viewer')
    }
  }, [formName, formType])

  const netMapEntries = Object.entries(pkg.net_map ?? {})

  return (
    <div className="flex flex-col h-full bg-gray-950 text-gray-200 text-[12px]">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-white/10 shrink-0">
        <Cpu size={14} className="text-amber-400" />
        <span className="font-medium text-gray-100">IC Package / Substrate Designer</span>
        <span className="ml-2 text-[10px] text-gray-500 font-mono">{pkg.name}</span>
        <span className={`ml-1 text-[10px] px-1.5 py-0.5 rounded font-mono
          ${pkg.package_type === 'flip_chip' ? 'bg-purple-900/40 text-purple-300'
            : pkg.package_type === 'wire_bond' ? 'bg-amber-900/40 text-amber-300'
            : 'bg-blue-900/40 text-blue-300'}`}>
          {pkg.package_type}
        </span>
        <div className="ml-auto flex gap-1">
          {onClose && (
            <button onClick={onClose}
                    className="p-1 rounded hover:bg-white/10 text-gray-500 hover:text-gray-300">
              <X size={13} />
            </button>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-0.5 px-2 pt-1.5 border-b border-white/10 shrink-0">
        {[['viewer', 'Viewer'], ['drc', 'DRC'], ['netmap', 'Net Map'], ['create', 'Create']].map(([id, label]) => (
          <button key={id} onClick={() => setTab(id)}
                  className={`px-2.5 py-1 text-[11px] rounded-t transition-colors
                    ${tab === id
                      ? 'bg-amber-900/30 text-amber-300 border-b-2 border-amber-400'
                      : 'text-gray-500 hover:text-gray-300'}`}>
            {label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-auto p-3 space-y-3">

        {/* ── Viewer tab ──────────────────────────────────────────────────── */}
        {tab === 'viewer' && (
          <div className="space-y-3">
            {/* Package stats */}
            <div className="grid grid-cols-3 gap-2">
              {[
                ['Die', `${pkg.die?.width_mm}×${pkg.die?.height_mm} mm`],
                ['Substrate', `${pkg.substrate?.width_mm}×${pkg.substrate?.height_mm} mm ${pkg.substrate?.layers}L`],
                ['Ball Grid', `${pkg.ball_grid?.rows}×${pkg.ball_grid?.cols} @ ${pkg.ball_grid?.pitch_mm}mm`],
                ['Bonds', `${(pkg.bonds ?? []).length} ${pkg.package_type === 'flip_chip' ? 'bumps' : 'wires'}`],
                ['Mapped Nets', `${Object.keys(pkg.net_map ?? {}).length} pads`],
                ['Material', pkg.substrate?.material ?? '—'],
              ].map(([label, val]) => (
                <div key={label} className="bg-white/5 rounded p-2">
                  <div className="text-[10px] text-gray-500">{label}</div>
                  <div className="text-gray-200 font-mono mt-0.5 truncate">{val}</div>
                </div>
              ))}
            </div>

            {/* SVG Viewer */}
            <div className="flex justify-center">
              <BGAViewer pkg={pkg} />
            </div>

            {/* Bond wire list */}
            {(pkg.bonds ?? []).length > 0 && (
              <div className="bg-white/5 rounded p-2 space-y-0.5">
                <div className="text-[10px] text-gray-500 mb-1">Bonds / Bumps</div>
                {pkg.bonds.map((b, i) => (
                  <div key={i} className="flex gap-3 text-[11px] text-gray-400">
                    <span className="font-mono text-gray-500 w-8">{b.die_pad}</span>
                    <span className="text-gray-500">→</span>
                    <span className="font-mono">{b.finger_id ?? b.ball_id ?? '—'}</span>
                    {b.length_mm != null && (
                      <span className="text-gray-600">{b.length_mm}mm ∠{b.angle_deg}°</span>
                    )}
                    {b.pitch_um != null && (
                      <span className="text-gray-600">pitch {b.pitch_um}µm</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── DRC tab ─────────────────────────────────────────────────────── */}
        {tab === 'drc' && (
          <div className="space-y-3">
            <div className="text-[11px] text-gray-500">
              Checks: wire length (IPC-7094A §3.2.3), wire angle (§3.2.5),
              bump pitch (IPC-SM-785 §6.2), ball pitch (JEDEC JEP95 Table 1),
              net-map integrity.
            </div>
            <button
              onClick={runDrc}
              disabled={loading}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-700/30 hover:bg-amber-700/50
                         border border-amber-600/40 rounded text-amber-300 text-[11px] transition-colors disabled:opacity-50">
              {loading ? <RefreshCw size={11} className="animate-spin" /> : <Layers size={11} />}
              Run DRC
            </button>

            {drcResult?.error && (
              <div className="text-red-400 text-[11px]">Error: {drcResult.error}</div>
            )}

            {drcResult && !drcResult.error && (
              <div className="space-y-2">
                <div className={`flex items-center gap-2 text-[12px] font-medium
                  ${drcResult.pass ? 'text-green-400' : 'text-red-400'}`}>
                  {drcResult.pass
                    ? <><CheckCircle2 size={14} /> DRC Passed</>
                    : <><AlertTriangle size={14} /> DRC Failed — {drcResult.error_count} error{drcResult.error_count !== 1 ? 's' : ''}</>}
                </div>
                {(drcResult.violations ?? []).length > 0 && (
                  <div className="bg-white/5 rounded divide-y divide-white/5">
                    {drcResult.violations.map((v, i) => <ViolRow key={i} v={v} />)}
                  </div>
                )}
                {drcResult.pass && (
                  <div className="text-gray-500 text-[11px]">No violations found.</div>
                )}
              </div>
            )}
          </div>
        )}

        {/* ── Net Map tab ──────────────────────────────────────────────────── */}
        {tab === 'netmap' && (
          <div className="space-y-2">
            <div className="text-[11px] text-gray-500">
              Die-pad → Package-ball net mapping ({netMapEntries.length} entries).
            </div>
            {netMapEntries.length === 0 && (
              <div className="text-gray-600 text-[11px]">No net map defined.</div>
            )}
            <div className="bg-white/5 rounded divide-y divide-white/5">
              {netMapEntries.map(([padId, ballId]) => {
                const ball = (pkg.ball_grid?.balls ?? []).find(b => b.id === ballId)
                return (
                  <div key={padId} className="flex items-center gap-3 px-2 py-1.5 text-[11px]">
                    <span className="font-mono text-amber-300 w-10">{padId}</span>
                    <span className="text-gray-600">→</span>
                    <span className="font-mono text-blue-300 w-10">{ballId}</span>
                    {ball?.net && (
                      <span className="text-gray-500">net: <span className="text-gray-300">{ball.net}</span></span>
                    )}
                    {ball && (
                      <span className="text-gray-600 text-[10px]">R{ball.row}C{ball.col}</span>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* ── Create tab ───────────────────────────────────────────────────── */}
        {tab === 'create' && (
          <div className="space-y-3">
            <div className="text-[11px] text-gray-500">
              Create a new IC package definition. The demo populates a 4×4 mm die
              with a 10×10 mm, 4-layer BT-resin substrate and 8×8 ball grid.
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <label className="text-[10px] text-gray-500">Package Name</label>
                <input
                  value={formName}
                  onChange={e => setFormName(e.target.value)}
                  className="w-full bg-white/10 border border-white/10 rounded px-2 py-1
                             text-gray-200 text-[11px] font-mono focus:outline-none focus:border-amber-500"
                />
              </div>
              <div className="space-y-1">
                <label className="text-[10px] text-gray-500">Package Type</label>
                <select
                  value={formType}
                  onChange={e => setFormType(e.target.value)}
                  className="w-full bg-gray-800 border border-white/10 rounded px-2 py-1
                             text-gray-200 text-[11px] focus:outline-none focus:border-amber-500">
                  <option value="wire_bond">Wire Bond</option>
                  <option value="flip_chip">Flip Chip</option>
                  <option value="bga_only">BGA Only</option>
                </select>
              </div>
            </div>

            <button
              onClick={createPkg}
              disabled={loading || !formName.trim()}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-700/30 hover:bg-amber-700/50
                         border border-amber-600/40 rounded text-amber-300 text-[11px] transition-colors disabled:opacity-50">
              {loading ? <RefreshCw size={11} className="animate-spin" /> : <Cpu size={11} />}
              Create Package
            </button>

            {createError && (
              <div className="text-red-400 text-[11px]">Error: {createError}</div>
            )}

            {createResult && (
              <div className="bg-green-900/20 border border-green-800/40 rounded p-2 text-[11px] text-green-300">
                Created {createResult.name} ({createResult.package_type}) — now shown in Viewer tab.
              </div>
            )}
          </div>
        )}

      </div>
    </div>
  )
}
