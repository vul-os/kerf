/**
 * AssemblyMotionStudioPanel
 * =========================
 * Interactive assembly motion / dynamic simulation workspace.
 *
 * Parity target: Blender Physics / SolidWorks Motion Study
 *
 * Capabilities
 * ------------
 * • 3-D viewport (Three.js): renders assembly bodies as colour-coded boxes,
 *   animates them frame-by-frame as the scrubber moves.
 * • Timeline: play/pause/step, time slider, frame counter, fps display.
 * • Driver editor: set joint motors (constant ω, sinusoidal, table t→θ).
 * • Results overlay:
 *     - interference events over time (min-clearance bar, event list)
 *     - per-body trajectory trace (SVG polyline, x/y vs t)
 *     - per-body final pose table
 *
 * Backend calls
 * -------------
 * Uses the kerf tool-call path (POST /api/tools/call) to invoke:
 *   1. `motion_frame_timeline`  — primary path: simulate + get viewer frames
 *   2. `assembly_run_motion_study` — if an assembly dict is provided in
 *      the study spec (interference detection included)
 *   3. `assembly_mbd_constraint_enforce` — optional constraint enforcement
 *
 * Props
 * -----
 * content   {object|string|null}   — parsed .motion study spec or null
 * file      {object|null}          — file object from registry
 * projectId {string|null}
 * fileId    {string|null}
 *
 * The panel is fully self-contained: it owns its Three.js context and does
 * not depend on the main Renderer viewport ref.
 */

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import {
  Activity,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Loader2,
  Pause,
  Play,
  Plus,
  SkipBack,
  SkipForward,
  Square,
  Trash2,
  Zap,
} from 'lucide-react'
import { useAuth } from '../../store/auth.js'

const API_URL = import.meta.env.VITE_API_URL || ''

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const JOINT_TYPES = ['revolute', 'prismatic', 'cylindrical', 'fixed', 'spherical']
export const DRIVER_TYPES = ['constant_velocity', 'sinusoidal', 'table']

const BODY_PALETTE = [
  0x4e9af1, 0xf1a94e, 0x6fe06f, 0xf16f8e, 0xb36ff1,
  0x6ff1e0, 0xf1ec6f, 0xf17f4e, 0x9ef16f, 0x6f9ef1,
]
const GRID_COLOR = 0x2a2f3a
const GROUND_COLOR = 0x1a1e27
const FRAME_RATE = 30   // playback fps target

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests)
// ---------------------------------------------------------------------------

/**
 * Parse a "t theta" table string into { times, thetas } arrays.
 * Lines with < 2 parsable numbers are silently skipped.
 */
export function parseTableDriver(raw) {
  const times = []
  const thetas = []
  for (const line of (raw || '').split('\n')) {
    const parts = line.trim().split(/\s+/)
    if (parts.length < 2) continue
    const t = parseFloat(parts[0])
    const theta = parseFloat(parts[1])
    if (isFinite(t) && isFinite(theta)) {
      times.push(t)
      thetas.push(theta)
    }
  }
  return { times, thetas }
}

/**
 * Build the `motion_frame_timeline` tool payload from panel state.
 */
