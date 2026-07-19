// StairView.jsx — Viewer/editor for .stair.json files.
// Includes a Stair Code Check card (IBC 2024 / ADA §504 / ICC A117.1 / OBC).
import { useState, useEffect, useRef, useCallback } from 'react'
import { Plus, Trash2, ShieldCheck, ShieldAlert, AlertTriangle, FileText } from 'lucide-react'
import {
  defaultStair, validateStair, addFlight, addLanding,
  straightStairFromAB, lShapeStair, uShapeStair,
} from '../lib/stairs.js'

// ── Helpers ────────────────────────────────────────────────────────────────────
function parse(c) { try { return JSON.parse(c) } catch { return null } }
function uid() { return Math.random().toString(36).slice(2, 9) }

const iCls = 'w-full bg-ink-950 border border-ink-700 rounded px-2 py-0.5 text-[12px] text-ink-200 focus:outline-none focus:border-kerf-300/60'
const sCls = 'bg-ink-950 border border-ink-700 rounded px-1.5 py-0.5 text-[11px] text-ink-200 focus:outline-none focus:border-kerf-300/60'
const btnCls = 'inline-flex items-center gap-1 text-[11px] text-kerf-300 hover:text-kerf-200'
const buildBtnCls = 'px-2.5 py-1 rounded bg-kerf-300/10 border border-kerf-300/30 text-kerf-200 hover:bg-kerf-300/20 text-[11px]'

function Section({ title, action, children }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-[11px] uppercase tracking-widest font-semibold text-ink-500">{title}</h2>
        {action}
      </div>
      {children}
    </div>
  )
}
const Empty = ({ children }) => <p className="text-[11px] text-ink-600 italic py-1">{children}</p>
const Stat = ({ label, value }) => (
  <div className="flex flex-col gap-0.5">
    <span className="text-[10px] text-ink-500 uppercase tracking-wide">{label}</span>
    <span className="font-mono text-kerf-300 text-[13px]">{value}</span>
  </div>
)

// ── Stair Code Check card ──────────────────────────────────────────────────────

const CODE_JURISDICTIONS = [
  { value: 'ibc_2024',    label: 'IBC 2024 §1011' },
  { value: 'ada_504',     label: 'ADA §504' },
  { value: 'icc_a117_1',  label: 'ICC A117.1 §504' },
  { value: 'ontario_obc', label: 'Ontario OBC Part 9' },
]

const DEFAULT_CODE_SPEC = {
  tread_depth_in: 11.0,
  riser_height_in: 7.0,
  stair_width_in: 44.0,
  handrail_height_in: 36.0,
  headroom_clearance_in: 80.0,
  num_risers: 14,
  has_landing: false,
  landing_depth_in: 44.0,
  jurisdiction: 'ibc_2024',
}

