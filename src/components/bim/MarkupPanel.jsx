/**
 * MarkupPanel.jsx — Markup / Redline tool for drawings, PDFs, and 3D views.
 *
 * Layout:
 *   Toolbar       — shape picker, colour, thickness, layer select
 *   SVG canvas    — draw annotations over the current drawing/page
 *   Layers panel  — visibility toggles per layer
 *   Annotation list — searchable, sortable by author / date
 *   Export bar    — PDF overlay, SVG, summary report
 *
 * Route: /markup  (lazy-loaded via App.jsx)
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Circle, Square, ArrowRight, Pen, Type, Highlighter,
  Stamp, Eye, EyeOff, Download, FileText, Search,
  ChevronUp, ChevronDown, Trash2, Plus, Layers,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SHAPES = [
  { id: 'circle',    label: 'Circle',    Icon: Circle },
  { id: 'rectangle', label: 'Rectangle', Icon: Square },
  { id: 'arrow',     label: 'Arrow',     Icon: ArrowRight },
  { id: 'freehand',  label: 'Freehand',  Icon: Pen },
  { id: 'text',      label: 'Text',      Icon: Type },
  { id: 'highlight', label: 'Highlight', Icon: Highlighter },
  { id: 'stamp',     label: 'Stamp',     Icon: Stamp },
]

const DEFAULT_LAYER = 'Review 1'
const PALETTE = ['#ef4444', '#f97316', '#eab308', '#22c55e', '#3b82f6', '#8b5cf6', '#ec4899']

function hexToRgb(hex) {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return [r, g, b]
}

function rgbToHex([r, g, b]) {
  return '#' + [r, g, b].map(v => v.toString(16).padStart(2, '0')).join('')
}

function newId() {
  return ([1e7] + -1e3 + -4e3 + -8e3 + -1e11).replace(/[018]/g, c =>
    (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16),
  )
}

// ---------------------------------------------------------------------------
// Annotation rendering helpers
// ---------------------------------------------------------------------------

function AnnotationShape({ ann, selected, onClick }) {
  const stroke = rgbToHex(ann.color_rgb)
  const sw = ann.thickness_mm
  const pts = ann.xy_mm

  const commonProps = {
    stroke,
    strokeWidth: sw,
    fill: ann.fill_rgba
      ? `rgba(${ann.fill_rgba[0]},${ann.fill_rgba[1]},${ann.fill_rgba[2]},${ann.fill_rgba[3] / 255})`
      : 'none',
    cursor: 'pointer',
    onClick,
    filter: selected ? 'drop-shadow(0 0 3px white)' : undefined,
  }

  if (ann.shape === 'circle' && pts.length >= 2) {
    const [cx, cy] = pts[0]
    const r = Math.hypot(pts[1][0] - cx, pts[1][1] - cy)
    return <circle cx={cx} cy={cy} r={Math.max(r, 2)} {...commonProps} />
  }

  if (ann.shape === 'circle' && pts.length === 1) {
    const [cx, cy] = pts[0]
    return <circle cx={cx} cy={cy} r={5} {...commonProps} />
  }

  if (ann.shape === 'rectangle' && pts.length >= 2) {
    const [x1, y1] = pts[0]
    const [x2, y2] = pts[1]
    return (
      <rect
        x={Math.min(x1, x2)} y={Math.min(y1, y2)}
        width={Math.abs(x2 - x1)} height={Math.abs(y2 - y1)}
        {...commonProps}
      />
    )
  }

  if (ann.shape === 'arrow' && pts.length >= 2) {
    const [x1, y1] = pts[0]
    const [x2, y2] = pts[pts.length - 1]
    const angle = Math.atan2(y2 - y1, x2 - x1)
    const size = Math.max(sw * 6, 6)
    const ax1 = x2 - size * Math.cos(angle - Math.PI / 6)
    const ay1 = y2 - size * Math.sin(angle - Math.PI / 6)
    const ax2 = x2 - size * Math.cos(angle + Math.PI / 6)
    const ay2 = y2 - size * Math.sin(angle + Math.PI / 6)
    return (
      <g onClick={onClick} cursor="pointer">
        <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={stroke} strokeWidth={sw} />
        <polygon points={`${x2},${y2} ${ax1.toFixed(1)},${ay1.toFixed(1)} ${ax2.toFixed(1)},${ay2.toFixed(1)}`} fill={stroke} />
      </g>
    )
  }

  if ((ann.shape === 'freehand' || ann.shape === 'highlight') && pts.length >= 2) {
    const pointStr = pts.map(([x, y]) => `${x},${y}`).join(' ')
    return (
      <polyline
        points={pointStr}
        stroke={stroke}
        strokeWidth={ann.shape === 'highlight' ? sw * 8 : sw}
        strokeOpacity={ann.shape === 'highlight' ? 0.4 : 1}
        fill="none"
        cursor="pointer"
        onClick={onClick}
      />
    )
  }

  if (ann.shape === 'text' && pts.length >= 1) {
    return (
      <text
        x={pts[0][0]} y={pts[0][1]}
        fill={stroke}
        fontSize="12"
        fontFamily="sans-serif"
        cursor="pointer"
        onClick={onClick}
      >
        {ann.text_content || 'Text'}
      </text>
    )
  }

  if (ann.shape === 'stamp' && pts.length >= 1) {
    const [x, y] = pts[0]
    return (
      <g onClick={onClick} cursor="pointer">
        <rect x={x} y={y - 12} width={60} height={18} stroke={stroke} strokeWidth={sw} fill="none" />
        <text x={x + 30} y={y} fill={stroke} fontSize="10" textAnchor="middle" fontFamily="sans-serif" fontWeight="bold">
          {ann.text_content || 'STAMP'}
        </text>
      </g>
    )
  }

  return null
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function MarkupPanel() {
  const [activeShape, setActiveShape] = useState('circle')
  const [activeColor, setActiveColor] = useState('#ef4444')
  const [thickness, setThickness] = useState(1.5)
  const [activeLayer, setActiveLayer] = useState(DEFAULT_LAYER)
  const [layers, setLayers] = useState([
    { name: DEFAULT_LAYER, color_rgb: [239, 68, 68], visible: true, annotations: [] },
  ])
  const [drawing, setDrawing] = useState(false)
  const [currentPts, setCurrentPts] = useState([])
  const [selectedGuid, setSelectedGuid] = useState(null)
  const [search, setSearch] = useState('')
  const [sortField, setSortField] = useState('created_at_iso')
  const [sortDir, setSortDir] = useState('desc')
  const [textInput, setTextInput] = useState('')
  const [pendingTextPt, setPendingTextPt] = useState(null)
  const svgRef = useRef(null)

  // ── Layer helpers ────────────────────────────────────────────────────────

  const getCurrentLayer = useCallback(
    () => layers.find((l) => l.name === activeLayer),
    [layers, activeLayer],
  )

  const addLayer = useCallback(() => {
    const name = `Review ${layers.length + 1}`
    setLayers((prev) => [
      ...prev,
      { name, color_rgb: hexToRgb(PALETTE[layers.length % PALETTE.length]), visible: true, annotations: [] },
    ])
    setActiveLayer(name)
  }, [layers])

  const toggleLayerVisibility = useCallback((name) => {
    setLayers((prev) =>
      prev.map((l) => (l.name === name ? { ...l, visible: !l.visible } : l)),
    )
  }, [])

  // ── SVG canvas interaction ───────────────────────────────────────────────

  function svgCoords(evt) {
    const svg = svgRef.current
    if (!svg) return [0, 0]
    const rect = svg.getBoundingClientRect()
    return [evt.clientX - rect.left, evt.clientY - rect.top]
  }

  function handleMouseDown(evt) {
    if (evt.button !== 0) return
    const pt = svgCoords(evt)

    if (activeShape === 'text') {
      // Drop a text placement marker — prompt user for content
      setPendingTextPt(pt)
      return
    }

    setDrawing(true)
    setCurrentPts([pt])
  }

  function handleMouseMove(evt) {
    if (!drawing) return
    const pt = svgCoords(evt)
    if (activeShape === 'freehand' || activeShape === 'highlight') {
      setCurrentPts((prev) => [...prev, pt])
    } else {
      setCurrentPts((prev) => [prev[0], pt])
    }
  }

  function handleMouseUp(evt) {
    if (!drawing) return
    setDrawing(false)
    const pt = svgCoords(evt)

    const pts = activeShape === 'freehand' || activeShape === 'highlight'
      ? [...currentPts, pt]
      : [currentPts[0], pt]

    commitAnnotation(pts, '')
    setCurrentPts([])
  }

  function commitAnnotation(pts, textContent) {
    const ann = {
      guid: newId(),
      shape: activeShape,
      xy_mm: pts,
      color_rgb: hexToRgb(activeColor),
      thickness_mm: thickness,
      fill_rgba: null,
      text_content: textContent,
      author: 'me',
      created_at_iso: new Date().toISOString(),
      page_or_view_id: '0',
    }

    setLayers((prev) =>
      prev.map((l) =>
        l.name === activeLayer
          ? { ...l, annotations: [...l.annotations, ann] }
          : l,
      ),
    )
    setSelectedGuid(ann.guid)
  }

  function confirmText() {
    if (!pendingTextPt) return
    commitAnnotation([pendingTextPt], textInput || 'Text')
    setPendingTextPt(null)
    setTextInput('')
  }

  function deleteSelected() {
    if (!selectedGuid) return
    setLayers((prev) =>
      prev.map((l) => ({
        ...l,
        annotations: l.annotations.filter((a) => a.guid !== selectedGuid),
      })),
    )
    setSelectedGuid(null)
  }

  // ── Annotation list ──────────────────────────────────────────────────────

  const allAnnotations = layers.flatMap((l) =>
    l.annotations.map((a) => ({ ...a, layerName: l.name })),
  )

  const filtered = allAnnotations
    .filter(
      (a) =>
        a.author.toLowerCase().includes(search.toLowerCase()) ||
        a.text_content.toLowerCase().includes(search.toLowerCase()) ||
        a.shape.toLowerCase().includes(search.toLowerCase()),
    )
    .sort((a, b) => {
      const va = a[sortField] ?? ''
      const vb = b[sortField] ?? ''
      const cmp = va < vb ? -1 : va > vb ? 1 : 0
      return sortDir === 'asc' ? cmp : -cmp
    })

  function toggleSort(field) {
    if (sortField === field) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortField(field)
      setSortDir('asc')
    }
  }

  // ── Export helpers ───────────────────────────────────────────────────────

  function exportSvg() {
    // Build SVG string from current session
    const ns = 'http://www.w3.org/2000/svg'
    const svgEl = svgRef.current
    if (!svgEl) return
    const serialized = new XMLSerializer().serializeToString(svgEl)
    const blob = new Blob([serialized], { type: 'image/svg+xml' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'markup-overlay.svg'
    a.click()
    URL.revokeObjectURL(url)
  }

  function exportSummary() {
    const rows = allAnnotations.map((a) =>
      `${a.shape}\t${a.author}\t${a.created_at_iso}\t${a.text_content}`,
    )
    const csv = ['Shape\tAuthor\tDate\tNote', ...rows].join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'markup-summary.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  // ── Render ───────────────────────────────────────────────────────────────

  const SortIcon = ({ field }) =>
    sortField === field ? (
      sortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />
    ) : null

  return (
    <div className="flex h-full bg-zinc-950 text-zinc-100 overflow-hidden">

      {/* ── Left sidebar ───────────────────────────────────────────────── */}
      <div className="w-64 flex flex-col border-r border-zinc-800 shrink-0">

        {/* Shape toolbar */}
        <div className="p-3 border-b border-zinc-800">
          <p className="text-xs font-semibold text-zinc-400 mb-2 uppercase tracking-wider">Shape</p>
          <div className="grid grid-cols-4 gap-1">
            {SHAPES.map(({ id, label, Icon }) => (
              <button
                key={id}
                title={label}
                onClick={() => setActiveShape(id)}
                className={`p-2 rounded flex items-center justify-center transition-colors ${
                  activeShape === id
                    ? 'bg-blue-600 text-white'
                    : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-zinc-100'
                }`}
              >
                <Icon size={14} />
              </button>
            ))}
          </div>
        </div>

        {/* Colour picker */}
        <div className="p-3 border-b border-zinc-800">
          <p className="text-xs font-semibold text-zinc-400 mb-2 uppercase tracking-wider">Colour</p>
          <div className="flex flex-wrap gap-1 mb-2">
            {PALETTE.map((hex) => (
              <button
                key={hex}
                onClick={() => setActiveColor(hex)}
                style={{ background: hex }}
                className={`w-6 h-6 rounded-full transition-transform ${
                  activeColor === hex ? 'ring-2 ring-white scale-110' : 'hover:scale-105'
                }`}
              />
            ))}
          </div>
          <input
            type="color"
            value={activeColor}
            onChange={(e) => setActiveColor(e.target.value)}
            className="w-full h-7 rounded cursor-pointer bg-transparent border border-zinc-700"
          />
        </div>

        {/* Thickness */}
        <div className="p-3 border-b border-zinc-800">
          <p className="text-xs font-semibold text-zinc-400 mb-2 uppercase tracking-wider">
            Thickness — {thickness.toFixed(1)} px
          </p>
          <input
            type="range"
            min={0.5}
            max={8}
            step={0.5}
            value={thickness}
            onChange={(e) => setThickness(Number(e.target.value))}
            className="w-full accent-blue-500"
          />
        </div>

        {/* Layers */}
        <div className="p-3 flex-1 overflow-y-auto">
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider flex items-center gap-1">
              <Layers size={12} /> Layers
            </p>
            <button
              onClick={addLayer}
              className="p-1 rounded text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800 transition-colors"
              title="Add layer"
            >
              <Plus size={12} />
            </button>
          </div>
          <div className="space-y-1">
            {layers.map((l) => (
              <div
                key={l.name}
                onClick={() => setActiveLayer(l.name)}
                className={`flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer transition-colors ${
                  activeLayer === l.name
                    ? 'bg-blue-600/20 border border-blue-600/40 text-blue-300'
                    : 'hover:bg-zinc-800 text-zinc-300'
                }`}
              >
                <div
                  className="w-3 h-3 rounded-full shrink-0"
                  style={{ background: rgbToHex(l.color_rgb) }}
                />
                <span className="text-xs flex-1 truncate">{l.name}</span>
                <span className="text-xs text-zinc-500">{l.annotations.length}</span>
                <button
                  onClick={(e) => { e.stopPropagation(); toggleLayerVisibility(l.name) }}
                  className="text-zinc-500 hover:text-zinc-200 transition-colors"
                >
                  {l.visible ? <Eye size={12} /> : <EyeOff size={12} />}
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* Export buttons */}
        <div className="p-3 border-t border-zinc-800 space-y-1">
          <button
            onClick={exportSvg}
            className="w-full flex items-center gap-2 px-3 py-2 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs transition-colors"
          >
            <Download size={12} /> SVG overlay
          </button>
          <button
            onClick={exportSummary}
            className="w-full flex items-center gap-2 px-3 py-2 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs transition-colors"
          >
            <FileText size={12} /> Summary CSV
          </button>
        </div>
      </div>

      {/* ── Canvas area ────────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col overflow-hidden">

        {/* Text input overlay when text tool is pending */}
        {pendingTextPt && (
          <div className="absolute z-50 inset-0 flex items-center justify-center bg-zinc-950/70">
            <div className="bg-zinc-900 border border-zinc-700 rounded-xl p-5 w-80 shadow-2xl">
              <p className="text-sm font-semibold text-zinc-200 mb-3">Enter annotation text</p>
              <input
                autoFocus
                value={textInput}
                onChange={(e) => setTextInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && confirmText()}
                className="w-full bg-zinc-800 border border-zinc-600 rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:border-blue-500 mb-3"
                placeholder="Note text..."
              />
              <div className="flex gap-2">
                <button
                  onClick={confirmText}
                  className="flex-1 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium py-2 rounded-lg transition-colors"
                >
                  Place
                </button>
                <button
                  onClick={() => { setPendingTextPt(null); setTextInput('') }}
                  className="flex-1 bg-zinc-700 hover:bg-zinc-600 text-zinc-300 text-sm py-2 rounded-lg transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Drawing canvas */}
        <div className="flex-1 relative overflow-hidden bg-zinc-900 rounded-none">
          {/* Background grid to simulate a drawing sheet */}
          <svg
            ref={svgRef}
            className="absolute inset-0 w-full h-full"
            style={{ cursor: activeShape === 'text' ? 'text' : 'crosshair' }}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
          >
            {/* Sheet grid */}
            <defs>
              <pattern id="grid-sm" width="20" height="20" patternUnits="userSpaceOnUse">
                <path d="M 20 0 L 0 0 0 20" fill="none" stroke="#27272a" strokeWidth="0.5" />
              </pattern>
              <pattern id="grid-lg" width="100" height="100" patternUnits="userSpaceOnUse">
                <rect width="100" height="100" fill="url(#grid-sm)" />
                <path d="M 100 0 L 0 0 0 100" fill="none" stroke="#3f3f46" strokeWidth="1" />
              </pattern>
            </defs>
            <rect width="100%" height="100%" fill="url(#grid-lg)" />

            {/* Committed annotations */}
            {layers.filter((l) => l.visible).map((l) =>
              l.annotations.map((ann) => (
                <AnnotationShape
                  key={ann.guid}
                  ann={ann}
                  selected={selectedGuid === ann.guid}
                  onClick={(e) => { e.stopPropagation(); setSelectedGuid(ann.guid) }}
                />
              )),
            )}

            {/* In-progress annotation */}
            {drawing && currentPts.length >= 2 && (
              <AnnotationShape
                ann={{
                  guid: '__preview__',
                  shape: activeShape,
                  xy_mm: currentPts,
                  color_rgb: hexToRgb(activeColor),
                  thickness_mm: thickness,
                  fill_rgba: null,
                  text_content: '',
                }}
                selected={false}
                onClick={() => {}}
              />
            )}
          </svg>

          {/* Deselect on canvas click */}
          <div
            className="absolute inset-0 pointer-events-none"
            onMouseDown={() => setSelectedGuid(null)}
          />
        </div>

        {/* Toolbar strip under canvas */}
        <div className="flex items-center gap-3 px-4 py-2 border-t border-zinc-800 bg-zinc-950 text-xs text-zinc-400">
          <span>
            Layer: <span className="text-zinc-200 font-medium">{activeLayer}</span>
          </span>
          <span>·</span>
          <span>
            Annotations: <span className="text-zinc-200">{allAnnotations.length}</span>
          </span>
          {selectedGuid && (
            <>
              <span>·</span>
              <button
                onClick={deleteSelected}
                className="flex items-center gap-1 text-red-400 hover:text-red-300 transition-colors"
              >
                <Trash2 size={12} /> Delete selected
              </button>
            </>
          )}
        </div>
      </div>

      {/* ── Right sidebar — annotation list ────────────────────────────── */}
      <div className="w-72 flex flex-col border-l border-zinc-800 shrink-0">
        <div className="p-3 border-b border-zinc-800">
          <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">
            Annotations
          </p>
          <div className="relative">
            <Search size={12} className="absolute left-2.5 top-2.5 text-zinc-500" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search…"
              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg pl-7 pr-3 py-1.5 text-xs text-zinc-200 focus:outline-none focus:border-blue-500"
            />
          </div>
        </div>

        {/* Sort header */}
        <div className="flex items-center gap-1 px-3 py-1.5 border-b border-zinc-800 text-xs text-zinc-500 select-none">
          <button
            onClick={() => toggleSort('author')}
            className="flex items-center gap-0.5 hover:text-zinc-300 transition-colors"
          >
            Author <SortIcon field="author" />
          </button>
          <span className="mx-1">·</span>
          <button
            onClick={() => toggleSort('created_at_iso')}
            className="flex items-center gap-0.5 hover:text-zinc-300 transition-colors"
          >
            Date <SortIcon field="created_at_iso" />
          </button>
          <span className="mx-1">·</span>
          <button
            onClick={() => toggleSort('shape')}
            className="flex items-center gap-0.5 hover:text-zinc-300 transition-colors"
          >
            Shape <SortIcon field="shape" />
          </button>
        </div>

        {/* Annotation rows */}
        <div className="flex-1 overflow-y-auto">
          {filtered.length === 0 && (
            <div className="flex flex-col items-center justify-center h-32 text-zinc-600 text-xs">
              No annotations yet.
              <br />
              Draw on the canvas to add one.
            </div>
          )}
          {filtered.map((ann) => (
            <div
              key={ann.guid}
              onClick={() => setSelectedGuid(ann.guid)}
              className={`px-3 py-2.5 border-b border-zinc-800/60 cursor-pointer transition-colors ${
                selectedGuid === ann.guid
                  ? 'bg-blue-600/10 border-blue-600/30'
                  : 'hover:bg-zinc-800/50'
              }`}
            >
              <div className="flex items-center gap-2 mb-0.5">
                <div
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ background: rgbToHex(ann.color_rgb) }}
                />
                <span className="text-xs font-medium text-zinc-200 capitalize">{ann.shape}</span>
                <span className="ml-auto text-xs text-zinc-500 truncate max-w-[80px]">{ann.layerName}</span>
              </div>
              {ann.text_content && (
                <p className="text-xs text-zinc-400 truncate pl-4">{ann.text_content}</p>
              )}
              <div className="flex items-center gap-2 pl-4 mt-0.5">
                <span className="text-xs text-zinc-600">{ann.author || 'me'}</span>
                {ann.created_at_iso && (
                  <span className="text-xs text-zinc-700">
                    {new Date(ann.created_at_iso).toLocaleDateString()}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
