/**
 * AnimationTimelinePanel.jsx — Blender-parity DCC animation workspace.
 *
 * Parity target: Blender NLA Editor / F-Curve editor + Pose Mode
 *
 * Capabilities
 * ------------
 * - Keyframe timeline: add / remove keys per-channel with bezier handle visualization
 * - FCurve SVG chart: value-vs-time polyline for all channels
 * - Play/pause/scrub: evaluates clip at each tick via animation_evaluate_clip
 * - Armature pose list: named bones, per-bone rotation display
 * - IK solver toggle: CCD / FABRIK, target input, run solve
 * - animation_apply_pose: apply skeleton rotations + show world matrices
 *
 * Backend tool calls (via callTool prop)
 * ---------------------------------------
 * - animation_evaluate_clip  (packages/kerf-cad-core/animation/tools.py)
 * - animation_solve_ik       (packages/kerf-cad-core/animation/tools.py)
 * - animation_apply_pose     (packages/kerf-cad-core/animation/tools.py)
 *
 * Props
 * -----
 * file      {object|null}
 * content   {object|string|null}  — parsed .anim clip JSON or null
 * projectId {string|null}
 * fileId    {string|null}
 * callTool  {(name:string, args:object) => Promise<any>}
 * onDispatch {(action:object) => void}
 */

