// MEPView.jsx — Viewer/editor for .duct.json / .pipe.json / .conduit.json files.
import { useState, useEffect, useRef, useCallback } from 'react'
import { Plus, Trash2, Zap } from 'lucide-react'
import {
  defaultMepRoute, addSegment, addFitting, addEndpoint,
  computeRouteLength, computePressureDrop, connectEndpoints,
} from '../lib/mep.js'

// ── Helpers ────────────────────────────────────────────────────────────────────
function parseContent(c) { try { return JSON.parse(c) } catch { return null } }
function uid() { return Math.random().toString(36).slice(2, 9) }
function kindFromFileName(name) {
  const n = (name || '').toLowerCase()
  if (n.includes('.duct.')) return 'duct'
  if (n.includes('.pipe.')) return 'pipe'
  if (n.includes('.conduit.')) return 'conduit'
  return 'duct'
}
const KIND_BADGE = {
  duct:    'bg-blue-900/40 text-blue-300 border border-blue-700/50',
  pipe:    'bg-green-900/40 text-green-300 border border-green-700/50',
  conduit: 'bg-amber-900/40 text-amber-300 border border-amber-700/50',
}
const iCls = 'w-full bg-ink-950 border border-ink-700 rounded px-2 py-0.5 text-[12px] text-ink-200 focus:outline-none focus:border-kerf-300/60'
const sCls = 'bg-ink-950 border border-ink-700 rounded px-1.5 py-0.5 text-[11px] text-ink-200 focus:outline-none focus:border-kerf-300/60'

function CoordCell({ value, onChange }) {
  const txt = Array.isArray(value) ? value.join(', ') : ''
  return (
    <input className={iCls} defaultValue={txt} onBlur={(e) => {
      const p = e.target.value.split(',').map((s) => parseFloat(s.trim()))
      if (p.length === 3 && p.every(Number.isFinite)) onChange(p)
    }} />
  )
}
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
const AddBtn = ({ onClick }) => (
  <button type="button" onClick={onClick} className="inline-flex items-center gap-1 text-[11px] text-kerf-300 hover:text-kerf-200"><Plus size={12} />Add</button>
)
const Empty = ({ children }) => <p className="text-[11px] text-ink-600 italic py-1">{children}</p>

