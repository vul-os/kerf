// RailingView.jsx — Viewer/editor for .railing.json files.
import { useState, useEffect, useRef, useCallback } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import {
  defaultRailing, validateRailing,
  computePostPositions, computeBalusterPositions, railingFromSketch,
} from '../lib/railings.js'

// ── Helpers ────────────────────────────────────────────────────────────────────
function parse(c) { try { return JSON.parse(c) } catch { return null } }

const iCls = 'w-full bg-ink-950 border border-ink-700 rounded px-2 py-0.5 text-[12px] text-ink-200 focus:outline-none focus:border-kerf-300/60'
const sCls = 'bg-ink-950 border border-ink-700 rounded px-1.5 py-0.5 text-[11px] text-ink-200 focus:outline-none focus:border-kerf-300/60'
const btnCls = 'inline-flex items-center gap-1 text-[11px] text-kerf-300 hover:text-kerf-200'

const PROFILES = ['round', 'square', 'flat']

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
function RailingSVG({ railing }) {
  const path = railing.path || []
  const h = railing.height_mm || 1000
  if (path.length < 2) return <Empty>Add at least 2 path points to preview.</Empty>

  const W = 260
  const H = 120
  const margin = 10

  const xs = path.map((p) => p.x || 0)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const spanX = maxX - minX || 1

  const scale = (W - margin * 2) / spanX

  function toSvg(p, elevated = false) {
    const x = margin + (p.x - minX) * scale
    const y = elevated ? (margin + 10) : (H - margin)
    return [x.toFixed(1), y.toFixed(1)]
  }

  const posts = computePostPositions(path, railing.posts?.spacing_mm || 1200)

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto rounded border border-ink-800 bg-ink-950">
      {/* Ground line */}
      <line x1={margin} y1={H - margin} x2={W - margin} y2={H - margin} stroke="#334155" strokeWidth="1" />
      {/* Top rail */}
      <polyline
        points={path.map((p) => toSvg(p, true).join(',')).join(' ')}
        fill="none" stroke="#5da9ff" strokeWidth="1.5" />
      {/* Posts */}
      {posts.map((p, i) => {
        const [x] = toSvg(p)
        return <line key={i} x1={x} y1={H - margin} x2={x} y2={margin + 10} stroke="#64748b" strokeWidth="1" />
      })}
    </svg>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────
export default function RailingView({ content, fileName, onContentChange }) {
  const [railing, setRailing] = useState(() =>
    parse(content) || defaultRailing({ path: [{ x: 0, y: 0, z: 0 }, { x: 3000, y: 0, z: 0 }] })
  )
  const debRef = useRef(null)

  useEffect(() => { const n = parse(content); if (n) setRailing(n) }, [content])

  const commit = useCallback((next) => {
    setRailing(next)
    if (debRef.current) clearTimeout(debRef.current)
    debRef.current = setTimeout(() => onContentChange?.(JSON.stringify(next, null, 2)), 250)
  }, [onContentChange])

  const patch = (u) => commit({ ...railing, ...u })
  const patchTopRail = (u) => patch({ top_rail: { ...railing.top_rail, ...u } })
  const patchPosts = (u) => patch({ posts: { ...railing.posts, ...u } })
  const patchBalusters = (u) => patch({ balusters: { ...railing.balusters, ...u } })

  const path = railing.path || []
  const postPositions = computePostPositions(path, railing.posts?.spacing_mm || 1200)
  const balPositions = computeBalusterPositions(path, railing.balusters?.spacing_mm || 120)
  const validation = validateRailing(railing)

  function fromStair() {
    const fileId = prompt('Stair file ID (for reference):')
    const side = prompt('Side (left / right / both):', 'right')
    if (!fileId || !side) return
    // Can't actually load the stair file here; just inform user.
    alert(`Wire railingFromStair() in your script using stair file "${fileId}", side "${side}".`)
  }

  function addPoint() {
    const last = path[path.length - 1] || { x: 0, y: 0, z: 0 }
    commit({ ...railing, path: [...path, { x: last.x + 1000, y: last.y, z: last.z }] })
  }

  function updatePoint(idx, raw) {
    const parts = raw.split(',').map(Number)
    if (parts.length !== 3 || parts.some(Number.isNaN)) return
    const next = path.map((p, i) => i === idx ? { x: parts[0], y: parts[1], z: parts[2] } : p)
    commit({ ...railing, path: next })
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto bg-ink-950 text-ink-100 p-4 space-y-5">
      {/* Header */}
      <Section title="Railing">
        <div className="grid grid-cols-2 gap-3 text-[12px]">
          <div className="flex flex-col gap-1 col-span-2">
            <span className="text-[10px] text-ink-500 uppercase tracking-wide">Name</span>
            <input className={iCls} value={railing.name || ''} placeholder="Railing name"
              onChange={(e) => patch({ name: e.target.value })} />
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-[10px] text-ink-500 uppercase tracking-wide">Height (mm)</span>
            <input className={iCls} type="number" value={railing.height_mm ?? 1000}
              onChange={(e) => patch({ height_mm: parseFloat(e.target.value) || 1000 })} />
          </div>
        </div>
      </Section>

      {/* Top rail */}
      <Section title="Top rail">
        <div className="grid grid-cols-3 gap-3 text-[12px]">
          {[
            ['Profile', (
              <select className={sCls} value={railing.top_rail?.profile || 'round'}
                onChange={(e) => patchTopRail({ profile: e.target.value })}>
                {PROFILES.map((p) => <option key={p}>{p}</option>)}
              </select>
            )],
            ['Size (mm)', <input className={iCls} type="number" value={railing.top_rail?.size_mm ?? 50} onChange={(e) => patchTopRail({ size_mm: parseFloat(e.target.value) || 50 })} />],
            ['Offset (mm)', <input className={iCls} type="number" value={railing.top_rail?.offset_mm ?? 0} onChange={(e) => patchTopRail({ offset_mm: parseFloat(e.target.value) || 0 })} />],
          ].map(([label, field]) => (
            <div key={label} className="flex flex-col gap-1">
              <span className="text-[10px] text-ink-500 uppercase tracking-wide">{label}</span>
              {field}
            </div>
          ))}
        </div>
      </Section>

      {/* Posts */}
      <Section title="Posts">
        <div className="grid grid-cols-2 gap-3 text-[12px]">
          {[
            ['Spacing (mm)', <input className={iCls} type="number" value={railing.posts?.spacing_mm ?? 1200} onChange={(e) => patchPosts({ spacing_mm: parseFloat(e.target.value) || 1200 })} />],
            ['Profile', (
              <select className={sCls} value={railing.posts?.profile || 'round'} onChange={(e) => patchPosts({ profile: e.target.value })}>
                {PROFILES.map((p) => <option key={p}>{p}</option>)}
              </select>
            )],
            ['Size (mm)', <input className={iCls} type="number" value={railing.posts?.size_mm ?? 40} onChange={(e) => patchPosts({ size_mm: parseFloat(e.target.value) || 40 })} />],
            ['Height (mm)', <input className={iCls} type="number" value={railing.posts?.height_mm ?? 1000} onChange={(e) => patchPosts({ height_mm: parseFloat(e.target.value) || 1000 })} />],
          ].map(([label, field]) => (
            <div key={label} className="flex flex-col gap-1">
              <span className="text-[10px] text-ink-500 uppercase tracking-wide">{label}</span>
              {field}
            </div>
          ))}
        </div>
      </Section>

      {/* Balusters */}
      <Section title="Balusters">
        <div className="grid grid-cols-2 gap-3 text-[12px]">
          {[
            ['Spacing (mm)', <input className={iCls} type="number" value={railing.balusters?.spacing_mm ?? 120} onChange={(e) => patchBalusters({ spacing_mm: parseFloat(e.target.value) || 120 })} />],
            ['Profile', (
              <select className={sCls} value={railing.balusters?.profile || 'round'} onChange={(e) => patchBalusters({ profile: e.target.value })}>
                {PROFILES.map((p) => <option key={p}>{p}</option>)}
              </select>
            )],
            ['Size (mm)', <input className={iCls} type="number" value={railing.balusters?.size_mm ?? 14} onChange={(e) => patchBalusters({ size_mm: parseFloat(e.target.value) || 14 })} />],
            ['Height (mm)', <input className={iCls} type="number" value={railing.balusters?.height_mm ?? 900} onChange={(e) => patchBalusters({ height_mm: parseFloat(e.target.value) || 900 })} />],
          ].map(([label, field]) => (
            <div key={label} className="flex flex-col gap-1">
              <span className="text-[10px] text-ink-500 uppercase tracking-wide">{label}</span>
              {field}
            </div>
          ))}
        </div>
      </Section>

      {/* Path */}
      <Section title="Path" action={
        <div className="flex gap-2">
          <button type="button" className={btnCls} onClick={fromStair}>From stair…</button>
          <button type="button" className={btnCls} onClick={addPoint}><Plus size={12} />Add point</button>
        </div>
      }>
        {path.length === 0 ? <Empty>No path points. Add at least 2.</Empty> : path.map((pt, idx) => (
          <div key={idx} className="flex items-center gap-2 py-1 border-b border-ink-850 text-[11px]">
            <span className="text-ink-500 w-5 flex-shrink-0">{idx}</span>
            <input className={iCls} defaultValue={`${pt.x}, ${pt.y}, ${pt.z}`}
              onBlur={(e) => updatePoint(idx, e.target.value)} />
            <button type="button" onClick={() => commit({ ...railing, path: path.filter((_, i) => i !== idx) })}
              className="p-0.5 text-ink-500 hover:text-red-400 flex-shrink-0"><Trash2 size={12} /></button>
          </div>
        ))}
      </Section>

      {/* Computed */}
      <Section title="Computed">
        <div className="flex gap-6 flex-wrap">
          <Stat label="Posts" value={postPositions.length} />
          <Stat label="Balusters" value={balPositions.length} />
        </div>
        {!validation.ok && (
          <ul className="mt-2 space-y-0.5">
            {validation.errors.map((e) => <li key={e} className="text-[11px] text-amber-400">{e}</li>)}
          </ul>
        )}
      </Section>

      {/* Preview */}
      <Section title="Preview (side view)">
        <RailingSVG railing={railing} />
      </Section>
    </div>
  )
}