// Inline pure-JS implementation mirrors kerf_cad_core.arch.stair_code_check
// so code checks work without a backend round-trip during UI interaction.
function runStairCodeCheck(spec) {
  const violations = []
  let riser_compliant = true
  let tread_compliant = true
  let width_compliant = true
  let handrail_compliant = true
  let headroom_compliant = true
  let landing_compliant = true
  let ratio_compliant = true
  let turning_compliant = true

  const R = spec.riser_height_in
  const T = spec.tread_depth_in
  const W = spec.stair_width_in
  const HR = spec.handrail_height_in
  const HC = spec.headroom_clearance_in
  const J = spec.jurisdiction

  if (J === 'ibc_2024' || J === 'icc_a117_1') {
    if (R < 4 || R > 7) {
      riser_compliant = false
      violations.push({ code_ref: `${J === 'ibc_2024' ? 'IBC 2024' : 'ICC A117.1'} §1011.5.2 / §504.2`, requirement: '4" ≤ riser ≤ 7"', actual: `${R}"` })
    }
    if (T < 11) {
      tread_compliant = false
      violations.push({ code_ref: `${J === 'ibc_2024' ? 'IBC 2024' : 'ICC A117.1'} §1011.5.3 / §504.2`, requirement: 'tread ≥ 11"', actual: `${T}"` })
    }
    if (W < 44) {
      width_compliant = false
      violations.push({ code_ref: `${J === 'ibc_2024' ? 'IBC 2024' : 'ICC A117.1'} §1011.2`, requirement: 'width ≥ 44" (occ. load ≥ 50)', actual: `${W}"` })
    }
    if (HR < 34 || HR > 38) {
      handrail_compliant = false
      violations.push({ code_ref: `${J === 'ibc_2024' ? 'IBC 2024' : 'ICC A117.1'} §1012.2 / §505.4`, requirement: '34" ≤ handrail ≤ 38"', actual: `${HR}"` })
    }
    if (HC < 80) {
      headroom_compliant = false
      violations.push({ code_ref: `${J === 'ibc_2024' ? 'IBC 2024' : 'ICC A117.1'} §1011.3`, requirement: 'headroom ≥ 80"', actual: `${HC}"` })
    }
    if (spec.has_landing && spec.landing_depth_in < 36) {
      landing_compliant = false
      violations.push({ code_ref: `${J === 'ibc_2024' ? 'IBC 2024' : 'ICC A117.1'} §1011.7`, requirement: 'landing depth ≥ 36"', actual: `${spec.landing_depth_in}"` })
    }
    const vertRise = R * spec.num_risers
    if (vertRise > 147) {
      turning_compliant = false
      violations.push({ code_ref: `${J === 'ibc_2024' ? 'IBC 2024' : 'ICC A117.1'} §1011.8`, requirement: 'max vertical rise between landings ≤ 147"', actual: `${vertRise.toFixed(1)}"` })
    }
  } else if (J === 'ada_504') {
    if (R < 4 || R > 7) {
      riser_compliant = false
      violations.push({ code_ref: 'ADA §504.2', requirement: '4" ≤ riser ≤ 7"', actual: `${R}"` })
    }
    if (T < 11) {
      tread_compliant = false
      violations.push({ code_ref: 'ADA §504.2', requirement: 'tread ≥ 11"', actual: `${T}"` })
    }
    if (T > 12) {
      tread_compliant = false
      violations.push({ code_ref: 'ADA §504.2', requirement: 'tread ≤ 12" (uniform nosing projection)', actual: `${T}"` })
    }
    if (HR < 34 || HR > 38) {
      handrail_compliant = false
      violations.push({ code_ref: 'ADA §505.4', requirement: '34" ≤ handrail ≤ 38"', actual: `${HR}"` })
    }
    if (HC < 80) {
      headroom_compliant = false
      violations.push({ code_ref: 'ADA §504 / IBC §1011.3', requirement: 'headroom ≥ 80"', actual: `${HC}"` })
    }
    if (W < 36) {
      width_compliant = false
      violations.push({ code_ref: 'ADA §504 (advisory)', requirement: 'accessible stair width ≥ 36"', actual: `${W}"` })
    }
    if (spec.has_landing && spec.landing_depth_in < 36) {
      landing_compliant = false
      violations.push({ code_ref: 'ADA §504 / IBC §1011.7', requirement: 'landing depth ≥ 36"', actual: `${spec.landing_depth_in}"` })
    }
  } else if (J === 'ontario_obc') {
    if (R < 3.94 || R > 8.27) {
      riser_compliant = false
      violations.push({ code_ref: 'OBC §9.8.4.1', requirement: '3.94" ≤ riser ≤ 8.27" (100–210 mm)', actual: `${R}"` })
    }
    if (T < 8.27) {
      tread_compliant = false
      violations.push({ code_ref: 'OBC §9.8.4.2', requirement: 'tread ≥ 8.27" (210 mm)', actual: `${T}"` })
    }
    if (W < 35.43) {
      width_compliant = false
      violations.push({ code_ref: 'OBC §9.8.2.1', requirement: 'width ≥ 35.43" (900 mm)', actual: `${W}"` })
    }
    if (HR < 34 || HR > 38) {
      handrail_compliant = false
      violations.push({ code_ref: 'OBC §9.8.7', requirement: '34"–38" (865–965 mm)', actual: `${HR}"` })
    }
    if (HC < 78.74) {
      headroom_compliant = false
      violations.push({ code_ref: 'OBC §9.8.3.1', requirement: 'headroom ≥ 78.74" (2000 mm)', actual: `${HC}"` })
    }
    if (spec.has_landing && spec.landing_depth_in < W) {
      landing_compliant = false
      violations.push({ code_ref: 'OBC §9.8.6.1', requirement: `landing depth ≥ stair width (${W}")`, actual: `${spec.landing_depth_in}"` })
    }
  }

  // Blondel — all jurisdictions
  const blondel = 2 * R + T
  if (blondel < 24 || blondel > 25) {
    ratio_compliant = false
    violations.push({ code_ref: 'Blondel formula', requirement: '24" ≤ 2R+T ≤ 25"', actual: `2×${R}+${T} = ${blondel.toFixed(2)}"` })
  }

  return {
    riser_compliant, tread_compliant, width_compliant, handrail_compliant,
    headroom_compliant, landing_compliant, ratio_2r_plus_t_compliant: ratio_compliant,
    turning_compliant,
    violations,
    all_compliant: violations.length === 0,
  }
}