// ── Main component ─────────────────────────────────────────────────────────────
export default function MEPView({ content, fileName, onContentChange }) {
  const kind = kindFromFileName(fileName)
  const [route, setRoute] = useState(() => parseContent(content) || defaultMepRoute(kind))
  const [autoStart, setAutoStart] = useState('')
  const [autoEnd, setAutoEnd] = useState('')
  const [autoWarn, setAutoWarn] = useState('')
  const debRef = useRef(null)

  useEffect(() => { const n = parseContent(content); if (n) setRoute(n) }, [content])

  const commit = useCallback((next) => {
    setRoute(next)
    if (debRef.current) clearTimeout(debRef.current)
    debRef.current = setTimeout(() => onContentChange?.(JSON.stringify(next, null, 2)), 250)
  }, [onContentChange])

  const patch = (u) => commit({ ...route, ...u })
  const patchSeg = (id, u) => commit({ ...route, segments: route.segments.map((s) => s.id === id ? { ...s, ...u } : s) })
  const patchEp  = (id, u) => commit({ ...route, endpoints: route.endpoints.map((e) => e.id === id ? { ...e, ...u } : e) })

  function runAutoRoute() {
    setAutoWarn('')
    if (!autoStart || !autoEnd) { setAutoWarn('Pick both endpoints first.'); return }
    try {
      const { route: next, warning } = connectEndpoints(route, autoStart, autoEnd, [])
      commit(next)
      if (warning) setAutoWarn(warning)
    } catch (err) { setAutoWarn(err.message) }
  }

  const lengthMm   = computeRouteLength(route)
  const pressurePa = computePressureDrop(route)

  return (
    <div className="flex-1 min-h-0 overflow-y-auto bg-ink-950 text-ink-100 p-4 space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3 flex-wrap">
        <span className={`text-[10px] uppercase tracking-widest font-semibold px-2 py-0.5 rounded ${KIND_BADGE[route.kind] || KIND_BADGE.duct}`}>{route.kind}</span>
        <input className="flex-1 min-w-[160px] bg-ink-900 border border-ink-700 rounded px-2 py-1 text-sm text-ink-100 focus:outline-none focus:border-kerf-300/60"
          value={route.system_name || ''} placeholder="System name" onChange={(e) => patch({ system_name: e.target.value })} />
        <div className="flex items-center gap-1.5 text-[11px] text-ink-400">
          <label htmlFor="mep-color">Colour</label>
          <input id="mep-color" type="color" value={route.system_color || '#5da9ff'}
            onChange={(e) => patch({ system_color: e.target.value })}
            className="w-7 h-7 rounded border border-ink-700 cursor-pointer bg-transparent" />
        </div>
      </div>

      {/* Properties */}
      <Section title="Properties">
        <div className="grid grid-cols-2 gap-3 text-[12px]">
          {[
            ['Material', <input className={iCls} value={route.material || ''} onChange={(e) => patch({ material: e.target.value })} />],
            ['Insulation (mm)', <input className={iCls} type="number" value={route.insulation_thickness_mm ?? 0} onChange={(e) => patch({ insulation_thickness_mm: parseFloat(e.target.value) || 0 })} />],
            ...(route.width_mm != null
              ? [['Width (mm)', <input className={iCls} type="number" value={route.width_mm ?? ''} onChange={(e) => patch({ width_mm: parseFloat(e.target.value) || null })} />],
                 ['Height (mm)', <input className={iCls} type="number" value={route.height_mm ?? ''} onChange={(e) => patch({ height_mm: parseFloat(e.target.value) || null })} />]]
              : [['Diameter (mm)', <input className={iCls} type="number" value={route.size_mm ?? ''} onChange={(e) => patch({ size_mm: parseFloat(e.target.value) || null })} />]])
          ].map(([label, field]) => (
            <div key={label} className="flex flex-col gap-1">
              <span className="text-[10px] text-ink-500 uppercase tracking-wide">{label}</span>
              {field}
            </div>
          ))}
        </div>
      </Section>

      {/* Segments */}
      <Section title="Segments" action={<AddBtn onClick={() => commit(addSegment(route, { id: `s_${uid()}`, from: [0,0,0], to: [1000,0,0], kind: 'straight' }))} />}>
        {route.segments.length === 0 ? <Empty>No segments yet.</Empty> : (
          <div className="overflow-x-auto">
            <table className="w-full text-[11px] border-collapse">
              <thead><tr className="text-ink-500 border-b border-ink-800">
                {['Kind','From XYZ','To XYZ','Elbow r (mm)',''].map((h) => <th key={h} className="text-left px-2 py-1 font-medium">{h}</th>)}
              </tr></thead>
              <tbody>
                {route.segments.map((seg) => (
                  <tr key={seg.id} className="border-b border-ink-850 hover:bg-ink-900/40">
                    <td className="px-2 py-1">
                      <select className={sCls} value={seg.kind || 'straight'} onChange={(e) => patchSeg(seg.id, { kind: e.target.value })}>
                        {['straight','elbow','vertical'].map((k) => <option key={k}>{k}</option>)}
                      </select>
                    </td>
                    <td className="px-2 py-1 w-40"><CoordCell value={seg.from} onChange={(v) => patchSeg(seg.id, { from: v })} /></td>
                    <td className="px-2 py-1 w-40"><CoordCell value={seg.to}   onChange={(v) => patchSeg(seg.id, { to: v })} /></td>
                    <td className="px-2 py-1 w-24">
                      {seg.kind === 'elbow' && <input className={iCls} type="number" value={seg.elbow_radius_mm ?? ''} onChange={(e) => patchSeg(seg.id, { elbow_radius_mm: parseFloat(e.target.value) || undefined })} />}
                    </td>
                    <td className="px-2 py-1">
                      <button type="button" onClick={() => commit({ ...route, segments: route.segments.filter((s) => s.id !== seg.id) })} className="p-0.5 text-ink-500 hover:text-red-400"><Trash2 size={12} /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {/* Fittings */}
      <Section title="Fittings" action={<AddBtn onClick={() => commit(addFitting(route, { id: `f_${uid()}`, kind: 'tee', position: [0,0,0], branches: [] }))} />}>
        {route.fittings.length === 0 ? <Empty>No fittings yet.</Empty> : route.fittings.map((f) => (
          <div key={f.id} className="flex items-center gap-2 py-1 border-b border-ink-850 text-[11px]">
            <select className={sCls} value={f.kind} onChange={(e) => commit({ ...route, fittings: route.fittings.map((x) => x.id === f.id ? { ...x, kind: e.target.value } : x) })}>
              {['tee','reducer','transition','cap','cross'].map((k) => <option key={k}>{k}</option>)}
            </select>
            <span className="text-ink-500">@</span>
            <div className="w-40"><CoordCell value={f.position} onChange={(v) => commit({ ...route, fittings: route.fittings.map((x) => x.id === f.id ? { ...x, position: v } : x) })} /></div>
            <button type="button" onClick={() => commit({ ...route, fittings: route.fittings.filter((x) => x.id !== f.id) })} className="p-0.5 text-ink-500 hover:text-red-400 ml-auto"><Trash2 size={12} /></button>
          </div>
        ))}
      </Section>

      {/* Endpoints */}
      <Section title="Endpoints" action={<AddBtn onClick={() => commit(addEndpoint(route, { id: `ep_${uid()}`, kind: 'source', position: [0,0,0] }))} />}>
        {route.endpoints.length === 0 ? <Empty>No endpoints yet.</Empty> : route.endpoints.map((ep) => (
          <div key={ep.id} className="flex items-center gap-2 py-1 border-b border-ink-850 text-[11px]">
            <select className={sCls} value={ep.kind} onChange={(e) => patchEp(ep.id, { kind: e.target.value })}>
              <option value="source">source</option>
              <option value="sink">sink</option>
            </select>
            <span className="text-ink-500">@</span>
            <div className="w-40"><CoordCell value={ep.position} onChange={(v) => patchEp(ep.id, { position: v })} /></div>
            <span className="text-ink-600 font-mono text-[10px] ml-1">{ep.id}</span>
            <button type="button" onClick={() => commit({ ...route, endpoints: route.endpoints.filter((e) => e.id !== ep.id) })} className="p-0.5 text-ink-500 hover:text-red-400 ml-auto"><Trash2 size={12} /></button>
          </div>
        ))}
      </Section>

      {/* Computed */}
      <Section title="Computed">
        <div className="flex gap-6 text-[12px]">
          {[
            ['Total length', `${(lengthMm / 1000).toFixed(3)} m`],
            ['Pressure drop', route.kind === 'conduit' ? 'N/A (electrical)' : `${pressurePa.toFixed(2)} Pa`],
          ].map(([label, value]) => (
            <div key={label} className="flex flex-col gap-0.5">
              <span className="text-[10px] text-ink-500 uppercase tracking-wide">{label}</span>
              <span className="font-mono text-kerf-300 text-[13px]">{value}</span>
            </div>
          ))}
        </div>
      </Section>

      {/* Auto-route */}
      <Section title="Auto-route">
        <div className="flex items-center gap-2 flex-wrap text-[12px]">
          <label className="text-ink-500">From</label>
          <select className={sCls} value={autoStart} onChange={(e) => setAutoStart(e.target.value)}>
            <option value="">— pick —</option>
            {route.endpoints.map((ep) => <option key={ep.id} value={ep.id}>{ep.id} ({ep.kind})</option>)}
          </select>
          <label className="text-ink-500">to</label>
          <select className={sCls} value={autoEnd} onChange={(e) => setAutoEnd(e.target.value)}>
            <option value="">— pick —</option>
            {route.endpoints.map((ep) => <option key={ep.id} value={ep.id}>{ep.id} ({ep.kind})</option>)}
          </select>
          <button type="button" onClick={runAutoRoute}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-kerf-300/10 border border-kerf-300/30 text-kerf-200 hover:bg-kerf-300/20 text-[11px]">
            <Zap size={11} />Auto-route
          </button>
        </div>
        {autoWarn && <p className="text-amber-400 text-[11px] mt-1">{autoWarn}</p>}
      </Section>
    </div>
  )
}
