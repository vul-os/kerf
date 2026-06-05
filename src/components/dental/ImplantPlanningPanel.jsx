/**
 * ImplantPlanningPanel — Multi-implant planning with brand catalogue,
 * Tarnow/Grunder spacing checks, and drill sequence viewer.
 *
 * Features:
 *  - Straumann BLT / NobelActive / Astra EV brand selection
 *  - Inter-implant spacing check (Tarnow 2000: ≥ 3 mm)
 *  - Implant-to-tooth check (Grunder 2005: ≥ 1.5 mm)
 *  - Step-by-step drill sequence per IFU
 *
 * Backend tools:
 *  - dental_implant_spacing_check
 *  - dental_drill_sequence
 *  - dental_implant_plan_v2
 */

import { useState } from 'react'
import { useAuth } from '../../store/auth.js'

const API_URL = import.meta.env.VITE_API_URL || ''

const BRANDS = ['Straumann BLT', 'NobelActive', 'Astra EV']

const BRAND_DIAMETERS = {
  'Straumann BLT': [3.3, 4.1, 4.8],
  'NobelActive': [3.5, 4.3, 5.0],
  'Astra EV': [3.5, 4.0, 4.5],
}

const BRAND_LENGTHS = {
  'Straumann BLT': [6, 8, 10, 12, 14, 16],
  'NobelActive': [8.5, 10, 11.5, 13, 15],
  'Astra EV': [6, 8, 9, 11, 13],
}

function callTool(tool, args, accessToken) {
  return fetch(`${API_URL}/api/tools/call`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      ...(accessToken ? { authorization: `Bearer ${accessToken}` } : {}),
    },
    body: JSON.stringify({ tool, args }),
  }).then((r) => r.json().catch(() => ({})))
}

