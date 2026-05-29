// AssemblyMotionPanel — planar MBD assembly motion side panel.
//
// Wires the kerf-motion `simulate_motion` backend tool into the assembly UI:
//   - Joint-list editor (revolute / prismatic / cylindrical per component pair)
//   - Driver input (constant angular velocity, position-vs-time table, or sinusoidal)
//   - "Run" button dispatches POST /api/tools/call → simulate_motion
//   - Timeline scrubber drives component transforms in the Three.js scene via
//     the Renderer imperative handle (`rendererRef.current.setComponentTransforms`)
//
// Props
// -----
// components     — array of assembly component rows (from parseAssembly)
// rendererRef    — React ref forwarded to <Renderer>; exposes setComponentTransforms
// projectId      — for context (passed through; not used in dispatch)
// onToast        — (msg) => void  optional toast for errors

import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, Play, Square, Loader2, Zap, Plus, Trash2 } from 'lucide-react'
import { useAuth } from '../store/auth.js'

const API_URL = import.meta.env.VITE_API_URL || ''

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const JOINT_TYPES = ['revolute', 'prismatic', 'cylindrical']
export const DRIVER_TYPES = ['constant_velocity', 'sinusoidal', 'table']

const DEFAULT_SIM = {
  dt: 0.01,
  duration: 2.0,
}

// ---------------------------------------------------------------------------
// Pure helpers (export for tests)
// ---------------------------------------------------------------------------

/**
 * Build the `simulate_motion` tool payload from panel state.
 *
 * @param {object[]} joints  — [{type, componentA, componentB, axis, value, ...}]
 * @param {object}   driver  — {type, velocity|amplitude|frequency|table}
 * @param {object}   sim     — {dt, duration}
 * @returns {object}  payload for POST /api/tools/call
 */
export function buildSimPayload(joints, driver, sim) {
  const n_steps = Math.max(1, Math.round(sim.duration / sim.dt))

  // One rigid body per unique component id referenced in joints, plus a
  // ground body (index 0).  For a simple planar analysis we give everything
  // unit mass / inertia so the integrator runs; real geometry would fill these.
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
    position: [0, i * 0.5, 0],
    velocity: [0, 0, 0],
  }))

  // Driver → force/torque on body 0
  const forces = [{ type: 'gravity', g: 9.80665 }]
  if (bodies.length > 0) {
    const dv = _driverForce(driver)
    if (dv) forces.push({ type: 'applied', body_idx: 0, force: dv.force, torque: dv.torque })
  }

  return {
    tool: 'simulate_motion',
    args: {
      bodies,
      forces,
      joints: joints.map((j) => ({
        type: j.type,
        component_a: j.componentA,
        component_b: j.componentB,
        axis: j.axis || [0, 0, 1],
      })),
      dt: sim.dt,
      n_steps,
      record_every: Math.max(1, Math.round(n_steps / 200)), // cap at ~200 frames
    },
  }
}

function _driverForce(driver) {
  if (!driver) return null
  switch (driver.type) {
    case 'constant_velocity':
      return { force: [0, 0, 0], torque: [0, 0, (driver.velocity ?? 1.0)] }
    case 'sinusoidal':
      // Amplitude × sin(2π f t) — approximated as constant amplitude for payload
      return { force: [0, 0, 0], torque: [0, 0, (driver.amplitude ?? 1.0)] }
    default:
      return null
  }
}

/**
 * Given a trajectory result from simulate_motion, extract the XZ position
 * of each body at frame index `frameIdx`.
 *
 * Returns Map<componentId, {x, y, z, qw, qx, qy, qz}>
 *
 * @param {object[]} componentIds  — ordered component ids matching bodies[]
 * @param {object}   result        — raw simulate_motion response
 * @param {number}   frameIdx      — 0-based frame index
 */