function Badge({ ok, label }) {
  return (
    <div className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium ${
      ok ? 'bg-emerald-900/30 border border-emerald-700/30 text-emerald-300'
         : 'bg-red-900/30 border border-red-700/30 text-red-300'
    }`}>
      {ok ? <ShieldCheck size={10} /> : <ShieldAlert size={10} />}
      {label}
    </div>
  )
}

function StairCodeCheckCard() {
  const [spec, setSpec] = useState(DEFAULT_CODE_SPEC)
  const [result, setResult] = useState(null)

  const patch = (u) => setSpec((s) => ({ ...s, ...u }))

  function handleRun() {
    setResult(runStairCodeCheck(spec))
  }

  function handleGenerateSticker() {
    if (!result) return
    const lines = [
      `STAIR CODE COMPLIANCE SUMMARY`,
      `Jurisdiction: ${CODE_JURISDICTIONS.find((j) => j.value === spec.jurisdiction)?.label ?? spec.jurisdiction}`,
      `Generated: ${new Date().toISOString().slice(0, 10)}`,
      ``,
      `INPUTS`,
      `  Riser height:      ${spec.riser_height_in}"`,
      `  Tread depth:       ${spec.tread_depth_in}"`,
      `  Stair width:       ${spec.stair_width_in}"`,
      `  Handrail height:   ${spec.handrail_height_in}"`,
      `  Headroom:          ${spec.headroom_clearance_in}"`,
      `  Num risers:        ${spec.num_risers}`,
      `  Has landing:       ${spec.has_landing ? 'Yes' : 'No'}`,
      spec.has_landing ? `  Landing depth:     ${spec.landing_depth_in}"` : '',
      ``,
      `RESULTS  ${result.all_compliant ? '✓ ALL PASS' : '✗ VIOLATIONS FOUND'}`,
      `  Riser:             ${result.riser_compliant ? 'PASS' : 'FAIL'}`,
      `  Tread:             ${result.tread_compliant ? 'PASS' : 'FAIL'}`,
      `  Width:             ${result.width_compliant ? 'PASS' : 'FAIL'}`,
      `  Handrail:          ${result.handrail_compliant ? 'PASS' : 'FAIL'}`,
      `  Headroom:          ${result.headroom_compliant ? 'PASS' : 'FAIL'}`,
      `  Landing:           ${result.landing_compliant ? 'PASS' : 'FAIL'}`,
      `  2R+T (Blondel):    ${result.ratio_2r_plus_t_compliant ? 'PASS' : 'FAIL'}`,
      `  Turning (rise):    ${result.turning_compliant ? 'PASS' : 'FAIL'}`,
      ``,
    ]
    if (result.violations.length > 0) {
      lines.push('VIOLATIONS')
      result.violations.forEach((v) => {
        lines.push(`  [${v.code_ref}]`)
        lines.push(`    Required: ${v.requirement}`)
        lines.push(`    Actual:   ${v.actual}`)
      })
      lines.push('')
    }
    lines.push('CAVEAT')
    lines.push('This automated check does not substitute for a licensed architect\'s')
    lines.push('plan review or authority having jurisdiction (AHJ) approval.')
    const blob = new Blob([lines.filter(Boolean).join('\n')], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `stair-code-check-${spec.jurisdiction}-${new Date().toISOString().slice(0, 10)}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  const CHECKS = [
    ['Riser', result?.riser_compliant],
    ['Tread', result?.tread_compliant],
    ['Width', result?.width_compliant],
    ['Handrail', result?.handrail_compliant],
    ['Headroom', result?.headroom_compliant],
    ['Landing', result?.landing_compliant],
    ['2R+T (Blondel)', result?.ratio_2r_plus_t_compliant],
    ['Turning/Rise', result?.turning_compliant],
  ]

  return (
    <div className="space-y-3">
      {/* Jurisdiction + inputs */}
      <div className="grid grid-cols-2 gap-2 text-[11px]">
        <div className="col-span-2 flex flex-col gap-0.5">
          <span className="text-[10px] text-ink-500 uppercase tracking-wide">Jurisdiction</span>
          <select className={sCls} value={spec.jurisdiction} onChange={(e) => patch({ jurisdiction: e.target.value })}>
            {CODE_JURISDICTIONS.map((j) => <option key={j.value} value={j.value}>{j.label}</option>)}
          </select>
        </div>
        {[
          ['Riser height (in)', 'riser_height_in', 0.5, 12, 0.25],
          ['Tread depth (in)', 'tread_depth_in', 6, 24, 0.25],
          ['Stair width (in)', 'stair_width_in', 12, 120, 1],
          ['Handrail ht. (in)', 'handrail_height_in', 20, 50, 0.5],
          ['Headroom (in)', 'headroom_clearance_in', 60, 120, 1],
          ['Num risers', 'num_risers', 1, 200, 1],
        ].map(([label, key, min, max, step]) => (
          <div key={key} className="flex flex-col gap-0.5">
            <span className="text-[10px] text-ink-500 uppercase tracking-wide">{label}</span>
            <input
              className={iCls} type="number"
              value={spec[key]} min={min} max={max} step={step}
              onChange={(e) => patch({ [key]: parseFloat(e.target.value) || 0 })}
            />
          </div>
        ))}
        <div className="flex flex-col gap-0.5">
          <span className="text-[10px] text-ink-500 uppercase tracking-wide">Has landing</span>
          <label className="flex items-center gap-1.5 text-[11px] text-ink-300 pt-0.5">
            <input type="checkbox" checked={spec.has_landing} onChange={(e) => patch({ has_landing: e.target.checked })} />
            Intermediate landing
          </label>
        </div>
        {spec.has_landing && (
          <div className="flex flex-col gap-0.5">
            <span className="text-[10px] text-ink-500 uppercase tracking-wide">Landing depth (in)</span>
            <input
              className={iCls} type="number"
              value={spec.landing_depth_in} min={12} max={120} step={1}
              onChange={(e) => patch({ landing_depth_in: parseFloat(e.target.value) || 36 })}
            />
          </div>
        )}
      </div>

      {/* Run button */}
      <button
        type="button"
        onClick={handleRun}
        className="w-full px-3 py-1.5 rounded bg-kerf-300/15 border border-kerf-300/30 text-kerf-200 hover:bg-kerf-300/25 text-[11px] font-medium"
      >
        Run Code Check
      </button>

      {/* Results */}
      {result && (
        <div className="space-y-2">
          {/* Status banner */}
          <div className={`flex items-center gap-2 px-3 py-2 rounded border text-[11px] font-medium ${
            result.all_compliant
              ? 'bg-emerald-900/20 border-emerald-700/30 text-emerald-300'
              : 'bg-red-900/20 border-red-700/30 text-red-300'
          }`}>
            {result.all_compliant ? <ShieldCheck size={13} /> : <ShieldAlert size={13} />}
            {result.all_compliant ? 'All checks pass' : `${result.violations.length} violation${result.violations.length !== 1 ? 's' : ''} found`}
          </div>

          {/* Per-category badges */}
          <div className="flex flex-wrap gap-1">
            {CHECKS.map(([label, ok]) => (
              <Badge key={label} ok={ok ?? true} label={label} />
            ))}
          </div>

          {/* Violations table */}
          {result.violations.length > 0 && (
            <div className="rounded border border-red-800/30 overflow-hidden">
              <div className="px-2 py-1 bg-red-900/20 text-[10px] uppercase tracking-wide text-red-400 font-semibold flex items-center gap-1">
                <AlertTriangle size={10} />Violations
              </div>
              <table className="w-full text-[10px]">
                <thead>
                  <tr className="border-b border-ink-800">
                    <th className="px-2 py-0.5 text-left text-ink-500 font-normal">Code ref</th>
                    <th className="px-2 py-0.5 text-left text-ink-500 font-normal">Requirement</th>
                    <th className="px-2 py-0.5 text-left text-ink-500 font-normal">Actual</th>
                  </tr>
                </thead>
                <tbody>
                  {result.violations.map((v, i) => (
                    <tr key={i} className="border-b border-ink-900 last:border-0">
                      <td className="px-2 py-1 font-mono text-amber-300">{v.code_ref}</td>
                      <td className="px-2 py-1 text-ink-300">{v.requirement}</td>
                      <td className="px-2 py-1 font-mono text-red-300">{v.actual}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Generate sticker */}
          <button
            type="button"
            onClick={handleGenerateSticker}
            className="inline-flex items-center gap-1.5 text-[11px] text-kerf-300 hover:text-kerf-200"
          >
            <FileText size={11} />Generate Code Summary Sticker (.txt)
          </button>
        </div>
      )}
    </div>
  )
}

// ── SVG side-view preview ──────────────────────────────────────────────────────
function StairSVG({ stair }) {
  const r = stair.riser_height_mm || 175
  const t = stair.tread_depth_mm || 280
  const steps = Math.round((stair.total_rise_mm || 2100) / r) || 12

  const W = 260
  const H = 120
  const margin = 10
  const usableW = W - margin * 2
  const usableH = H - margin * 2
  const sx = usableW / (steps * t || 1)
  const sy = usableH / (steps * r || 1)
  const scale = Math.min(sx, sy)

  const pts = []
  for (let i = 0; i <= steps; i++) {
    pts.push([margin + i * t * scale, H - margin - i * r * scale])
    if (i < steps) pts.push([margin + (i + 1) * t * scale, H - margin - i * r * scale])
  }

  const d = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ')

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto rounded border border-ink-800 bg-ink-950">
      <path d={d} fill="none" stroke="#5da9ff" strokeWidth="1.5" />
      <line x1={margin} y1={H - margin} x2={margin + steps * t * scale} y2={H - margin}
        stroke="#334155" strokeWidth="1" />
    </svg>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────
export default function StairView({ content, fileName, onContentChange }) {
  const [stair, setStair] = useState(() => parse(content) || defaultStair({ total_rise_mm: 2800, total_run_mm: 4200 }))
  const debRef = useRef(null)

  useEffect(() => { const n = parse(content); if (n) setStair(n) }, [content])

  const commit = useCallback((next) => {
    setStair(next)
    if (debRef.current) clearTimeout(debRef.current)
    debRef.current = setTimeout(() => onContentChange?.(JSON.stringify(next, null, 2)), 250)
  }, [onContentChange])

  const patch = (u) => commit({ ...stair, ...u })

  const riser = stair.riser_height_mm || 175
  const tread = stair.tread_depth_mm || 280
  const formula = 2 * riser + tread
  const formulaOk = formula >= 550 && formula <= 700
  const totalSteps = Math.round((stair.total_rise_mm || 0) / riser) || 0

  const validation = validateStair(stair)

  function buildStraight() {
    const a = prompt('Point A (x,y,z):', '0,0,0')
    const b = prompt('Point B (x,y,z):', '4200,0,2800')
    if (!a || !b) return
    const pa = a.split(',').map(Number)
    const pb = b.split(',').map(Number)
    if (pa.length === 3 && pb.length === 3) commit(straightStairFromAB(pa, pb, stair))
  }

  function buildL() {
    const r1 = parseFloat(prompt('Leg 1 run (mm):', '2100') || '0')
    const r2 = parseFloat(prompt('Leg 2 run (mm):', '2100') || '0')
    if (r1 > 0 && r2 > 0) commit(lShapeStair([0, 0, 0], r1, r2, [1000, 1000], stair))
  }

  function buildU() {
    const lr = parseFloat(prompt('Leg run (mm):', '2800') || '0')
    if (lr > 0) commit(uShapeStair([0, 0, 0], lr, [1000, 1000], stair))
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto bg-ink-950 text-ink-100 p-4 space-y-5">
      {/* Header */}
      <Section title="Stair">
        <div className="grid grid-cols-2 gap-3 text-[12px]">
          {[
            ['Shape', (
              <select className={sCls} value={stair.shape || 'straight'} onChange={(e) => patch({ shape: e.target.value })}>
                {['straight', 'L-shape', 'U-shape'].map((s) => <option key={s}>{s}</option>)}
              </select>
            )],
            ['Width (mm)', <input className={iCls} type="number" value={stair.width_mm ?? 1000} onChange={(e) => patch({ width_mm: parseFloat(e.target.value) || 1000 })} />],
            ['Total rise (mm)', <input className={iCls} type="number" value={stair.total_rise_mm ?? ''} onChange={(e) => patch({ total_rise_mm: parseFloat(e.target.value) || 0 })} />],
            ['Total run (mm)', <input className={iCls} type="number" value={stair.total_run_mm ?? ''} onChange={(e) => patch({ total_run_mm: parseFloat(e.target.value) || 0 })} />],
          ].map(([label, field]) => (
            <div key={label} className="flex flex-col gap-1">
              <span className="text-[10px] text-ink-500 uppercase tracking-wide">{label}</span>
              {field}
            </div>
          ))}
        </div>
      </Section>

      {/* Step params */}
      <Section title="Step parameters">
        <div className="space-y-3 text-[12px]">
          <div className="flex flex-col gap-1">
            <div className="flex justify-between">
              <span className="text-[10px] text-ink-500 uppercase tracking-wide">Riser height (mm)</span>
              <span className="text-[11px] font-mono text-kerf-300">{riser}</span>
            </div>
            <input type="range" min={100} max={220} value={riser}
              onChange={(e) => patch({ riser_height_mm: parseInt(e.target.value, 10) })}
              className="w-full accent-kerf-300" />
          </div>
          <div className="flex flex-col gap-1">
            <div className="flex justify-between">
              <span className="text-[10px] text-ink-500 uppercase tracking-wide">Tread depth (mm)</span>
              <span className="text-[11px] font-mono text-kerf-300">{tread}</span>
            </div>
            <input type="range" min={200} max={350} value={tread}
              onChange={(e) => patch({ tread_depth_mm: parseInt(e.target.value, 10) })}
              className="w-full accent-kerf-300" />
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-[10px] text-ink-500 uppercase tracking-wide">Nosing (mm)</span>
            <input className={iCls} type="number" value={stair.nosing_mm ?? 25} onChange={(e) => patch({ nosing_mm: parseFloat(e.target.value) || 0 })} />
          </div>
          <div className={`flex items-center gap-3 rounded px-3 py-2 text-[11px] ${formulaOk ? 'bg-kerf-300/10 border border-kerf-300/20 text-kerf-300' : 'bg-amber-900/20 border border-amber-700/30 text-amber-300'}`}>
            <span>2R+T = <strong className="font-mono">{formula}</strong> mm</span>
            <span className="text-ink-500">·</span>
            <span>{formulaOk ? 'Comfort range OK (550–700)' : 'Outside comfort range 550–700'}</span>
          </div>
        </div>
      </Section>

      {/* Flights */}
      <Section title="Flights" action={
        <button type="button" className={btnCls}
          onClick={() => commit(addFlight(stair, { id: `fl_${uid()}`, start_point: [0, 0, 0], direction: [1, 0, 0], step_count: 6 }))}>
          <Plus size={12} />Add
        </button>
      }>
        {(!stair.flights || stair.flights.length === 0) ? <Empty>No flights yet.</Empty> : stair.flights.map((fl, idx) => (
          <div key={fl.id} className="flex items-center gap-2 py-1.5 border-b border-ink-850 text-[11px]">
            <span className="text-ink-500 w-5">{idx + 1}</span>
            <div className="flex flex-col gap-1 flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-ink-500 w-10">Start</span>
                <input className={iCls} defaultValue={(fl.start_point || [0, 0, 0]).join(', ')}
                  onBlur={(e) => {
                    const p = e.target.value.split(',').map(Number)
                    if (p.length === 3) commit({ ...stair, flights: stair.flights.map((f) => f.id === fl.id ? { ...f, start_point: p } : f) })
                  }} />
              </div>
              <div className="flex items-center gap-2">
                <span className="text-ink-500 w-10">Dir</span>
                <input className={iCls} defaultValue={(fl.direction || [1, 0, 0]).join(', ')}
                  onBlur={(e) => {
                    const p = e.target.value.split(',').map(Number)
                    if (p.length === 3) commit({ ...stair, flights: stair.flights.map((f) => f.id === fl.id ? { ...f, direction: p } : f) })
                  }} />
                <span className="text-ink-500 w-14 flex-shrink-0">Steps</span>
                <input className={iCls} type="number" value={fl.step_count ?? 6}
                  onChange={(e) => commit({ ...stair, flights: stair.flights.map((f) => f.id === fl.id ? { ...f, step_count: parseInt(e.target.value, 10) || 1 } : f) })} />
              </div>
            </div>
            <button type="button" onClick={() => commit({ ...stair, flights: stair.flights.filter((f) => f.id !== fl.id) })}
              className="p-0.5 text-ink-500 hover:text-red-400 flex-shrink-0"><Trash2 size={12} /></button>
          </div>
        ))}
      </Section>

      {/* Landings */}
      <Section title="Landings" action={
        <button type="button" className={btnCls}
          onClick={() => commit(addLanding(stair, { id: `ld_${uid()}`, position: [0, 0, 0], size_mm: [1000, 1000] }))}>
          <Plus size={12} />Add
        </button>
      }>
        {(!stair.landings || stair.landings.length === 0) ? <Empty>No landings yet.</Empty> : stair.landings.map((ld) => (
          <div key={ld.id} className="flex items-center gap-2 py-1.5 border-b border-ink-850 text-[11px]">
            <div className="flex-1 min-w-0 grid grid-cols-2 gap-2">
              <div className="flex flex-col gap-0.5">
                <span className="text-[10px] text-ink-500">Position</span>
                <input className={iCls} defaultValue={(ld.position || [0, 0, 0]).join(', ')}
                  onBlur={(e) => {
                    const p = e.target.value.split(',').map(Number)
                    if (p.length === 3) commit({ ...stair, landings: stair.landings.map((l) => l.id === ld.id ? { ...l, position: p } : l) })
                  }} />
              </div>
              <div className="flex flex-col gap-0.5">
                <span className="text-[10px] text-ink-500">Size W×D</span>
                <input className={iCls} defaultValue={(ld.size_mm || [1000, 1000]).join(', ')}
                  onBlur={(e) => {
                    const p = e.target.value.split(',').map(Number)
                    if (p.length === 2) commit({ ...stair, landings: stair.landings.map((l) => l.id === ld.id ? { ...l, size_mm: p } : l) })
                  }} />
              </div>
            </div>
            <button type="button" onClick={() => commit({ ...stair, landings: stair.landings.filter((l) => l.id !== ld.id) })}
              className="p-0.5 text-ink-500 hover:text-red-400 flex-shrink-0"><Trash2 size={12} /></button>
          </div>
        ))}
      </Section>

      {/* Computed */}
      <Section title="Computed">
        <div className="flex gap-6 flex-wrap">
          <Stat label="Total steps" value={totalSteps} />
          <Stat label="Actual riser" value={`${totalSteps > 0 ? ((stair.total_rise_mm || 0) / totalSteps).toFixed(1) : '—'} mm`} />
        </div>
        {!validation.ok && (
          <ul className="mt-2 space-y-0.5">
            {validation.errors.map((e) => <li key={e} className="text-[11px] text-amber-400">{e}</li>)}
          </ul>
        )}
      </Section>

      {/* Preview */}
      <Section title="Preview (side view)">
        <StairSVG stair={stair} />
      </Section>

      {/* Build shapes */}
      <Section title="Build shape">
        <div className="flex gap-2 flex-wrap">
          <button type="button" className={buildBtnCls} onClick={buildStraight}>Build straight A→B</button>
          <button type="button" className={buildBtnCls} onClick={buildL}>Build L-shape</button>
          <button type="button" className={buildBtnCls} onClick={buildU}>Build U-shape</button>
        </div>
      </Section>

      {/* Code check */}
      <Section title="Stair Code Check (IBC / ADA / ICC A117.1 / OBC)">
        <StairCodeCheckCard />
      </Section>
    </div>
  )
}
