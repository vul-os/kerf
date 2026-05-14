// SheetEditor.jsx — Editor for .sheet.json print-ready layout files.

import { useState, useEffect, useRef, useCallback } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { VALID_SIZES, VALID_ORIENTATIONS, SHEET_SIZES_MM, validateSheet, addViewport, removeViewport } from '../lib/sheet.js'

const DEBOUNCE_MS = 250

function parse(content) {
  try { return JSON.parse(content || '{}') } catch { return {} }
}

// SVG preview of the sheet — outline + labeled viewport rectangles.
function SheetPreview({ sheet }) {
  const size = SHEET_SIZES_MM[sheet.size] || [297, 420]
  const [w, h] = sheet.orientation === 'landscape' ? [size[1], size[0]] : [size[0], size[1]]
  const SVG_W = 360
  const SVG_H = Math.round((SVG_W / w) * h)
  const scale = SVG_W / w

  return (
    <svg
      width={SVG_W}
      height={SVG_H}
      viewBox={`0 0 ${SVG_W} ${SVG_H}`}
      className="border border-ink-700 rounded bg-white/5 block mx-auto"
    >
      {/* Sheet border */}
      <rect x={0} y={0} width={SVG_W} height={SVG_H} fill="#111827" stroke="#374151" strokeWidth={1} />
      {/* Title block strip */}
      <rect x={0} y={SVG_H - 28} width={SVG_W} height={28} fill="#1f2937" stroke="#374151" strokeWidth={0.5} />
      <text x={6} y={SVG_H - 16} fill="#9ca3af" fontSize={7} fontFamily="monospace">
        {sheet.titleblock?.project_name || 'Project'}
      </text>
      <text x={6} y={SVG_H - 7} fill="#6b7280" fontSize={6} fontFamily="monospace">
        {sheet.name || 'Sheet'} · {sheet.sheet_number || ''} · {sheet.titleblock?.drawn_by || ''}
      </text>

      {/* Viewports */}
      {(sheet.viewports || []).map((vp) => {
        const [vx, vy] = vp.position || [10, 10]
        const vpW = 80
        const vpH = 60
        const sx = vx * scale
        const sy = vy * scale
        return (
          <g key={vp.id}>
            <rect
              x={sx}
              y={sy}
              width={vpW}
              height={vpH}
              fill="none"
              stroke="#4b9ef4"
              strokeWidth={1}
              strokeDasharray="3 2"
            />
            <text x={sx + 4} y={sy + 12} fill="#93c5fd" fontSize={6} fontFamily="monospace">
              {vp.title || vp.view_file_id || 'view'}
            </text>
            <text x={sx + 4} y={sy + 21} fill="#6b7280" fontSize={5} fontFamily="monospace">
              1:{Math.round(1 / (vp.scale || 0.02))}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

export default function SheetEditor({ content, fileName, onContentChange }) {
  const [sheet, setSheet] = useState(() => parse(content))
  const lastEmittedRef = useRef(content)
  const timerRef = useRef(null)

  useEffect(() => {
    if (content !== lastEmittedRef.current) {
      setSheet(parse(content))
    }
  }, [content])

  const emit = useCallback((next) => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => {
      const s = JSON.stringify(next, null, 2)
      lastEmittedRef.current = s
      onContentChange?.(s)
    }, DEBOUNCE_MS)
  }, [onContentChange])
  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current) }, [])

  function patch(delta) {
    setSheet((s) => {
      const next = { ...s, ...delta }
      emit(next)
      return next
    })
  }

  function patchTitleblock(delta) {
    patch({ titleblock: { ...(sheet.titleblock || {}), ...delta } })
  }

  // ── Viewports ────────────────────────────────────────────────────────────────

  function handleAddViewport() {
    const next = addViewport(sheet, '', [10, 10], 0.02, '')
    emit(next)
    setSheet(next)
  }

  function handleRemoveViewport(id) {
    const next = removeViewport(sheet, id)
    emit(next)
    setSheet(next)
  }

  function patchViewport(id, delta) {
    setSheet((s) => {
      const viewports = (s.viewports || []).map((vp) => vp.id === id ? { ...vp, ...delta } : vp)
      const next = { ...s, viewports }
      emit(next)
      return next
    })
  }

  const { errors } = validateSheet(sheet)
  const viewports = sheet.viewports || []
  const revisions = sheet.revisions || []

  return (
    <div className="h-full flex flex-col bg-ink-950 text-ink-100 overflow-auto">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-ink-800 flex-shrink-0 flex-wrap gap-y-2">
        <input
          type="text"
          value={sheet.name || ''}
          onChange={(e) => patch({ name: e.target.value })}
          placeholder="Sheet name"
          className="w-44 bg-ink-900 border border-ink-800 rounded px-2 py-1 text-sm text-ink-100 outline-none focus:border-kerf-300/60"
        />
        <input
          type="text"
          value={sheet.sheet_number || ''}
          onChange={(e) => patch({ sheet_number: e.target.value })}
          placeholder="A101"
          className="w-20 bg-ink-900 border border-ink-800 rounded px-2 py-1 text-sm font-mono text-ink-100 outline-none focus:border-kerf-300/60"
        />
        <select
          value={sheet.size || 'A1'}
          onChange={(e) => patch({ size: e.target.value })}
          className="bg-ink-900 border border-ink-800 rounded px-2 py-1 text-xs text-ink-100 outline-none focus:border-kerf-300/60"
        >
          {VALID_SIZES.map((s) => <option key={s}>{s}</option>)}
        </select>
        <select
          value={sheet.orientation || 'landscape'}
          onChange={(e) => patch({ orientation: e.target.value })}
          className="bg-ink-900 border border-ink-800 rounded px-2 py-1 text-xs text-ink-100 outline-none focus:border-kerf-300/60"
        >
          {VALID_ORIENTATIONS.map((o) => <option key={o}>{o}</option>)}
        </select>
        <span className="text-[10px] text-ink-500 font-mono truncate max-w-[140px]">{fileName}</span>
      </div>

      {errors.length > 0 && (
        <div className="px-4 py-2 text-[11px] text-amber-400 border-b border-amber-900/40 bg-amber-950/20">
          {errors[0]}
        </div>
      )}

      <div className="flex-1 overflow-auto px-4 py-4 space-y-6">
        {/* Title block */}
        <section>
          <span className="text-[11px] text-ink-400 uppercase tracking-wider font-semibold block mb-2">Title block</span>
          <div className="grid grid-cols-2 gap-2">
            {[
              ['project_name', 'Project name'],
              ['issue_date', 'Issue date'],
              ['drawn_by', 'Drawn by'],
              ['scale', 'Scale'],
            ].map(([key, label]) => (
              <label key={key} className="flex flex-col gap-0.5">
                <span className="text-[10px] text-ink-500">{label}</span>
                <input
                  value={sheet.titleblock?.[key] || ''}
                  onChange={(e) => patchTitleblock({ [key]: e.target.value })}
                  className="bg-ink-900 border border-ink-800 rounded px-2 py-1 text-[11px] text-ink-100 outline-none focus:border-kerf-300/60"
                />
              </label>
            ))}
          </div>
        </section>

        {/* Viewports */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] text-ink-400 uppercase tracking-wider font-semibold">Viewports</span>
            <button
              type="button"
              onClick={handleAddViewport}
              className="inline-flex items-center gap-1 px-2 py-1 rounded bg-kerf-300/10 border border-kerf-300/30 text-kerf-200 hover:bg-kerf-300/20 text-[11px]"
            >
              <Plus size={11} /> Add viewport
            </button>
          </div>
          {viewports.length === 0 ? (
            <p className="text-[11px] text-ink-500 italic">No viewports.</p>
          ) : (
            <ul className="space-y-2">
              {viewports.map((vp) => (
                <li key={vp.id} className="bg-ink-900 border border-ink-800 rounded px-3 py-2 space-y-1.5">
                  <div className="flex items-center gap-2">
                    <input
                      value={vp.view_file_id || ''}
                      onChange={(e) => patchViewport(vp.id, { view_file_id: e.target.value })}
                      placeholder="view-file-id"
                      className="flex-1 bg-ink-950 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] font-mono text-ink-100 outline-none focus:border-kerf-300/60"
                    />
                    <input
                      value={vp.title || ''}
                      onChange={(e) => patchViewport(vp.id, { title: e.target.value })}
                      placeholder="title"
                      className="w-28 bg-ink-950 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] text-ink-100 outline-none focus:border-kerf-300/60"
                    />
                    <button
                      type="button"
                      onClick={() => handleRemoveViewport(vp.id)}
                      className="p-1 rounded hover:bg-red-900/30 text-ink-500 hover:text-red-300"
                      title="Remove viewport"
                    >
                      <Trash2 size={11} />
                    </button>
                  </div>
                  <div className="flex items-center gap-2 text-[10px]">
                    <span className="text-ink-500">Pos</span>
                    {[0, 1].map((axis) => (
                      <input
                        key={axis}
                        type="number"
                        value={vp.position?.[axis] ?? 0}
                        onChange={(e) => {
                          const pos = [...(vp.position || [0,0])]
                          pos[axis] = Number(e.target.value)
                          patchViewport(vp.id, { position: pos })
                        }}
                        className="w-16 bg-ink-950 border border-ink-800 rounded px-1.5 py-0.5 font-mono text-ink-100 outline-none focus:border-kerf-300/60"
                      />
                    ))}
                    <span className="text-ink-500 ml-2">Scale 1:</span>
                    <input
                      type="number"
                      value={vp.scale ? Math.round(1 / vp.scale) : 50}
                      onChange={(e) => patchViewport(vp.id, { scale: 1 / (Number(e.target.value) || 50) })}
                      className="w-16 bg-ink-950 border border-ink-800 rounded px-1.5 py-0.5 font-mono text-ink-100 outline-none focus:border-kerf-300/60"
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Revisions (read from revisions array, read-only display for v1) */}
        {revisions.length > 0 && (
          <section>
            <span className="text-[11px] text-ink-400 uppercase tracking-wider font-semibold block mb-2">Revisions</span>
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-[10px] text-ink-500 uppercase tracking-wider border-b border-ink-800">
                  <th className="text-left pb-1 pr-2 font-medium">Rev</th>
                  <th className="text-left pb-1 pr-2 font-medium">Date</th>
                  <th className="text-left pb-1 pr-2 font-medium">Description</th>
                  <th className="text-left pb-1 font-medium">By</th>
                </tr>
              </thead>
              <tbody>
                {revisions.map((r, i) => (
                  <tr key={i} className="border-b border-ink-900">
                    <td className="py-1 pr-2 font-mono text-ink-300">{r.revision || r.rev || String.fromCharCode(65 + i)}</td>
                    <td className="py-1 pr-2 text-ink-400">{r.date || ''}</td>
                    <td className="py-1 pr-2 text-ink-300">{r.description || r.note || ''}</td>
                    <td className="py-1 text-ink-400">{r.drawn_by || r.by || ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        {/* SVG preview */}
        <section>
          <span className="text-[11px] text-ink-400 uppercase tracking-wider font-semibold block mb-2">Preview</span>
          <SheetPreview sheet={sheet} />
        </section>
      </div>
    </div>
  )
}