export function extractTransformsAtFrame(componentIds, result, frameIdx) {
  const map = new Map()
  if (!result?.trajectories) return map
  result.trajectories.forEach((traj, i) => {
    const id = componentIds[i]
    if (!id) return
    const snap = traj[Math.min(frameIdx, traj.length - 1)]
    if (!snap) return
    const [x = 0, y = 0, z = 0] = snap.position ?? []
    map.set(id, { x, y, z, qw: 1, qx: 0, qy: 0, qz: 0 })
  })
  return map
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function JointRow({ joint, index, components, onChange, onRemove }) {
  return (
    <div
      className="flex flex-col gap-1 bg-ink-900 border border-ink-800 rounded p-2 text-[11px]"
      data-testid={`joint-row-${index}`}
    >
      <div className="flex items-center gap-1.5">
        <select
          className="flex-1 bg-ink-950 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] text-ink-200"
          value={joint.type}
          onChange={(e) => onChange(index, { ...joint, type: e.target.value })}
          aria-label={`Joint ${index + 1} type`}
        >
          {JOINT_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
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
        <select
          className="flex-1 bg-ink-950 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] text-ink-400"
          value={joint.componentA || ''}
          onChange={(e) => onChange(index, { ...joint, componentA: e.target.value })}
          aria-label={`Joint ${index + 1} component A`}
        >
          <option value="">Body A…</option>
          {(components || []).map((c) => (
            <option key={c.id} value={c.id}>{c.id}</option>
          ))}
        </select>
        <select
          className="flex-1 bg-ink-950 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] text-ink-400"
          value={joint.componentB || ''}
          onChange={(e) => onChange(index, { ...joint, componentB: e.target.value })}
          aria-label={`Joint ${index + 1} component B`}
        >
          <option value="">Body B…</option>
          {(components || []).map((c) => (
            <option key={c.id} value={c.id}>{c.id}</option>
          ))}
        </select>
      </div>
    </div>
  )
}

function DriverEditor({ driver, onChange }) {
  return (
    <div className="flex flex-col gap-1.5 text-[11px]" data-testid="driver-editor">
      <div className="flex items-center gap-2">
        <span className="text-ink-500 w-16 shrink-0">Driver</span>
        <select
          className="flex-1 bg-ink-950 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] text-ink-200"
          value={driver.type}
          onChange={(e) => onChange({ ...driver, type: e.target.value })}
          aria-label="Driver type"
        >
          <option value="constant_velocity">Constant velocity</option>
          <option value="sinusoidal">Sinusoidal</option>
          <option value="table">Table (t, θ)</option>
        </select>
      </div>

      {driver.type === 'constant_velocity' && (
        <div className="flex items-center gap-2">
          <span className="text-ink-500 w-16 shrink-0">ω (rad/s)</span>
          <input
            type="number"
            step="0.1"
            className="w-24 bg-ink-950 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] text-ink-100 font-mono"
            value={driver.velocity ?? 1.0}
            onChange={(e) => onChange({ ...driver, velocity: parseFloat(e.target.value) || 0 })}
            aria-label="Constant angular velocity"
          />
        </div>
      )}

      {driver.type === 'sinusoidal' && (
        <>
          <div className="flex items-center gap-2">
            <span className="text-ink-500 w-16 shrink-0">A (rad)</span>
            <input
              type="number"
              step="0.1"
              className="w-24 bg-ink-950 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] text-ink-100 font-mono"
              value={driver.amplitude ?? 1.0}
              onChange={(e) => onChange({ ...driver, amplitude: parseFloat(e.target.value) || 0 })}
              aria-label="Sinusoidal amplitude"
            />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-ink-500 w-16 shrink-0">f (Hz)</span>
            <input
              type="number"
              step="0.1"
              className="w-24 bg-ink-950 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] text-ink-100 font-mono"
              value={driver.frequency ?? 1.0}
              onChange={(e) => onChange({ ...driver, frequency: parseFloat(e.target.value) || 0 })}
              aria-label="Sinusoidal frequency"
            />
          </div>
        </>
      )}

      {driver.type === 'table' && (
        <div className="flex flex-col gap-1">
          <span className="text-ink-500">t, θ pairs (one per line: t θ)</span>
          <textarea
            className="bg-ink-950 border border-ink-800 rounded p-1.5 font-mono text-[11px] text-ink-100 h-20 resize-none"
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

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function AssemblyMotionPanel({
  components = [],
  rendererRef = null,
  projectId = null,
  onToast,
}) {
  const [open, setOpen] = useState(false)
  const [joints, setJoints] = useState([])
  const [driver, setDriver] = useState({ type: 'constant_velocity', velocity: 1.0 })
  const [sim, setSim] = useState({ ...DEFAULT_SIM })
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)     // simulate_motion response
  const [frameIdx, setFrameIdx] = useState(0)
  const [totalFrames, setTotalFrames] = useState(0)
  // Component IDs extracted from the last successful simulation (ordered to
  // match result.trajectories)
  const componentIdsRef = useRef([])

  // ── Joint list mutations ────────────────────────────────────────────────

  function addJoint() {
    setJoints((prev) => [
      ...prev,
      { type: 'revolute', componentA: '', componentB: '', axis: [0, 0, 1] },
    ])
  }

  function updateJoint(idx, next) {
    setJoints((prev) => prev.map((j, i) => (i === idx ? next : j)))
  }

  function removeJoint(idx) {
    setJoints((prev) => prev.filter((_, i) => i !== idx))
  }

  // ── Dispatch ────────────────────────────────────────────────────────────

  const handleRun = useCallback(async () => {
    if (running) return
    setRunning(true)
    setResult(null)
    setFrameIdx(0)
    setTotalFrames(0)

    const payload = buildSimPayload(joints, driver, sim)

    // Extract ordered component ids for frame → transform mapping
    const ids = payload.args.bodies.map((b) => b.name)
    componentIdsRef.current = ids

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
        throw new Error(`simulate_motion failed (${res.status}): ${text}`)
      }

      const data = await res.json()
      if (data.error) throw new Error(data.error)

      // data may be wrapped in an outer `result` key depending on the route
      const inner = data.result ?? data

      if (!inner?.trajectories) throw new Error('No trajectory data returned')

      const nFrames = inner.trajectories?.[0]?.length ?? 0
      setResult(inner)
      setTotalFrames(nFrames)
      setFrameIdx(0)

      // Drive renderer to frame 0
      _applyFrame(inner, 0)
    } catch (err) {
      onToast?.(err.message || 'Motion simulation failed')
    } finally {
      setRunning(false)
    }
  }, [joints, driver, sim, running, onToast])

  // ── Scrubber ────────────────────────────────────────────────────────────

  function _applyFrame(r, idx) {
    if (!rendererRef?.current?.setComponentTransforms) return
    const transforms = extractTransformsAtFrame(componentIdsRef.current, r, idx)
    rendererRef.current.setComponentTransforms(transforms)
  }

  function handleScrub(e) {
    const idx = parseInt(e.target.value, 10)
    setFrameIdx(idx)
    if (result) _applyFrame(result, idx)
  }

  // ── Playback (simple rAF loop) ──────────────────────────────────────────

  const playbackRef = useRef(null)
  const [playing, setPlaying] = useState(false)

  function startPlayback() {
    if (!result || totalFrames === 0) return
    setPlaying(true)
    let f = frameIdx
    function step() {
      f = (f + 1) % totalFrames
      setFrameIdx(f)
      _applyFrame(result, f)
      playbackRef.current = requestAnimationFrame(step)
    }
    playbackRef.current = requestAnimationFrame(step)
  }

  function stopPlayback() {
    setPlaying(false)
    if (playbackRef.current) {
      cancelAnimationFrame(playbackRef.current)
      playbackRef.current = null
    }
  }

  // Stop playback when result changes or component unmounts
  useEffect(() => {
    return () => {
      if (playbackRef.current) cancelAnimationFrame(playbackRef.current)
    }
  }, [])

  useEffect(() => {
    if (result === null) stopPlayback()
  }, [result]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Render ──────────────────────────────────────────────────────────────

  const hasResult = result !== null && totalFrames > 0
  const tAtFrame = result?.t?.[frameIdx] ?? 0

  return (
    <div className="border-t border-ink-800 flex-shrink-0" data-testid="assembly-motion-panel">
      {/* Collapsible header */}
      <div className="flex items-center px-3 py-1.5 gap-2">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex flex-1 items-center gap-1.5 text-[11px] text-ink-400 hover:text-kerf-300 transition-colors"
          aria-expanded={open}
          aria-controls="motion-panel-body"
        >
          {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
          <Zap size={11} className="text-kerf-400 shrink-0" />
          <span className="font-medium">Motion Study</span>
          {hasResult && (
            <span className="ml-auto text-[10px] text-kerf-400 font-mono">
              t={tAtFrame.toFixed(3)} s
            </span>
          )}
        </button>
      </div>

      {open && (
        <div id="motion-panel-body" className="px-3 pb-3 flex flex-col gap-3">

          {/* Joint list */}
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-ink-500 uppercase tracking-wider font-medium">
                Joints
              </span>
              <button
                type="button"
                onClick={addJoint}
                className="flex items-center gap-1 text-[10px] text-kerf-400 hover:text-kerf-300 transition-colors"
                data-testid="add-joint-btn"
              >
                <Plus size={10} />
                Add joint
              </button>
            </div>

            {joints.length === 0 && (
              <p className="text-[11px] text-ink-600 italic">
                No joints defined — add a revolute or prismatic joint to constrain
                component motion.
              </p>
            )}

            {joints.map((j, i) => (
              <JointRow
                key={i}
                joint={j}
                index={i}
                components={components}
                onChange={updateJoint}
                onRemove={removeJoint}
              />
            ))}
          </div>

          {/* Driver */}
          <DriverEditor driver={driver} onChange={setDriver} />

          {/* Sim parameters */}
          <div className="flex gap-3 text-[11px]">
            <div className="flex items-center gap-1.5">
              <span className="text-ink-500">dt (s)</span>
              <input
                type="number"
                step="0.001"
                min="0.0001"
                className="w-20 bg-ink-950 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] text-ink-100 font-mono"
                value={sim.dt}
                onChange={(e) =>
                  setSim((s) => ({ ...s, dt: parseFloat(e.target.value) || DEFAULT_SIM.dt }))
                }
                aria-label="Time step dt"
              />
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-ink-500">t end (s)</span>
              <input
                type="number"
                step="0.5"
                min="0.1"
                className="w-20 bg-ink-950 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] text-ink-100 font-mono"
                value={sim.duration}
                onChange={(e) =>
                  setSim((s) => ({ ...s, duration: parseFloat(e.target.value) || DEFAULT_SIM.duration }))
                }
                aria-label="Simulation end time"
              />
            </div>
          </div>

          {/* Run button */}
          <button
            type="button"
            onClick={handleRun}
            disabled={running}
            className="flex items-center justify-center gap-1.5 rounded bg-kerf-600 hover:bg-kerf-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-[11px] font-medium py-1.5 px-3 transition-colors"
            data-testid="motion-run-btn"
          >
            {running
              ? <><Loader2 size={11} className="animate-spin" />Simulating…</>
              : <><Play size={11} />Run simulation</>
            }
          </button>

          {/* Timeline scrubber */}
          {hasResult && (
            <div className="flex flex-col gap-1.5" data-testid="motion-scrubber">
              <div className="flex items-center justify-between text-[10px] text-ink-500">
                <span>0 s</span>
                <span className="font-mono text-kerf-400">t = {tAtFrame.toFixed(3)} s</span>
                <span>{sim.duration.toFixed(1)} s</span>
              </div>
              <input
                type="range"
                min={0}
                max={totalFrames - 1}
                step={1}
                value={frameIdx}
                onChange={handleScrub}
                className="w-full accent-kerf-400"
                aria-label="Timeline scrubber"
              />
              <div className="flex items-center gap-2 mt-1">
                {playing ? (
                  <button
                    type="button"
                    onClick={stopPlayback}
                    className="flex items-center gap-1 text-[10px] text-amber-400 hover:text-amber-300 transition-colors"
                  >
                    <Square size={10} />Stop
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={startPlayback}
                    className="flex items-center gap-1 text-[10px] text-kerf-400 hover:text-kerf-300 transition-colors"
                  >
                    <Play size={10} />Play
                  </button>
                )}
                <span className="text-[10px] text-ink-600 font-mono">
                  {frameIdx + 1}/{totalFrames} frames
                </span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
