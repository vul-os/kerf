/**
 * SurgicalGuide — CBCT scan import + implant pose editor + drill sleeve setup
 * + final guide preview with milling-ready B-rep body rendering + STL export.
 *
 * Uses the existing point-cloud importer pattern (file input → parse as JSON
 * or CSV xyz, builds jaw_surface_pts array). Dispatches `dental_surgical_guide`
 * via POST /api/tools/call.
 *
 * Backend tool: packages/kerf-dental/src/kerf_dental/tools.py → dental_surgical_guide
 *
 * Wave 4D caveat closed: backend now emits `body_stl_b64` (binary STL base64)
 * alongside the planning data.  This component renders the B-rep in a Three.js
 * viewport and provides an "Export STL" button.
 */

import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../../store/auth.js'
import { buildSurgicalGuidePayload } from './dentalDispatch.js'

const API_URL = import.meta.env.VITE_API_URL || ''

// ---------------------------------------------------------------------------
// STL export helper — decodes base64 binary STL and triggers a download
// ---------------------------------------------------------------------------
function exportStlFromB64(b64, filename = 'surgical_guide.stl') {
  const binary = atob(b64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  const blob = new Blob([bytes], { type: 'model/stl' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

// ---------------------------------------------------------------------------
// Three.js B-rep viewport — renders the guide body STL in a canvas
// ---------------------------------------------------------------------------
function GuideBrepViewport({ stlB64 }) {
  const canvasRef = useRef(null)
  const rendererRef = useRef(null)
  const animRef = useRef(null)

  useEffect(() => {
    if (!stlB64 || !canvasRef.current) return

    let three, scene, camera, renderer, mesh, animId

    async function init() {
      try {
        three = await import('three')
        const { STLLoader } = await import('three/examples/jsm/loaders/STLLoader.js')

        const canvas = canvasRef.current
        renderer = new three.WebGLRenderer({ canvas, antialias: true, alpha: true })
        renderer.setSize(320, 180)
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
        rendererRef.current = renderer

        scene = new three.Scene()
        camera = new three.PerspectiveCamera(45, 320 / 180, 0.1, 1000)

        // Decode base64 STL
        const binary = atob(stlB64)
        const buf = new ArrayBuffer(binary.length)
        const view = new Uint8Array(buf)
        for (let i = 0; i < binary.length; i++) view[i] = binary.charCodeAt(i)

        const loader = new STLLoader()
        const geometry = loader.parse(buf)
        geometry.computeBoundingBox()
        geometry.computeVertexNormals()

        const box = geometry.boundingBox
        const center = new three.Vector3()
        box.getCenter(center)
        geometry.translate(-center.x, -center.y, -center.z)

        const size = new three.Vector3()
        box.getSize(size)
        const maxDim = Math.max(size.x, size.y, size.z)

        const material = new three.MeshPhongMaterial({
          color: 0x38bdf8,
          specular: 0x1e3a5f,
          shininess: 40,
          transparent: true,
          opacity: 0.85,
          side: three.DoubleSide,
        })
        mesh = new three.Mesh(geometry, material)
        scene.add(mesh)

        // Lights
        scene.add(new three.AmbientLight(0xffffff, 0.5))
        const dirLight = new three.DirectionalLight(0xffffff, 1.0)
        dirLight.position.set(1, 2, 3)
        scene.add(dirLight)

        camera.position.set(0, -maxDim * 1.5, maxDim * 1.2)
        camera.lookAt(0, 0, 0)

        // Simple orbit on mouse drag
        let isDragging = false, lastX = 0, lastY = 0, rotX = 0, rotY = 0
        canvas.addEventListener('mousedown', (e) => { isDragging = true; lastX = e.clientX; lastY = e.clientY })
        canvas.addEventListener('mousemove', (e) => {
          if (!isDragging) return
          rotY += (e.clientX - lastX) * 0.01
          rotX += (e.clientY - lastY) * 0.01
          lastX = e.clientX; lastY = e.clientY
        })
        canvas.addEventListener('mouseup', () => { isDragging = false })
        canvas.addEventListener('mouseleave', () => { isDragging = false })

        function animate() {
          animId = requestAnimationFrame(animate)
          if (!isDragging) rotY += 0.005
          mesh.rotation.x = rotX
          mesh.rotation.y = rotY
          renderer.render(scene, camera)
        }
        animate()
        animRef.current = () => cancelAnimationFrame(animId)
      } catch {
        // Three.js not available — silently degrade to SVG preview
      }
    }

    init()

    return () => {
      animRef.current?.()
      rendererRef.current?.dispose()
    }
  }, [stlB64])

  if (!stlB64) return null

  return (
    <div className="relative rounded overflow-hidden border border-sky-700/40 bg-ink-950">
      <canvas
        ref={canvasRef}
        width={320}
        height={180}
        aria-label="3D viewport — milling-ready surgical guide B-rep"
        className="block w-full"
        style={{ cursor: 'grab' }}
      />
      <div className="absolute top-1.5 left-2 text-[8px] font-mono text-sky-500/70 tracking-widest">
        B-REP · MILLING-READY
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// SVG guide preview — draws jaw surface points + implant cylinders + sleeves
// ---------------------------------------------------------------------------
function GuidePreview({ jawPts, implants, result }) {
  if (!jawPts || jawPts.length === 0) return null

  const W = 320
  const H = 160
  const PAD = 20

  const xs = jawPts.map((p) => p[0])
  const ys = jawPts.map((p) => p[1])
  const minX = Math.min(...xs)
  const minY = Math.min(...ys)
  const rangeX = (Math.max(...xs) - minX) || 1
  const rangeY = (Math.max(...ys) - minY) || 1

  const toSvg = (x, y) => [
    PAD + ((x - minX) / rangeX) * (W - 2 * PAD),
    PAD + ((y - minY) / rangeY) * (H - 2 * PAD),
  ]

  const jawPath = jawPts
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${toSvg(p[0], p[1]).join(' ')}`)
    .join(' ') + ' Z'

  return (
    <svg
      width={W}
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      aria-label="Surgical guide occlusal SVG preview"
      className="rounded border border-ink-700 bg-ink-950"
    >
      {/* Jaw surface polygon */}
      <path d={jawPath} fill="#0f172a" stroke="#334155" strokeWidth="1.5" />
      <path d={jawPath} fill="#38bdf8" fillOpacity="0.07" />

      {/* Implant positions */}
      {implants.map((imp, i) => {
        const [cx, cy] = toSvg(imp.position[0], imp.position[1])
        const r = (imp.diameter_mm / 2) * 4
        const len = imp.length_mm * 2
        const placed = result && i < result.sleeve_count
        return (
          <g key={i}>
            <line
              x1={cx} y1={cy}
              x2={cx + imp.axis_direction[0] * len}
              y2={cy - imp.axis_direction[2] * len}
              stroke={placed ? '#22c55e' : '#64748b'}
              strokeWidth={r}
              strokeLinecap="round"
              opacity="0.7"
            />
            <circle
              cx={cx}
              cy={cy}
              r={r + 3}
              fill="none"
              stroke={placed ? '#22c55e' : '#94a3b8'}
              strokeWidth="1.5"
              opacity="0.8"
            />
            <text x={cx + r + 4} y={cy + 4} fontSize="9" fill="#94a3b8" fontFamily="monospace">
              I{i + 1}
            </text>
          </g>
        )
      })}

      {/* Legend */}
      <text x="6" y="14" fontSize="8" fill="#475569" fontFamily="monospace">occlusal view</text>
      {result && (
        <text x="6" y={H - 6} fontSize="8" fill="#22c55e" fontFamily="monospace">
          {result.sleeve_count} sleeve{result.sleeve_count !== 1 ? 's' : ''} placed
          {' · '}max err {result.max_angular_error_deg?.toFixed(4)}°
        </text>
      )}
      {result?.body_stl_b64 && (
        <text x="6" y={H - 16} fontSize="8" fill="#38bdf8" fontFamily="monospace">
          B-rep: {result.body_stl_bytes} bytes STL
        </text>
      )}
    </svg>
  )
}

// ---------------------------------------------------------------------------
// ImplantPoseRow — editable row for one implant's position + axis
// ---------------------------------------------------------------------------
function ImplantPoseRow({ index, implant, onChange, onRemove }) {
  function update(field, subfield, value) {
    const next = JSON.parse(JSON.stringify(implant))
    if (subfield != null) {
      next[field][subfield] = parseFloat(value) || 0
    } else {
      next[field] = parseFloat(value) || 0
    }
    onChange(index, next)
  }

  const AxisInput = ({ axis, si }) => (
    <input
      type="number"
      step="0.1"
      value={implant[axis][si]}
      onChange={(e) => update(axis, si, e.target.value)}
      className="w-14 bg-ink-800 border border-ink-700 rounded px-1 py-0.5 text-[10px] font-mono text-ink-100 outline-none focus:border-sky-400/60"
      aria-label={`${axis}[${si}]`}
    />
  )

  return (
    <div className="flex flex-col gap-1 p-2 rounded bg-ink-800/60 border border-ink-700 text-[10px]">
      <div className="flex items-center justify-between">
        <span className="font-mono text-sky-300">Implant {index + 1}</span>
        <button
          type="button"
          onClick={() => onRemove(index)}
          className="text-ink-500 hover:text-red-400 text-[10px]"
          aria-label={`Remove implant ${index + 1}`}
        >
          Remove
        </button>
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-ink-500 w-10">pos:</span>
        <AxisInput axis="position" si={0} />
        <AxisInput axis="position" si={1} />
        <AxisInput axis="position" si={2} />
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-ink-500 w-10">axis:</span>
        <AxisInput axis="axis_direction" si={0} />
        <AxisInput axis="axis_direction" si={1} />
        <AxisInput axis="axis_direction" si={2} />
      </div>
      <div className="flex items-center gap-3">
        <label className="flex items-center gap-1 text-ink-400">
          &#8960;
          <input
            type="number"
            min="2"
            max="7"
            step="0.5"
            value={implant.diameter_mm}
            onChange={(e) => update('diameter_mm', null, e.target.value)}
            className="w-14 bg-ink-800 border border-ink-700 rounded px-1 py-0.5 font-mono text-ink-100 outline-none focus:border-sky-400/60"
          />
          mm
        </label>
        <label className="flex items-center gap-1 text-ink-400">
          L
          <input
            type="number"
            min="6"
            max="20"
            step="1"
            value={implant.length_mm}
            onChange={(e) => update('length_mm', null, e.target.value)}
            className="w-14 bg-ink-800 border border-ink-700 rounded px-1 py-0.5 font-mono text-ink-100 outline-none focus:border-sky-400/60"
          />
          mm
        </label>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Parse point cloud from .csv or .json string
// ---------------------------------------------------------------------------
function parsePointCloud(text) {
  text = text.trim()
  if (text.startsWith('[')) {
    const arr = JSON.parse(text)
    if (!Array.isArray(arr)) throw new Error('Expected JSON array')
    return arr.map((row) => {
      if (Array.isArray(row)) return row.slice(0, 3).map(Number)
      return [Number(row.x || row[0] || 0), Number(row.y || row[1] || 0), Number(row.z || row[2] || 0)]
    })
  }
  return text
    .split('\n')
    .filter(Boolean)
    .map((line) => line.split(/[,\s]+/).slice(0, 3).map(Number))
    .filter((row) => row.length === 3 && row.every(Number.isFinite))
}

// Default jaw for demo
const DEMO_JAW_PTS = [
  [0, 0, 0], [30, 0, 0], [35, 8, 0], [30, 15, 0],
  [15, 18, 0], [0, 15, 0], [-5, 8, 0],
]

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------
export default function SurgicalGuide({ projectId }) {
  const { accessToken } = useAuth()
  const fileInputRef = useRef(null)

  const [jawPts, setJawPts]       = useState(DEMO_JAW_PTS)
  const [jawLabel, setJawLabel]   = useState('Demo jaw (7 pts)')
  const [jawError, setJawError]   = useState(null)

  const [implants, setImplants] = useState([
    { position: [10, 8, 0], axis_direction: [0, 0, 1], diameter_mm: 4.1, length_mm: 10 },
  ])

  const [running, setRunning] = useState(false)
  const [result, setResult]   = useState(null)
  const [error, setError]     = useState(null)

  // ---- file import ----
  function handleFileChange(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setJawError(null)
    const reader = new FileReader()
    reader.onload = (ev) => {
      try {
        const pts = parsePointCloud(ev.target.result || '')
        if (pts.length < 3) throw new Error('Need at least 3 points')
        setJawPts(pts)
        setJawLabel(`${file.name} (${pts.length} pts)`)
        setResult(null)
      } catch (err) {
        setJawError(`Failed to parse "${file.name}": ${err.message}`)
      }
    }
    reader.readAsText(file)
    e.target.value = ''
  }

  // ---- implant management ----
  function addImplant() {
    setImplants((prev) => [
      ...prev,
      { position: [prev.length * 6, 8, 0], axis_direction: [0, 0, 1], diameter_mm: 4.1, length_mm: 10 },
    ])
  }

  function updateImplant(idx, next) {
    setImplants((prev) => prev.map((imp, i) => (i === idx ? next : imp)))
  }

  function removeImplant(idx) {
    setImplants((prev) => prev.filter((_, i) => i !== idx))
  }

  // ---- run ----
  async function handleRun() {
    if (implants.length === 0) { setError('Add at least one implant.'); return }
    setRunning(true)
    setResult(null)
    setError(null)
    try {
      const body = buildSurgicalGuidePayload({
        jaw_surface_pts: jawPts,
        implants: implants.map((imp) => ({
          position: imp.position,
          axis_direction: imp.axis_direction,
          diameter_mm: imp.diameter_mm,
          length_mm: imp.length_mm,
        })),
      })
      const res = await fetch(`${API_URL}/api/tools/call`, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          ...(accessToken ? { authorization: `Bearer ${accessToken}` } : {}),
        },
        body: JSON.stringify(body),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(data?.error || `HTTP ${res.status}`)
      } else {
        setResult(data)
      }
    } catch (err) {
      setError(err?.message || String(err))
    } finally {
      setRunning(false)
    }
  }

  // ---- export STL ----
  function handleExportStl() {
    if (!result?.body_stl_b64) return
    exportStlFromB64(result.body_stl_b64, `surgical_guide_${implants.length}imp.stl`)
  }

  return (
    <div className="flex flex-col gap-4 p-4 text-ink-100" data-testid="surgical-guide-panel">
      <div className="flex items-center gap-2">
        <span className="text-[11px] font-mono uppercase tracking-widest text-ink-400">Surgical Guide</span>
        <span className="ml-auto text-[10px] text-ink-600 font-mono">dental_surgical_guide</span>
      </div>

      {/* CBCT / point cloud import */}
      <div>
        <label className="block text-[11px] text-ink-400 mb-1.5">Jaw surface (CBCT / point cloud)</label>
        <div className="flex items-center gap-2">
          <div className="flex-1 rounded border border-ink-700 bg-ink-800 px-2 py-1.5 text-[11px] text-ink-400 font-mono truncate">
            {jawLabel}
          </div>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="px-3 py-1.5 rounded bg-sky-500/15 border border-sky-400/40 text-sky-200 text-xs hover:bg-sky-500/25"
          >
            Import
          </button>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,.txt,.json,.xyz"
          onChange={handleFileChange}
          className="hidden"
          aria-label="Import jaw surface point cloud"
        />
        {jawError && (
          <p className="mt-1 text-[10px] text-red-400 font-mono">{jawError}</p>
        )}
        <p className="mt-1 text-[10px] text-ink-600">
          Accepts .csv (x,y,z per line) or .json ([[x,y,z],...]). Demo jaw loaded by default.
        </p>
      </div>

      {/* B-rep 3D viewport (shown after generation) */}
      {result?.body_stl_b64 && (
        <div>
          <label className="block text-[11px] text-ink-400 mb-1.5">B-rep guide body (Three.js)</label>
          <GuideBrepViewport stlB64={result.body_stl_b64} />
        </div>
      )}

      {/* SVG guide preview (always shown) */}
      <div>
        <label className="block text-[11px] text-ink-400 mb-1.5">
          {result?.body_stl_b64 ? 'Occlusal SVG preview' : 'Guide preview'}
        </label>
        <GuidePreview jawPts={jawPts} implants={implants} result={result} />
      </div>

      {/* Implant pose editor */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="text-[11px] text-ink-400">Implant poses ({implants.length})</label>
          <button
            type="button"
            onClick={addImplant}
            className="text-[10px] px-2 py-1 rounded bg-sky-500/15 border border-sky-400/30 text-sky-300 hover:bg-sky-500/25"
          >
            + Add implant
          </button>
        </div>
        <div className="flex flex-col gap-2 max-h-64 overflow-y-auto pr-0.5">
          {implants.length === 0 && (
            <div className="text-center text-ink-500 text-xs py-4">No implants — click Add implant.</div>
          )}
          {implants.map((imp, i) => (
            <ImplantPoseRow
              key={i}
              index={i}
              implant={imp}
              onChange={updateImplant}
              onRemove={removeImplant}
            />
          ))}
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={handleRun}
          disabled={running || implants.length === 0}
          className="flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded bg-sky-500/20 border border-sky-400/50 text-sky-200 text-xs font-medium hover:bg-sky-500/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {running ? (
            <>
              <span className="w-3 h-3 border-2 border-sky-400 border-t-transparent rounded-full animate-spin" />
              Generating guide…
            </>
          ) : (
            'Generate surgical guide'
          )}
        </button>

        {result?.body_stl_b64 && (
          <button
            type="button"
            onClick={handleExportStl}
            data-testid="export-stl-button"
            className="px-3 py-2 rounded bg-emerald-500/20 border border-emerald-400/50 text-emerald-200 text-xs font-medium hover:bg-emerald-500/30 transition-colors whitespace-nowrap"
            aria-label="Export surgical guide as STL"
          >
            Export STL
          </button>
        )}
      </div>

      {/* Result */}
      {result && (
        <div
          className="rounded border border-sky-700/50 bg-sky-950/30 p-3 text-[11px] font-mono text-sky-300 space-y-1"
          data-testid="surgical-guide-result"
        >
          <div className="text-sky-400 font-semibold mb-1">Surgical guide generated</div>
          {result.sleeve_count != null && (
            <div>sleeves: <span className="text-sky-200">{result.sleeve_count}</span></div>
          )}
          {result.max_angular_error_deg != null && (
            <div>max angular error: <span className="text-sky-200">{result.max_angular_error_deg}&#176;</span></div>
          )}
          {Array.isArray(result.angular_errors_deg) && (
            <div>
              per-sleeve errors:{' '}
              <span className="text-sky-200">
                [{result.angular_errors_deg.map((e) => e.toFixed(4)).join(', ')}]
              </span>
            </div>
          )}
          {result.all_validate_body_ok && (
            <div className="text-sky-400">validate_body: OK</div>
          )}
          {result.body_stl_b64 && (
            <div className="text-emerald-400">
              B-rep body: {result.body_stl_bytes} bytes STL
              {result.plate_dims_mm && (
                <span className="text-emerald-300 ml-1">
                  · plate {result.plate_dims_mm.map((v) => v.toFixed(1)).join('×')} mm
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {/* Error */}
      {error && (
        <div
          className="rounded border border-red-700/50 bg-red-950/30 p-3 text-[11px] font-mono text-red-300"
          data-testid="surgical-guide-error"
        >
          {error}
        </div>
      )}
    </div>
  )
}
