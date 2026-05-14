// StairView.jsx — Viewer/editor for .stair.json files.
import { useState, useEffect, useRef, useCallback } from 'react'
import { Plus, Trash2 } from 'lucide-react'
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
    </div>
  )
}