import { useState, useCallback, useMemo, useEffect, useRef } from 'react'
import {
  Play,
  Pause,
  SkipBack,
  SkipForward,
  Plus,
  Trash2,
  Activity,
  ChevronDown,
  ChevronRight,
  Zap,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Default clip (one channel, two keyframes)
// ---------------------------------------------------------------------------

export const DEFAULT_CLIP = {
  name: 'Take001',
  duration: 2.0,
  fcurves: {
    'location.x': [
      { t: 0.0, value: 0, interpolation: 'bezier', tangent_in: [0, 0], tangent_out: [0.5, 0] },
      { t: 2.0, value: 1, interpolation: 'bezier', tangent_in: [0.5, 0], tangent_out: [0, 0] },
    ],
    'location.y': [
      { t: 0.0, value: 0, interpolation: 'linear' },
      { t: 1.0, value: 0.5, interpolation: 'linear' },
      { t: 2.0, value: 0, interpolation: 'linear' },
    ],
  },
}

export const DEFAULT_BONES = [
  { name: 'root', head: [0, 0, 0], tail: [0, 1, 0], parent: null },
  { name: 'forearm', head: [0, 1, 0], tail: [0, 2, 0], parent: 'root' },
  { name: 'hand', head: [0, 2, 0], tail: [0, 2.5, 0], parent: 'forearm' },
]

// ---------------------------------------------------------------------------
// Exported pure helpers — used by the component and directly unit-testable
// ---------------------------------------------------------------------------

/**
 * Build args for animation_solve_ik.
 * @param {{bones, ikTarget, ikAlgorithm}} opts
 */
export function makeIKArgs({ bones, ikTarget, ikAlgorithm }) {
  return {
    bones,
    chain: bones.map((b) => b.name),
    target: ikTarget,
    algorithm: ikAlgorithm,
    max_iter: 30,
    tol: 1e-4,
  }
}

/**
 * Build args for animation_apply_pose.
 * @param {{bones, rotations}} opts
 */
export function makeApplyPoseArgs({ bones, rotations }) {
  return { bones, rotations }
}

/**
 * Build args for animation_evaluate_clip.
 * @param {{clip, evalTime}} opts
 */
export function makeEvaluateClipArgs({ clip, evalTime }) {
  return {
    name: clip.name,
    duration: clip.duration,
    fcurves: clip.fcurves,
    eval_time: evalTime,
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function parseContent(content) {
  if (!content) return null
  if (typeof content === 'object') return content
  try { return JSON.parse(content) } catch { return null }
}

function fmtT(t) { return typeof t === 'number' ? t.toFixed(3) : String(t) }
function fmtV(v) {
  if (typeof v === 'number') return v.toFixed(4)
  if (Array.isArray(v)) return `[${v.map((x) => fmtV(x)).join(', ')}]`
  return String(v)
}

// ---------------------------------------------------------------------------
// FCurve SVG Chart
// ---------------------------------------------------------------------------

function FCurveChart({ fcurves, evalTime, duration, width = 320, height = 120 }) {
  const MARGIN = { top: 8, right: 8, bottom: 18, left: 32 }
  const W = width - MARGIN.left - MARGIN.right
  const H = height - MARGIN.top - MARGIN.bottom

  // Compute data bounds
  const allValues = Object.values(fcurves)
    .flat()
    .map((kf) => (typeof kf.value === 'number' ? kf.value : 0))
  const minV = allValues.length ? Math.min(...allValues) : 0
  const maxV = allValues.length ? Math.max(...allValues) : 1
  const rangeV = maxV - minV || 1

  const toX = (t) => (t / (duration || 1)) * W
  const toY = (v) => H - ((v - minV) / rangeV) * H

  const COLORS = ['#4e9af1', '#f1a94e', '#6fe06f', '#f16f8e', '#b36ff1']

  return (
    <svg
      data-testid="fcurve-chart"
      width={width}
      height={height}
      style={{ display: 'block', fontFamily: 'monospace' }}
    >
      <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
        {/* Grid lines */}
        {[0, 0.25, 0.5, 0.75, 1].map((frac) => (
          <line
            key={frac}
            x1={0} y1={H * frac} x2={W} y2={H * frac}
            stroke="#1a1d24" strokeWidth={1}
          />
        ))}
        {/* Axes */}
        <line x1={0} y1={0} x2={0} y2={H} stroke="#2d323d" strokeWidth={1} />
        <line x1={0} y1={H} x2={W} y2={H} stroke="#2d323d" strokeWidth={1} />

        {/* Curves */}
        {Object.entries(fcurves).map(([ch, kfs], ci) => {
          const color = COLORS[ci % COLORS.length]
          const pts = kfs
            .filter((kf) => typeof kf.value === 'number')
            .sort((a, b) => a.t - b.t)
            .map((kf) => `${toX(kf.t).toFixed(1)},${toY(kf.value).toFixed(1)}`)
          return (
            <g key={ch}>
              {pts.length > 1 && (
                <polyline
                  points={pts.join(' ')}
                  fill="none"
                  stroke={color}
                  strokeWidth={1.5}
                  opacity={0.8}
                />
              )}
              {/* Key dots */}
              {kfs
                .filter((kf) => typeof kf.value === 'number')
                .map((kf, ki) => (
                  <circle
                    key={ki}
                    cx={toX(kf.t)}
                    cy={toY(kf.value)}
                    r={3}
                    fill={color}
                    opacity={0.9}
                  />
                ))}
              {/* Legend label */}
              <text
                x={W + 2}
                y={kfs[0] ? toY(typeof kfs[0].value === 'number' ? kfs[0].value : 0) : 0}
                fontSize={7}
                fill={color}
                dominantBaseline="middle"
              >
                {ch}
              </text>
            </g>
          )
        })}

        {/* Playhead */}
        {evalTime != null && (
          <line
            x1={toX(evalTime)}
            y1={0}
            x2={toX(evalTime)}
            y2={H}
            stroke="#f1ec6f"
            strokeWidth={1.5}
            strokeDasharray="3,2"
          />
        )}

        {/* Time axis labels */}
        {[0, duration / 2, duration].map((t) => (
          <text key={t} x={toX(t)} y={H + 13} fontSize={7} fill="#5a6275" textAnchor="middle">
            {fmtT(t)}s
          </text>
        ))}
      </g>
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Section accordion
// ---------------------------------------------------------------------------

function Section({ title, icon: Icon, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div style={{ borderBottom: '1px solid #1a1d24', paddingBottom: open ? 10 : 0, marginBottom: 2 }}>
      <button
        type="button"
        data-testid={`section-${title.toLowerCase().replace(/\s+/g, '-')}`}
        onClick={() => setOpen((o) => !o)}
        style={{
          display: 'flex', alignItems: 'center', gap: 6, width: '100%',
          background: 'none', border: 'none', color: '#b8bfcc',
          fontSize: 11, fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase',
          padding: '8px 0 4px 0', cursor: 'pointer', textAlign: 'left',
        }}
      >
        {Icon && <Icon size={12} style={{ color: '#5a6275' }} />}
        <span style={{ flex: 1 }}>{title}</span>
        {open ? <ChevronDown size={11} style={{ color: '#5a6275' }} /> : <ChevronRight size={11} style={{ color: '#5a6275' }} />}
      </button>
      {open && <div>{children}</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function AnimationTimelinePanel({
  file,
  content,
  projectId,
  fileId,
  callTool,
  onDispatch,
}) {
  const parsed = useMemo(() => parseContent(content), [content])

  // Clip state
  const [clip, setClip] = useState(() => {
    if (parsed?.fcurves) return parsed
    return DEFAULT_CLIP
  })

  // Playback
  const [evalTime, setEvalTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [playbackRate, setPlaybackRate] = useState(1)
  const animRef = useRef(null)
  const lastTickRef = useRef(null)

  // Evaluated channel values
  const [channelValues, setChannelValues] = useState({})

  // IK solver
  const [ikAlgorithm, setIkAlgorithm] = useState('fabrik')
  const [ikEnabled, setIkEnabled] = useState(false)
  const [ikTarget, setIkTarget] = useState([0, 1.5, 0])
  const [ikRotations, setIkRotations] = useState({})

  // Armature
  const [bones, setBones] = useState(() => {
    if (parsed?.bones) return parsed.bones
    return DEFAULT_BONES
  })
  const [worldMatrices, setWorldMatrices] = useState([])

  // Loading/error
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // New keyframe form
  const [newKfChannel, setNewKfChannel] = useState(Object.keys(clip.fcurves)[0] || 'location.x')
  const [newKfTime, setNewKfTime] = useState(0)
  const [newKfValue, setNewKfValue] = useState(0)
  const [newKfInterp, setNewKfInterp] = useState('bezier')

  // ---------------------------------------------------------------------------
  // Tool helpers
  // ---------------------------------------------------------------------------

  const doCallTool = useCallback(
    async (name, args) => {
      if (!callTool) throw new Error('callTool prop not provided')
      const raw = await callTool(name, args)
      if (typeof raw === 'string') return JSON.parse(raw)
      return raw
    },
    [callTool],
  )

  // Evaluate clip at current time
  const evaluateClip = useCallback(
    async (t) => {
      if (!callTool) return
      try {
        const result = await doCallTool('animation_evaluate_clip', makeEvaluateClipArgs({ clip, evalTime: t }))
        if (result?.ok !== false) {
          setChannelValues(result.channels || {})
          onDispatch?.({ type: 'ANIM_CLIP_EVALUATED', payload: result })
        }
      } catch (err) {
        // Silently fail during playback to avoid spamming errors
      }
    },
    [clip, callTool, doCallTool, onDispatch],
  )

  // Playback loop
  useEffect(() => {
    if (!playing) {
      if (animRef.current) cancelAnimationFrame(animRef.current)
      return
    }
    const tick = (ts) => {
      if (lastTickRef.current == null) lastTickRef.current = ts
      const dt = (ts - lastTickRef.current) / 1000
      lastTickRef.current = ts
      setEvalTime((prev) => {
        const next = prev + dt * playbackRate
        if (next >= clip.duration) {
          setPlaying(false)
          return clip.duration
        }
        return next
      })
      animRef.current = requestAnimationFrame(tick)
    }
    animRef.current = requestAnimationFrame(tick)
    return () => { if (animRef.current) cancelAnimationFrame(animRef.current) }
  }, [playing, playbackRate, clip.duration])

  // Evaluate whenever evalTime changes (debounced by rAF granularity)
  useEffect(() => {
    evaluateClip(evalTime)
  }, [evalTime]) // eslint-disable-line react-hooks/exhaustive-deps

  // IK solve
  const solveIK = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await doCallTool('animation_solve_ik', makeIKArgs({ bones, ikTarget, ikAlgorithm }))
      if (result?.ok === false) {
        setError(result.reason || 'IK error')
      } else {
        setIkRotations(result.rotations || {})
        onDispatch?.({ type: 'ANIM_IK_SOLVED', payload: result })
        // Auto-apply pose
        await applyPose(result.rotations || {})
      }
    } catch (err) {
      setError(String(err?.message ?? err))
    } finally {
      setLoading(false)
    }
  }, [bones, ikTarget, ikAlgorithm, doCallTool, onDispatch])

  // Apply pose
  const applyPose = useCallback(
    async (rotations) => {
      try {
        const result = await doCallTool('animation_apply_pose', makeApplyPoseArgs({ bones, rotations }))
        if (result?.ok !== false) {
          setWorldMatrices(result.world_matrices || [])
          onDispatch?.({ type: 'ANIM_POSE_APPLIED', payload: result })
        }
      } catch (err) {
        setError(String(err?.message ?? err))
      }
    },
    [bones, doCallTool, onDispatch],
  )

  // Add keyframe
  const addKeyframe = useCallback(() => {
    const ch = newKfChannel
    const kf = { t: newKfTime, value: newKfValue, interpolation: newKfInterp }
    setClip((prev) => {
      const prevKeys = prev.fcurves[ch] || []
      const sorted = [...prevKeys.filter((k) => k.t !== newKfTime), kf].sort((a, b) => a.t - b.t)
      return { ...prev, fcurves: { ...prev.fcurves, [ch]: sorted } }
    })
  }, [newKfChannel, newKfTime, newKfValue, newKfInterp])

  // Remove keyframe
  const removeKeyframe = useCallback((ch, t) => {
    setClip((prev) => ({
      ...prev,
      fcurves: {
        ...prev.fcurves,
        [ch]: (prev.fcurves[ch] || []).filter((k) => k.t !== t),
      },
    }))
  }, [])

  // Scrub to time
  const scrub = useCallback((t) => {
    setEvalTime(t)
    lastTickRef.current = null
  }, [])

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const channels = Object.keys(clip.fcurves)

  return (
    <div
      data-testid="animation-timeline-panel"
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        background: '#0d0f14',
        color: '#e2e6ee',
        fontFamily: 'system-ui, sans-serif',
        fontSize: 12,
        overflow: 'hidden',
      }}
    >
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div
        style={{
          height: 36,
          background: '#0f1115',
          borderBottom: '1px solid #1a1d24',
          display: 'flex',
          alignItems: 'center',
          padding: '0 14px',
          gap: 10,
          flexShrink: 0,
        }}
      >
        <Activity size={13} style={{ color: '#f1a94e' }} />
        <span style={{ fontSize: 12, fontWeight: 600, color: '#e2e6ee' }}>
          Animation Timeline
        </span>
        <span style={{ fontSize: 10, color: '#5a6275', fontFamily: 'monospace' }}>
          {clip.name} · {clip.duration}s
        </span>
        {file?.name && (
          <span style={{ marginLeft: 'auto', fontSize: 10, color: '#5a6275' }}>{file.name}</span>
        )}
      </div>

      {/* ── Main split ─────────────────────────────────────────────────────── */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Left panel: controls */}
        <div
          data-testid="anim-left-panel"
          style={{
            width: 240,
            minWidth: 240,
            background: '#0f1115',
            borderRight: '1px solid #1a1d24',
            overflowY: 'auto',
            padding: '8px 12px',
          }}
        >
          {/* ── Playback ──────────────────────────────────────────────────── */}
          <Section title="Playback" icon={Play}>
            {/* Transport buttons */}
            <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
              <button
                type="button"
                data-testid="btn-skip-back"
                onClick={() => { scrub(0); setPlaying(false) }}
                style={iconBtnStyle}
                title="Rewind to start"
              >
                <SkipBack size={12} />
              </button>
              <button
                type="button"
                data-testid="btn-play-pause"
                onClick={() => {
                  if (evalTime >= clip.duration) scrub(0)
                  setPlaying((p) => !p)
                  lastTickRef.current = null
                }}
                style={{ ...iconBtnStyle, flex: 1, background: '#1e3a5f', borderColor: '#4e9af1', color: '#4e9af1' }}
              >
                {playing ? <Pause size={12} /> : <Play size={12} />}
                <span style={{ fontSize: 10, marginLeft: 4 }}>{playing ? 'Pause' : 'Play'}</span>
              </button>
              <button
                type="button"
                data-testid="btn-skip-forward"
                onClick={() => { scrub(clip.duration); setPlaying(false) }}
                style={iconBtnStyle}
                title="Skip to end"
              >
                <SkipForward size={12} />
              </button>
            </div>

            {/* Scrub slider */}
            <div style={{ marginBottom: 6 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                <span style={{ fontSize: 10, color: '#8a909e' }}>Time</span>
                <span style={{ fontSize: 10, color: '#e2e6ee', fontFamily: 'monospace' }}>
                  {evalTime.toFixed(3)}s / {clip.duration}s
                </span>
              </div>
              <input
                data-testid="scrub-slider"
                type="range"
                min={0}
                max={clip.duration}
                step={0.001}
                value={evalTime}
                onChange={(e) => scrub(parseFloat(e.target.value))}
                style={{ width: '100%', accentColor: '#f1a94e' }}
              />
            </div>

            {/* Evaluated values */}
            {Object.keys(channelValues).length > 0 && (
              <div
                data-testid="channel-values"
                style={{
                  background: '#14171c',
                  border: '1px solid #2d323d',
                  borderRadius: 4,
                  padding: '6px 8px',
                  marginBottom: 6,
                }}
              >
                <div style={{ fontSize: 9, color: '#5a6275', fontWeight: 600, marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Evaluated</div>
                {Object.entries(channelValues).map(([ch, val]) => (
                  <div key={ch} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, marginBottom: 2 }}>
                    <span style={{ color: '#8a909e' }}>{ch}</span>
                    <span style={{ color: '#e2e6ee', fontFamily: 'monospace' }}>{fmtV(val)}</span>
                  </div>
                ))}
              </div>
            )}
          </Section>

          {/* ── Keyframe editor ───────────────────────────────────────────── */}
          <Section title="Add Keyframe" icon={Plus}>
            <div style={{ marginBottom: 6 }}>
              <span style={{ fontSize: 10, color: '#8a909e', display: 'block', marginBottom: 3 }}>Channel</span>
              <input
                data-testid="new-kf-channel"
                type="text"
                value={newKfChannel}
                onChange={(e) => setNewKfChannel(e.target.value)}
                style={inputStyle}
              />
            </div>
            <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
              <div style={{ flex: 1 }}>
                <span style={{ fontSize: 10, color: '#8a909e', display: 'block', marginBottom: 3 }}>Time (s)</span>
                <input
                  data-testid="new-kf-time"
                  type="number"
                  step={0.1}
                  value={newKfTime}
                  onChange={(e) => setNewKfTime(parseFloat(e.target.value) || 0)}
                  style={inputStyle}
                />
              </div>
              <div style={{ flex: 1 }}>
                <span style={{ fontSize: 10, color: '#8a909e', display: 'block', marginBottom: 3 }}>Value</span>
                <input
                  data-testid="new-kf-value"
                  type="number"
                  step={0.1}
                  value={newKfValue}
                  onChange={(e) => setNewKfValue(parseFloat(e.target.value) || 0)}
                  style={inputStyle}
                />
              </div>
            </div>
            <div style={{ marginBottom: 6 }}>
              <span style={{ fontSize: 10, color: '#8a909e', display: 'block', marginBottom: 3 }}>Interpolation</span>
              <div style={{ display: 'flex', gap: 3 }}>
                {['step', 'linear', 'bezier'].map((interp) => (
                  <button
                    key={interp}
                    type="button"
                    data-testid={`interp-${interp}`}
                    onClick={() => setNewKfInterp(interp)}
                    style={{
                      flex: 1,
                      background: newKfInterp === interp ? '#1a2a3a' : '#14171c',
                      border: `1px solid ${newKfInterp === interp ? '#4e9af1' : '#2d323d'}`,
                      borderRadius: 3,
                      color: newKfInterp === interp ? '#4e9af1' : '#8a909e',
                      fontSize: 9,
                      padding: '3px 0',
                      cursor: 'pointer',
                    }}
                  >
                    {interp}
                  </button>
                ))}
              </div>
            </div>
            <button
              type="button"
              data-testid="btn-add-keyframe"
              onClick={addKeyframe}
              style={{
                width: '100%',
                background: '#1a2a1a',
                border: '1px solid #4ecf6f',
                borderRadius: 4,
                color: '#4ecf6f',
                fontSize: 11,
                fontWeight: 600,
                padding: '6px 0',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 5,
              }}
            >
              <Plus size={11} />
              Add Keyframe
            </button>
          </Section>

          {/* ── IK Solver ─────────────────────────────────────────────────── */}
          <Section title="IK Solver" icon={Zap}>
            <div style={{ marginBottom: 6 }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 11, color: '#b8bfcc' }}>
                <input
                  data-testid="ik-enabled-toggle"
                  type="checkbox"
                  checked={ikEnabled}
                  onChange={(e) => setIkEnabled(e.target.checked)}
                  style={{ accentColor: '#4e9af1' }}
                />
                IK Enabled
              </label>
            </div>
            <div style={{ marginBottom: 6 }}>
              <span style={{ fontSize: 10, color: '#8a909e', display: 'block', marginBottom: 3 }}>Algorithm</span>
              <div style={{ display: 'flex', gap: 4 }}>
                {['ccd', 'fabrik'].map((alg) => (
                  <button
                    key={alg}
                    type="button"
                    data-testid={`ik-algo-${alg}`}
                    onClick={() => setIkAlgorithm(alg)}
                    style={{
                      flex: 1,
                      background: ikAlgorithm === alg ? '#1e3a5f' : '#14171c',
                      border: `1px solid ${ikAlgorithm === alg ? '#4e9af1' : '#2d323d'}`,
                      borderRadius: 3,
                      color: ikAlgorithm === alg ? '#4e9af1' : '#8a909e',
                      fontSize: 10,
                      fontWeight: ikAlgorithm === alg ? 700 : 400,
                      padding: '4px 0',
                      cursor: 'pointer',
                      textTransform: 'uppercase',
                    }}
                  >
                    {alg}
                  </button>
                ))}
              </div>
            </div>
            {/* IK Target */}
            <div style={{ marginBottom: 6 }}>
              <span style={{ fontSize: 10, color: '#8a909e', display: 'block', marginBottom: 3 }}>Target XYZ</span>
              <div style={{ display: 'flex', gap: 4 }}>
                {['X', 'Y', 'Z'].map((axis, i) => (
                  <div key={axis} style={{ flex: 1 }}>
                    <span style={{ fontSize: 9, color: '#5a6275', display: 'block', marginBottom: 2 }}>{axis}</span>
                    <input
                      data-testid={`ik-target-${axis.toLowerCase()}`}
                      type="number"
                      step={0.1}
                      value={ikTarget[i]}
                      onChange={(e) => {
                        const v = parseFloat(e.target.value) || 0
                        setIkTarget((t) => { const n = [...t]; n[i] = v; return n })
                      }}
                      style={{ ...inputStyle, fontFamily: 'monospace' }}
                    />
                  </div>
                ))}
              </div>
            </div>
            <button
              type="button"
              data-testid="btn-solve-ik"
              onClick={solveIK}
              disabled={loading || !callTool}
              style={{
                width: '100%',
                background: loading ? '#1a2030' : ikEnabled ? '#1e3a5f' : '#14171c',
                border: `1px solid ${ikEnabled ? '#4e9af1' : '#2d323d'}`,
                borderRadius: 4,
                color: ikEnabled ? '#4e9af1' : '#5a6275',
                fontSize: 11,
                fontWeight: 600,
                padding: '6px 0',
                cursor: loading || !ikEnabled ? 'not-allowed' : 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 5,
              }}
            >
              <Zap size={11} />
              {loading ? 'Solving…' : 'Solve IK'}
            </button>
          </Section>
        </div>

        {/* ── Right: FCurve + Keyframes + Armature ───────────────────────── */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* FCurve chart */}
          <div
            data-testid="fcurve-chart-container"
            style={{
              background: '#0a0c10',
              borderBottom: '1px solid #1a1d24',
              padding: '10px 14px',
              flexShrink: 0,
            }}
          >
            <div style={{ fontSize: 10, color: '#5a6275', marginBottom: 6, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              FCurves
            </div>
            <FCurveChart
              fcurves={clip.fcurves}
              evalTime={evalTime}
              duration={clip.duration}
              width={500}
              height={130}
            />
          </div>

          {/* Keyframe list */}
          <div
            data-testid="keyframe-list"
            style={{
              flex: 1,
              overflowY: 'auto',
              padding: '8px 14px',
            }}
          >
            <div style={{ fontSize: 10, color: '#5a6275', marginBottom: 6, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Keyframes
            </div>
            {channels.map((ch) => (
              <div key={ch} style={{ marginBottom: 10 }}>
                <div style={{ fontSize: 10, color: '#f1a94e', fontWeight: 600, marginBottom: 4 }}>{ch}</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {(clip.fcurves[ch] || []).map((kf, ki) => (
                    <div
                      key={ki}
                      data-testid={`keyframe-${ch}-${ki}`}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        background: Math.abs(kf.t - evalTime) < 0.05 ? '#1a2a3a' : '#14171c',
                        border: '1px solid #2d323d',
                        borderRadius: 3,
                        padding: '3px 8px',
                      }}
                    >
                      <span style={{ fontSize: 10, fontFamily: 'monospace', color: '#b8bfcc', width: 50 }}>
                        t={fmtT(kf.t)}
                      </span>
                      <span style={{ fontSize: 10, fontFamily: 'monospace', color: '#e2e6ee', flex: 1 }}>
                        {fmtV(kf.value)}
                      </span>
                      <span style={{ fontSize: 9, color: '#5a6275' }}>{kf.interpolation || 'linear'}</span>
                      <button
                        type="button"
                        data-testid={`remove-kf-${ch}-${ki}`}
                        onClick={() => removeKeyframe(ch, kf.t)}
                        style={{
                          background: 'none',
                          border: 'none',
                          cursor: 'pointer',
                          color: '#5a6275',
                          padding: 0,
                          display: 'flex',
                          alignItems: 'center',
                        }}
                        title="Remove keyframe"
                      >
                        <Trash2 size={10} />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            ))}

            {/* Armature pose list */}
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 10, color: '#5a6275', marginBottom: 6, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Armature Bones
              </div>
              {bones.map((bone, bi) => (
                <div
                  key={bone.name}
                  data-testid={`bone-row-${bone.name}`}
                  style={{
                    background: '#14171c',
                    border: '1px solid #2d323d',
                    borderRadius: 3,
                    padding: '5px 8px',
                    marginBottom: 3,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                  }}
                >
                  <span style={{ fontSize: 10, fontWeight: 600, color: '#b8bfcc', width: 70 }}>{bone.name}</span>
                  <span style={{ fontSize: 9, color: '#5a6275', flex: 1 }}>
                    parent: {bone.parent || '—'}
                  </span>
                  {ikRotations[bone.name] && (
                    <span style={{ fontSize: 9, color: '#4e9af1', fontFamily: 'monospace' }}>IK</span>
                  )}
                  {worldMatrices[bi] && (
                    <span style={{ fontSize: 9, color: '#6fe06f', fontFamily: 'monospace' }}>posed</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Error bar */}
      {error && (
        <div
          data-testid="anim-error"
          style={{
            background: '#2a1010',
            border: '1px solid #7f2020',
            padding: '6px 14px',
            fontSize: 11,
            color: '#f16f8e',
            flexShrink: 0,
          }}
        >
          Error: {error}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Shared micro-styles
// ---------------------------------------------------------------------------

const iconBtnStyle = {
  background: '#14171c',
  border: '1px solid #2d323d',
  borderRadius: 4,
  color: '#8a909e',
  cursor: 'pointer',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  padding: '5px 8px',
}

const inputStyle = {
  width: '100%',
  background: '#14171c',
  border: '1px solid #2d323d',
  borderRadius: 3,
  color: '#e2e6ee',
  fontSize: 11,
  padding: '4px 6px',
  boxSizing: 'border-box',
}