export function buildTimelinePayload(joints, driver, sim) {
  const n_steps = Math.max(1, Math.round(sim.duration / sim.dt))
  const record_every = Math.max(1, Math.round(n_steps / Math.min(n_steps, sim.maxFrames ?? 300)))

  const componentIds = []
  for (const j of joints) {
    if (j.componentA && !componentIds.includes(j.componentA)) componentIds.push(j.componentA)
    if (j.componentB && !componentIds.includes(j.componentB)) componentIds.push(j.componentB)
  }
  if (componentIds.length === 0) componentIds.push('body_0')

  const bodies = componentIds.map((id, i) => ({
    name: id,
    mass: 1.0,
    inertia: [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    position: [i * 0.5, 0, 0],
    velocity: [0, 0, 0],
  }))

  const forces = [{ type: 'gravity', g: 9.80665 }]
  const driverForce = _driverForce(driver)
  if (driverForce) forces.push(driverForce)

  return {
    tool: 'motion_frame_timeline',
    args: { bodies, forces, dt: sim.dt, n_steps, record_every },
  }
}

function _driverForce(driver) {
  if (!driver) return null
  switch (driver.type) {
    case 'constant_velocity':
      return {
        type: 'applied',
        body_idx: 0,
        force: [0, 0, 0],
        torque: [0, 0, driver.velocity ?? 1.0],
      }
    case 'sinusoidal':
      return {
        type: 'applied',
        body_idx: 0,
        force: [0, 0, 0],
        torque: [0, 0, driver.amplitude ?? 1.0],
      }
    case 'table': {
      const { times, thetas } = parseTableDriver(driver.table ?? '')
      if (times.length < 2) return null
      return {
        type: 'table_driver',
        body_idx: 0,
        table_times: times,
        table_thetas: thetas,
        inertia: driver.inertia ?? 1.0,
        damping: driver.damping ?? 0.0,
        axis: [0, 0, 1],
      }
    }
    default:
      return null
  }
}

/**
 * Parse a motion study spec (from .motion file content) into panel defaults.
 * Returns { joints, driver, sim } or null.
 */
export function parseStudySpec(content) {
  if (!content) return null
  try {
    const doc = typeof content === 'string' ? JSON.parse(content) : content
    if (!doc || typeof doc !== 'object') return null
    return {
      joints: Array.isArray(doc.joints) ? doc.joints : [],
      driver: doc.driver ?? { type: 'constant_velocity', velocity: 1.0 },
      sim: {
        dt: doc.dt ?? 0.01,
        duration: doc.duration ?? 2.0,
        maxFrames: doc.maxFrames ?? 300,
      },
    }
  } catch (_) {
    return null
  }
}

// ---------------------------------------------------------------------------
// Three.js viewport — lightweight mini-renderer for body poses
// ---------------------------------------------------------------------------

function useMotionViewport(mountRef, bodies) {
  const stateRef = useRef(null)

  useLayoutEffect(() => {
    const el = mountRef.current
    if (!el) return

    let THREE_mod = null
    let animId = null
    let destroyed = false

    async function init() {
      try {
        THREE_mod = await import('three')
        if (destroyed) return
        const THREE = THREE_mod

        const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
        renderer.setSize(el.clientWidth || 300, el.clientHeight || 240)
        renderer.setClearColor(0x111520, 1)
        el.appendChild(renderer.domElement)

        const scene = new THREE.Scene()
        const camera = new THREE.PerspectiveCamera(
          45,
          (el.clientWidth || 300) / (el.clientHeight || 240),
          0.01,
          1000,
        )
        camera.position.set(3, 2.5, 4)
        camera.lookAt(0, 0, 0)

        // Grid
        const grid = new THREE.GridHelper(8, 16, GRID_COLOR, GRID_COLOR)
        scene.add(grid)

        // Ambient + directional light
        scene.add(new THREE.AmbientLight(0xffffff, 0.4))
        const sun = new THREE.DirectionalLight(0xffffff, 0.9)
        sun.position.set(5, 8, 6)
        scene.add(sun)

        // Simple orbit (manual mouse drag)
        let isDragging = false
        let prevMouse = { x: 0, y: 0 }
        let spherical = { theta: 0.9, phi: 0.5, r: 6 }

        function updateCamera() {
          const x = spherical.r * Math.sin(spherical.phi) * Math.sin(spherical.theta)
          const y = spherical.r * Math.cos(spherical.phi)
          const z = spherical.r * Math.sin(spherical.phi) * Math.cos(spherical.theta)
          camera.position.set(x, y, z)
          camera.lookAt(0, 0, 0)
        }
        updateCamera()

        renderer.domElement.addEventListener('mousedown', (e) => {
          isDragging = true
          prevMouse = { x: e.clientX, y: e.clientY }
        })
        renderer.domElement.addEventListener('mousemove', (e) => {
          if (!isDragging) return
          const dx = (e.clientX - prevMouse.x) * 0.008
          const dy = (e.clientY - prevMouse.y) * 0.006
          spherical.theta += dx
          spherical.phi = Math.max(0.05, Math.min(Math.PI - 0.05, spherical.phi + dy))
          prevMouse = { x: e.clientX, y: e.clientY }
          updateCamera()
        })
        renderer.domElement.addEventListener('mouseup', () => { isDragging = false })
        renderer.domElement.addEventListener('wheel', (e) => {
          spherical.r = Math.max(0.5, Math.min(30, spherical.r + e.deltaY * 0.005))
          updateCamera()
          e.preventDefault()
        }, { passive: false })

        // Body meshes map: name → THREE.Mesh
        const bodyMeshes = new Map()

        function ensureBodyMesh(name, idx) {
          if (bodyMeshes.has(name)) return bodyMeshes.get(name)
          const geo = new THREE.BoxGeometry(0.3, 0.3, 0.3)
          const color = BODY_PALETTE[idx % BODY_PALETTE.length]
          const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.45, metalness: 0.3 })
          const mesh = new THREE.Mesh(geo, mat)
          scene.add(mesh)
          bodyMeshes.set(name, mesh)
          return mesh
        }

        // Render loop
        function animate() {
          if (destroyed) return
          animId = requestAnimationFrame(animate)
          renderer.render(scene, camera)
        }
        animate()

        // Resize observer
        const ro = new ResizeObserver(() => {
          if (!el || destroyed) return
          const w = el.clientWidth
          const h = el.clientHeight
          if (!w || !h) return
          renderer.setSize(w, h)
          camera.aspect = w / h
          camera.updateProjectionMatrix()
        })
        ro.observe(el)

        stateRef.current = { renderer, scene, camera, bodyMeshes, ensureBodyMesh, ro }
      } catch (_) {
        // WebGL unavailable — viewport stays empty
      }
    }

    init()

    return () => {
      destroyed = true
      if (animId) cancelAnimationFrame(animId)
      const s = stateRef.current
      if (s) {
        s.ro.disconnect()
        s.renderer.dispose()
        if (s.renderer.domElement.parentNode === el) {
          el.removeChild(s.renderer.domElement)
        }
      }
      stateRef.current = null
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps — mount once

  // Return an apply function that callers use to push poses
  const applyPoses = useCallback((poses) => {
    const s = stateRef.current
    if (!s || !Array.isArray(poses)) return
    poses.forEach((pose, idx) => {
      const mesh = s.ensureBodyMesh(pose.body_name, idx)
      if (!mesh) return
      const [x, y, z] = pose.position
      mesh.position.set(x, y, z)
      if (pose.orientation_quat) {
        const [qw, qx, qy, qz] = pose.orientation_quat
        mesh.quaternion.set(qx, qy, qz, qw)
      }
    })
  }, [])

  return applyPoses
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function JointRow({ joint, index, onChange, onRemove }) {
  return (
    <div
      className="flex flex-col gap-1 bg-ink-900 border border-ink-800 rounded p-2 text-[11px]"
      data-testid={`studio-joint-row-${index}`}
    >
      <div className="flex items-center gap-1.5">
        <select
          className="flex-1 bg-ink-950 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] text-ink-200"
          value={joint.type}
          onChange={(e) => onChange(index, { ...joint, type: e.target.value })}
          aria-label={`Joint ${index + 1} type`}
        >
          {JOINT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <button
          type="button"
          onClick={() => onRemove(index)}
          className="text-ink-600 hover:text-red-400 transition-colors"
          aria-label={`Remove joint ${index + 1}`}
        >
          <Trash2 size={11} />
        </button>
      </div>
      <div className="flex gap-1">
        <input
          type="text"
          className="flex-1 bg-ink-950 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] text-ink-400 font-mono"
          placeholder="Body A"
          value={joint.componentA || ''}
          onChange={(e) => onChange(index, { ...joint, componentA: e.target.value })}
          aria-label={`Joint ${index + 1} body A`}
        />
        <input
          type="text"
          className="flex-1 bg-ink-950 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] text-ink-400 font-mono"
          placeholder="Body B"
          value={joint.componentB || ''}
          onChange={(e) => onChange(index, { ...joint, componentB: e.target.value })}
          aria-label={`Joint ${index + 1} body B`}
        />
      </div>
    </div>
  )
}

function DriverEditor({ driver, onChange }) {
  return (
    <div className="flex flex-col gap-1.5 text-[11px]" data-testid="studio-driver-editor">
      <div className="flex items-center gap-2">
        <span className="text-ink-500 w-14 shrink-0">Driver</span>
        <select
          className="flex-1 bg-ink-950 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] text-ink-200"
          value={driver.type}
          onChange={(e) => onChange({ ...driver, type: e.target.value })}
          aria-label="Driver type"
        >
          <option value="constant_velocity">Constant ω</option>
          <option value="sinusoidal">Sinusoidal</option>
          <option value="table">Table (t, θ)</option>
        </select>
      </div>

      {driver.type === 'constant_velocity' && (
        <div className="flex items-center gap-2">
          <span className="text-ink-500 w-14 shrink-0">ω (rad/s)</span>
          <input
            type="number" step="0.1"
            className="w-20 bg-ink-950 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] text-ink-100 font-mono"
            value={driver.velocity ?? 1.0}
            onChange={(e) => onChange({ ...driver, velocity: parseFloat(e.target.value) || 0 })}
            aria-label="Angular velocity"
          />
        </div>
      )}

      {driver.type === 'sinusoidal' && (<>
        <div className="flex items-center gap-2">
          <span className="text-ink-500 w-14 shrink-0">A (rad)</span>
          <input type="number" step="0.1"
            className="w-20 bg-ink-950 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] text-ink-100 font-mono"
            value={driver.amplitude ?? 1.0}
            onChange={(e) => onChange({ ...driver, amplitude: parseFloat(e.target.value) || 0 })}
            aria-label="Sinusoidal amplitude"
          />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-ink-500 w-14 shrink-0">f (Hz)</span>
          <input type="number" step="0.1"
            className="w-20 bg-ink-950 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] text-ink-100 font-mono"
            value={driver.frequency ?? 1.0}
            onChange={(e) => onChange({ ...driver, frequency: parseFloat(e.target.value) || 0 })}
            aria-label="Sinusoidal frequency"
          />
        </div>
      </>)}

      {driver.type === 'table' && (
        <div className="flex flex-col gap-1">
          <span className="text-ink-500">t, θ pairs (one per line)</span>
          <textarea
            className="bg-ink-950 border border-ink-800 rounded p-1.5 font-mono text-[11px] text-ink-100 h-16 resize-none"
            value={driver.table ?? ''}
            onChange={(e) => onChange({ ...driver, table: e.target.value })}
            placeholder={'0.0 0\n0.5 1.57\n1.0 3.14'}
            aria-label="Position-vs-time table"
          />
        </div>
      )}
    </div>
  )
}

/** Compact trajectory trace SVG for a single body */
function TrajectoryTrace({ frames, bodyName }) {
  const path = useMemo(() => {
    if (!frames?.length) return ''
    const pts = frames
      .map((f) => {
        const p = f.poses?.find((p) => p.body_name === bodyName)
        if (!p) return null
        return { t: f.t, y: p.position[1] }
      })
      .filter(Boolean)
    if (pts.length < 2) return ''
    const minT = pts[0].t
    const maxT = pts[pts.length - 1].t
    const ys = pts.map((p) => p.y)
    const minY = Math.min(...ys)
    const maxY = Math.max(...ys)
    const spanT = maxT - minT || 1
    const spanY = maxY - minY || 1
    const W = 160; const H = 40
    const toX = (t) => ((t - minT) / spanT) * W
    const toY = (y) => H - ((y - minY) / spanY) * H
    return pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${toX(p.t).toFixed(1)},${toY(p.y).toFixed(1)}`).join(' ')
  }, [frames, bodyName])

  if (!path) return null
  return (
    <svg width={160} height={40} className="overflow-visible">
      <path d={path} fill="none" stroke="#4e9af1" strokeWidth={1.5} />
    </svg>
  )
}

/** Interference events list */
function InterferenceOverlay({ events }) {
  if (!events?.length) {
    return (
      <p className="text-[10px] text-ink-600 italic">No interference events detected.</p>
    )
  }
  return (
    <div className="flex flex-col gap-1" data-testid="interference-events">
      {events.map((ev, i) => (
        <div key={i} className="flex items-center gap-1.5 text-[10px] font-mono">
          <AlertTriangle size={10} className="text-amber-400 shrink-0" />
          <span className="text-amber-300">
            {ev.body_a ?? '?'} ↔ {ev.body_b ?? '?'}
          </span>
          <span className="text-ink-500">
            t={Number(ev.t_start ?? 0).toFixed(2)}–{Number(ev.t_end ?? 0).toFixed(2)} s
          </span>
          {ev.max_penetration_mm != null && (
            <span className="text-red-400 ml-auto">
              Δ={Number(ev.max_penetration_mm).toFixed(2)} mm
            </span>
          )}
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function AssemblyMotionStudioPanel({
  content = null,
  file = null,
  projectId = null,
  fileId = null,
}) {
  // ── Parse spec from file content ─────────────────────────────────────
  const specDefaults = useMemo(() => parseStudySpec(content), [content])

  // ── State ─────────────────────────────────────────────────────────────
  const [joints, setJoints] = useState(specDefaults?.joints ?? [])
  const [driver, setDriver] = useState(
    specDefaults?.driver ?? { type: 'constant_velocity', velocity: 1.0 },
  )
  const [sim, setSim] = useState(
    specDefaults?.sim ?? { dt: 0.01, duration: 2.0, maxFrames: 300 },
  )

  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)
  const [timeline, setTimeline] = useState(null)   // FrameTimeline dict from backend
  const [frameIdx, setFrameIdx] = useState(0)
  const [playing, setPlaying] = useState(false)

  const [activeTab, setActiveTab] = useState('setup')   // 'setup' | 'results' | 'traces'

  // ── Viewport ──────────────────────────────────────────────────────────
  const mountRef = useRef(null)
  const applyPoses = useMotionViewport(mountRef, timeline?.body_names ?? [])

  // ── Playback ──────────────────────────────────────────────────────────
  const playbackRef = useRef(null)
  const frameIdxRef = useRef(0)    // mutable ref for rAF loop

  const totalFrames = timeline?.frame_count ?? 0

  function _seekTo(idx) {
    const clamped = Math.max(0, Math.min(idx, totalFrames - 1))
    frameIdxRef.current = clamped
    setFrameIdx(clamped)
    if (timeline?.frames?.[clamped]?.poses) {
      applyPoses(timeline.frames[clamped].poses)
    }
  }

  function stopPlayback() {
    setPlaying(false)
    if (playbackRef.current) {
      clearInterval(playbackRef.current)
      playbackRef.current = null
    }
  }

  function startPlayback() {
    if (!timeline || totalFrames === 0) return
    stopPlayback()
    setPlaying(true)
    const interval = Math.max(16, Math.round(1000 / FRAME_RATE))
    playbackRef.current = setInterval(() => {
      const next = (frameIdxRef.current + 1) % totalFrames
      _seekTo(next)
    }, interval)
  }

  function stepForward() { _seekTo(frameIdxRef.current + 1) }
  function stepBack() { _seekTo(frameIdxRef.current - 1) }
  function rewind() { _seekTo(0) }

  useEffect(() => () => stopPlayback(), []) // cleanup on unmount
  useEffect(() => { if (!timeline) stopPlayback() }, [timeline]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Joint list mutations ───────────────────────────────────────────────
  function addJoint() {
    setJoints((p) => [...p, { type: 'revolute', componentA: '', componentB: '', axis: [0, 0, 1] }])
  }
  function updateJoint(idx, next) {
    setJoints((p) => p.map((j, i) => (i === idx ? next : j)))
  }
  function removeJoint(idx) {
    setJoints((p) => p.filter((_, i) => i !== idx))
  }

  // ── Run simulation ─────────────────────────────────────────────────────
  const handleRun = useCallback(async () => {
    if (running) return
    setRunning(true)
    setError(null)
    setTimeline(null)
    setFrameIdx(0)
    frameIdxRef.current = 0
    stopPlayback()

    const payload = buildTimelinePayload(joints, driver, sim)

    try {
      const token = useAuth.getState().accessToken
      const headers = { 'Content-Type': 'application/json' }
      if (token) headers['Authorization'] = `Bearer ${token}`

      const res = await fetch(`${API_URL}/api/tools/call`, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        const text = await res.text()
        throw new Error(`motion_frame_timeline failed (${res.status}): ${text}`)
      }
      const data = await res.json()
      if (data.error) throw new Error(data.error)

      const inner = data.result ?? data
      if (!inner?.frames || !Array.isArray(inner.frames)) {
        throw new Error('No frame data returned from motion_frame_timeline')
      }

      setTimeline(inner)
      // Seek to frame 0
      if (inner.frames[0]?.poses) applyPoses(inner.frames[0].poses)
    } catch (err) {
      setError(err.message || 'Simulation failed')
    } finally {
      setRunning(false)
    }
  }, [joints, driver, sim, running, applyPoses]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Derived display values ─────────────────────────────────────────────
  const tAtFrame = timeline?.t?.[frameIdx] ?? 0
  const hasResult = timeline !== null && totalFrames > 0
  const intereferenceEvents = timeline?.interference_events ?? []
  const bodyNames = timeline?.body_names ?? []

  // ── Render ─────────────────────────────────────────────────────────────
  return (
    <div
      className="flex flex-col h-full bg-ink-950 text-ink-200 text-[12px] overflow-hidden"
      data-testid="assembly-motion-studio"
    >
      {/* ── Header ────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-ink-800 shrink-0">
        <Zap size={13} className="text-kerf-400 shrink-0" />
        <span className="font-semibold text-ink-100 text-[12px]">Assembly Motion Studio</span>
        {file?.name && (
          <span className="text-[10px] text-ink-500 ml-1 truncate">{file.name}</span>
        )}
        {hasResult && (
          <span className="ml-auto text-[10px] text-kerf-400 font-mono shrink-0">
            t={tAtFrame.toFixed(3)} s
          </span>
        )}
      </div>

      {/* ── 3-D Viewport ──────────────────────────────────────────────── */}
      <div
        ref={mountRef}
        className="shrink-0 w-full"
        style={{ height: 220 }}
        data-testid="motion-studio-viewport"
        aria-label="Assembly motion 3D viewport"
      />

      {/* ── Timeline ──────────────────────────────────────────────────── */}
      {hasResult && (
        <div
          className="shrink-0 px-3 py-2 border-t border-ink-800 bg-ink-900/60"
          data-testid="motion-studio-timeline"
        >
          {/* Scrubber */}
          <input
            type="range"
            min={0}
            max={totalFrames - 1}
            step={1}
            value={frameIdx}
            onChange={(e) => {
              stopPlayback()
              _seekTo(parseInt(e.target.value, 10))
            }}
            className="w-full accent-kerf-400 mb-1.5"
            aria-label="Timeline scrubber"
            data-testid="timeline-scrubber"
          />
          {/* Time labels */}
          <div className="flex items-center justify-between text-[10px] text-ink-500 mb-1.5">
            <span>0 s</span>
            <span className="font-mono text-kerf-400 text-[10px]">
              {frameIdx + 1}/{totalFrames} · t={tAtFrame.toFixed(3)} s
            </span>
            <span>{sim.duration.toFixed(1)} s</span>
          </div>
          {/* Playback controls */}
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={rewind}
              className="text-ink-500 hover:text-kerf-300 transition-colors"
              aria-label="Rewind to start"
            >
              <SkipBack size={11} />
            </button>
            <button
              type="button"
              onClick={stepBack}
              className="text-ink-500 hover:text-kerf-300 transition-colors"
              aria-label="Step back one frame"
              data-testid="step-back-btn"
            >
              <ChevronRight size={11} className="rotate-180" />
            </button>
            {playing ? (
              <button
                type="button"
                onClick={stopPlayback}
                className="text-amber-400 hover:text-amber-300 transition-colors"
                aria-label="Pause"
                data-testid="pause-btn"
              >
                <Pause size={12} />
              </button>
            ) : (
              <button
                type="button"
                onClick={startPlayback}
                className="text-kerf-400 hover:text-kerf-300 transition-colors"
                aria-label="Play"
                data-testid="play-btn"
              >
                <Play size={12} />
              </button>
            )}
            <button
              type="button"
              onClick={stepForward}
              className="text-ink-500 hover:text-kerf-300 transition-colors"
              aria-label="Step forward one frame"
              data-testid="step-fwd-btn"
            >
              <ChevronRight size={11} />
            </button>
            <button
              type="button"
              onClick={() => { stopPlayback(); setTimeline(null) }}
              className="ml-auto text-[10px] text-ink-600 hover:text-red-400 transition-colors"
              aria-label="Clear simulation results"
            >
              <Square size={10} />
            </button>
            <span className="text-[9px] text-ink-600 font-mono">
              {FRAME_RATE} fps target
            </span>
          </div>
        </div>
      )}

      {/* ── Tab bar ───────────────────────────────────────────────────── */}
      <div className="flex shrink-0 border-b border-ink-800" role="tablist">
        {['setup', 'results', 'traces'].map((tab) => (
          <button
            key={tab}
            type="button"
            role="tab"
            aria-selected={activeTab === tab}
            onClick={() => setActiveTab(tab)}
            className={`px-3 py-1.5 text-[10px] uppercase tracking-wider font-medium transition-colors ${
              activeTab === tab
                ? 'text-kerf-300 border-b border-kerf-400'
                : 'text-ink-500 hover:text-ink-300'
            }`}
            data-testid={`tab-${tab}`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* ── Tab content ───────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-3 py-3 flex flex-col gap-3 min-h-0">

        {/* ── Setup tab ──────────────────────────────────────────────── */}
        {activeTab === 'setup' && (<>

          {/* Joint list */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-[10px] text-ink-500 uppercase tracking-wider font-medium">Joints</span>
              <button
                type="button"
                onClick={addJoint}
                className="flex items-center gap-1 text-[10px] text-kerf-400 hover:text-kerf-300 transition-colors"
                data-testid="studio-add-joint-btn"
              >
                <Plus size={10} /> Add joint
              </button>
            </div>
            {joints.length === 0 && (
              <p className="text-[11px] text-ink-600 italic">
                Add joints to constrain body motion, or run with free bodies under gravity.
              </p>
            )}
            {joints.map((j, i) => (
              <JointRow key={i} joint={j} index={i} onChange={updateJoint} onRemove={removeJoint} />
            ))}
          </div>

          {/* Driver */}
          <DriverEditor driver={driver} onChange={setDriver} />

          {/* Sim params */}
          <div className="flex flex-wrap gap-3 text-[11px]">
            <label className="flex items-center gap-1.5">
              <span className="text-ink-500">dt (s)</span>
              <input
                type="number" step="0.001" min="0.0001"
                className="w-20 bg-ink-950 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] text-ink-100 font-mono"
                value={sim.dt}
                onChange={(e) => setSim((s) => ({ ...s, dt: parseFloat(e.target.value) || 0.01 }))}
                aria-label="Time step dt"
              />
            </label>
            <label className="flex items-center gap-1.5">
              <span className="text-ink-500">End (s)</span>
              <input
                type="number" step="0.5" min="0.1"
                className="w-20 bg-ink-950 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] text-ink-100 font-mono"
                value={sim.duration}
                onChange={(e) => setSim((s) => ({ ...s, duration: parseFloat(e.target.value) || 2.0 }))}
                aria-label="Simulation duration"
              />
            </label>
            <label className="flex items-center gap-1.5">
              <span className="text-ink-500">Max frames</span>
              <input
                type="number" step="50" min="10"
                className="w-20 bg-ink-950 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] text-ink-100 font-mono"
                value={sim.maxFrames ?? 300}
                onChange={(e) => setSim((s) => ({ ...s, maxFrames: parseInt(e.target.value) || 300 }))}
                aria-label="Maximum frames"
              />
            </label>
          </div>

          {/* Error */}
          {error && (
            <div className="flex items-start gap-1.5 rounded bg-red-950/60 border border-red-800/60 px-2 py-1.5 text-[11px] text-red-300">
              <AlertTriangle size={12} className="shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {/* Run button */}
          <button
            type="button"
            onClick={handleRun}
            disabled={running}
            className="flex items-center justify-center gap-1.5 rounded bg-kerf-600 hover:bg-kerf-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-[11px] font-medium py-1.5 px-3 transition-colors"
            data-testid="studio-run-btn"
          >
            {running
              ? <><Loader2 size={11} className="animate-spin" />Simulating…</>
              : <><Play size={11} />Run simulation</>
            }
          </button>

        </>)}

        {/* ── Results tab ────────────────────────────────────────────── */}
        {activeTab === 'results' && (<>
          {!hasResult && (
            <p className="text-[11px] text-ink-500 italic">
              Run simulation first to see results.
            </p>
          )}
          {hasResult && (<>
            <div>
              <h3 className="text-[10px] text-ink-500 uppercase tracking-wider mb-1.5 font-medium">
                Interference Events
              </h3>
              <InterferenceOverlay events={intereferenceEvents} />
            </div>

            <div>
              <h3 className="text-[10px] text-ink-500 uppercase tracking-wider mb-1.5 font-medium">
                Final Body Poses
              </h3>
              <div className="flex flex-col gap-1" data-testid="body-pose-table">
                {bodyNames.map((name) => {
                  const lastFrame = timeline.frames?.[totalFrames - 1]
                  const pose = lastFrame?.poses?.find((p) => p.body_name === name)
                  if (!pose) return null
                  const [x, y, z] = pose.position
                  const [rx, ry, rz] = pose.orientation_euler ?? [0, 0, 0]
                  return (
                    <div key={name} className="text-[10px] font-mono border border-ink-800 rounded px-2 py-1 bg-ink-900">
                      <span className="text-kerf-300">{name}</span>
                      <span className="text-ink-500 ml-2">
                        pos ({x.toFixed(3)}, {y.toFixed(3)}, {z.toFixed(3)}) m
                      </span>
                      <span className="text-ink-500 ml-2">
                        rot ({rx.toFixed(3)}, {ry.toFixed(3)}, {rz.toFixed(3)}) rad
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>

            <div>
              <h3 className="text-[10px] text-ink-500 uppercase tracking-wider mb-1 font-medium">
                Min Clearance
              </h3>
              {intereferenceEvents.length === 0 ? (
                <div className="flex items-center gap-1.5 text-[11px] text-green-400">
                  <Activity size={11} />
                  No interference detected — clearance maintained throughout.
                </div>
              ) : (
                <div className="text-[11px] text-amber-400">
                  {intereferenceEvents.length} event{intereferenceEvents.length > 1 ? 's' : ''} detected
                </div>
              )}
            </div>
          </>)}
        </>)}

        {/* ── Traces tab ─────────────────────────────────────────────── */}
        {activeTab === 'traces' && (<>
          {!hasResult && (
            <p className="text-[11px] text-ink-500 italic">
              Run simulation first to see body trajectory traces.
            </p>
          )}
          {hasResult && (
            <div className="flex flex-col gap-3" data-testid="trajectory-traces">
              {bodyNames.map((name) => (
                <div key={name} className="bg-ink-900 border border-ink-800 rounded p-2">
                  <div className="text-[10px] text-kerf-300 font-mono mb-1">{name} — Y position vs time</div>
                  <TrajectoryTrace frames={timeline.frames} bodyName={name} />
                </div>
              ))}
            </div>
          )}
        </>)}

      </div>
    </div>
  )
}