export default function ImplantPlanningPanel({ projectId }) {
  const { accessToken } = useAuth()

  const [brand, setBrand]   = useState('Straumann BLT')
  const [diam, setDiam]     = useState(4.1)
  const [length, setLength] = useState(10)

  // Two implant positions for Tarnow check
  const [pos1, setPos1] = useState([0, 0, 0])
  const [pos2, setPos2] = useState([7, 0, 0])
  const [toothPos, setToothPos] = useState(null) // optional adjacent tooth

  const [drillSeq, setDrillSeq]     = useState(null)
  const [spacing, setSpacing]       = useState(null)
  const [loading, setLoading]       = useState(null) // 'drill' | 'spacing'
  const [error, setError]           = useState(null)

  async function handleDrillSeq() {
    setLoading('drill')
    setError(null)
    const data = await callTool('dental_drill_sequence', { brand, diameter_mm: diam }, accessToken)
    setLoading(null)
    if (data.error) setError(data.error)
    else setDrillSeq(data)
  }

  async function handleSpacingCheck() {
    setLoading('spacing')
    setError(null)
    const args = {
      implant_positions: [pos1, pos2],
      implant_diameters_mm: [diam, diam],
    }
    if (toothPos) args.adjacent_tooth_positions = [toothPos]
    const data = await callTool('dental_implant_spacing_check', args, accessToken)
    setLoading(null)
    if (data.error) setError(data.error)
    else setSpacing(data)
  }

  function updatePos(setter, idx, val) {
    setter((prev) => {
      const next = [...prev]
      next[idx] = parseFloat(val) || 0
      return next
    })
  }

  const PosInput = ({ label, pos, setPos }) => (
    <div className="flex items-center gap-1.5 text-[10px]">
      <span className="text-ink-500 w-8">{label}</span>
      {['x', 'y', 'z'].map((ax, i) => (
        <label key={ax} className="flex items-center gap-0.5">
          <span className="text-ink-600">{ax}</span>
          <input
            type="number" step="1" value={pos[i]}
            onChange={(e) => updatePos(setPos, i, e.target.value)}
            className="w-12 bg-ink-800 border border-ink-700 rounded px-1 py-0.5 font-mono text-ink-100 outline-none focus:border-teal-400/60"
          />
        </label>
      ))}
    </div>
  )

  return (
    <div className="flex flex-col gap-4 p-4 text-ink-100" data-testid="implant-planning-panel">
      {/* Header */}
      <div className="flex items-center gap-2">
        <span className="text-[11px] font-mono uppercase tracking-widest text-ink-400">Implant Planning</span>
        <span className="ml-auto text-[10px] text-ink-600 font-mono">dental_implant_spacing_check</span>
      </div>

      {/* Brand + dimensions */}
      <div className="grid grid-cols-3 gap-2">
        <div>
          <label className="block text-[10px] text-ink-500 mb-1">Brand</label>
          <select
            value={brand}
            onChange={(e) => { setBrand(e.target.value); setDiam(BRAND_DIAMETERS[e.target.value][1]); setLength(BRAND_LENGTHS[e.target.value][2]) }}
            className="w-full bg-ink-800 border border-ink-700 rounded px-2 py-1.5 text-xs text-ink-100 outline-none focus:border-teal-400/60"
          >
            {BRANDS.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-[10px] text-ink-500 mb-1">Diameter (mm)</label>
          <select
            value={diam}
            onChange={(e) => setDiam(parseFloat(e.target.value))}
            className="w-full bg-ink-800 border border-ink-700 rounded px-2 py-1.5 text-xs text-ink-100 outline-none focus:border-teal-400/60"
          >
            {(BRAND_DIAMETERS[brand] || []).map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-[10px] text-ink-500 mb-1">Length (mm)</label>
          <select
            value={length}
            onChange={(e) => setLength(parseInt(e.target.value, 10))}
            className="w-full bg-ink-800 border border-ink-700 rounded px-2 py-1.5 text-xs text-ink-100 outline-none focus:border-teal-400/60"
          >
            {(BRAND_LENGTHS[brand] || []).map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
        </div>
      </div>

      {/* Drill sequence */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="text-[11px] text-ink-400">Drill sequence (per IFU)</span>
          <button
            type="button"
            onClick={handleDrillSeq}
            disabled={loading === 'drill'}
            className="text-[10px] px-2 py-1 rounded bg-teal-500/15 border border-teal-400/30 text-teal-300 hover:bg-teal-500/25 disabled:opacity-50"
          >
            {loading === 'drill' ? (
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 border border-teal-400 border-t-transparent rounded-full animate-spin" />
                Loading…
              </span>
            ) : 'Get sequence'}
          </button>
        </div>
        {drillSeq?.steps && (
          <div className="flex flex-col gap-1 mt-1" data-testid="drill-sequence-result">
            {drillSeq.steps.map((step) => (
              <div
                key={step.step}
                className="flex items-center gap-2 px-2 py-1 rounded bg-ink-800 border border-ink-700 text-[10px] font-mono"
              >
                <span className="w-4 text-teal-400 font-bold">{step.step}</span>
                <span className="flex-1 text-ink-200">{step.drill}</span>
                <span className="text-teal-300">⌀{step.diameter_mm}</span>
                <span className="text-ink-500">{step.speed_rpm} rpm</span>
                <span className="text-ink-500">{step.torque_ncm} Ncm</span>
              </div>
            ))}
            <p className="text-[9px] text-ink-600 mt-0.5">{drillSeq.disclaimer}</p>
          </div>
        )}
      </div>

      {/* Tarnow / Grunder spacing check */}
      <div>
        <span className="text-[11px] text-ink-400 block mb-2">Spacing check (Tarnow 2000 / Grunder 2005)</span>

        <div className="flex flex-col gap-1.5">
          <PosInput label="Imp 1" pos={pos1} setPos={setPos1} />
          <PosInput label="Imp 2" pos={pos2} setPos={setPos2} />
        </div>

        <button
          type="button"
          onClick={handleSpacingCheck}
          disabled={loading === 'spacing'}
          className="mt-2 w-full flex items-center justify-center gap-2 px-4 py-2 rounded bg-teal-500/20 border border-teal-400/50 text-teal-200 text-xs font-medium hover:bg-teal-500/30 disabled:opacity-50 transition-colors"
        >
          {loading === 'spacing' ? (
            <>
              <span className="w-3 h-3 border-2 border-teal-400 border-t-transparent rounded-full animate-spin" />
              Checking…
            </>
          ) : 'Check spacing'}
        </button>
      </div>

      {/* Spacing result */}
      {spacing && (
        <div
          className={`rounded border p-3 text-[11px] font-mono space-y-1 ${
            spacing.tarnow_ok && spacing.grunder_ok
              ? 'bg-emerald-950/30 border-emerald-700/50 text-emerald-300'
              : 'bg-amber-950/30 border-amber-700/50 text-amber-300'
          }`}
          data-testid="spacing-result"
        >
          <div className="font-semibold mb-1">
            {spacing.tarnow_ok && spacing.grunder_ok ? 'Spacing OK' : 'Spacing violations'}
          </div>
          {spacing.min_implant_to_implant_mm != null && (
            <div>
              imp–imp: <span className={spacing.tarnow_ok ? 'text-emerald-200' : 'text-red-400'}>
                {spacing.min_implant_to_implant_mm} mm
              </span>
              <span className="text-ink-500 ml-1">(Tarnow min 3 mm)</span>
            </div>
          )}
          {spacing.min_implant_to_tooth_mm != null && (
            <div>
              imp–tooth: <span className={spacing.grunder_ok ? 'text-emerald-200' : 'text-red-400'}>
                {spacing.min_implant_to_tooth_mm} mm
              </span>
              <span className="text-ink-500 ml-1">(Grunder min 1.5 mm)</span>
            </div>
          )}
          {spacing.tarnow_violations.map((v, i) => (
            <div key={i} className="text-red-400 text-[10px]">
              Tarnow: implant {v.implant_i + 1}–{v.implant_j + 1}: {v.surface_to_surface_mm} mm (deficit {v.deficit_mm} mm)
            </div>
          ))}
          {spacing.grunder_violations.map((v, i) => (
            <div key={i} className="text-amber-400 text-[10px]">
              Grunder: implant {v.implant_i + 1}–tooth {v.tooth_j + 1}: {v.surface_to_tooth_mm} mm (deficit {v.deficit_mm} mm)
            </div>
          ))}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="rounded border border-red-700/50 bg-red-950/30 p-3 text-[11px] font-mono text-red-300" data-testid="implant-planning-error">
          {error}
        </div>
      )}

      {/* Footer */}
      <p className="text-[10px] text-ink-600 leading-relaxed">
        Tarnow 2000: implant-to-implant ≥ 3 mm surface-to-surface.
        Grunder 2005: implant-to-tooth ≥ 1.5 mm.
        NOT FDA-cleared — verify all measurements clinically.
      </p>
    </div>
  )
}
