/**
 * SculptStudioPanel.jsx — Blender-parity DCC sculpt workspace.
 *
 * Parity target: Blender Sculpt Mode / ZBrush
 *
 * Capabilities
 * ------------
 * - Brush palette: grab / smooth / inflate / crease / pinch / Taubin-smooth
 * - Strength + radius sliders per-brush (0–1, 0.01–2)
 * - DynaMesh remesh trigger (resolution slider 32–512)
 * - PolyPaint colour stroke controls (colour picker, opacity)
 * - Mesh stats readout: vertex / face count, volume estimate
 * - Last-result preview: affected vertex count, mesh version badge
 *
 * Backend tool calls (via callTool prop)
 * ---------------------------------------
 * - sculpt_apply_brush     (packages/kerf-cad-core/sculpt/tools.py)
 * - sculpt_dynamesh_remesh (packages/kerf-cad-core/sculpt/sculpt_extended_tools.py)
 * - sculpt_polypaint_stroke (packages/kerf-cad-core/sculpt/sculpt_extended_tools.py)
 *
 * Props
 * -----
 * file      {object|null}
 * content   {object|string|null}  — parsed .sculpt session JSON or null
 * projectId {string|null}
 * fileId    {string|null}
 * callTool  {(name:string, args:object) => Promise<any>}  — kerf tool-call
 * onDispatch {(action:object) => void}
 */

import { useState, useCallback, useMemo } from 'react'
import {
  Layers,
  Zap,
  RotateCcw,
  Cpu,
  Palette,
  Activity,
  ChevronDown,
  ChevronRight,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Brush kinds supported by sculpt_apply_brush. */
export const BRUSH_KINDS = [
  { id: 'grab',   label: 'Grab',   icon: '✊', description: 'Translate vertices inside radius' },
  { id: 'smooth', label: 'Smooth', icon: '〰', description: 'Laplacian smooth toward neighbours' },
  { id: 'inflate', label: 'Inflate', icon: '🫧', description: 'Push along per-vertex normal' },
  { id: 'crease', label: 'Crease', icon: '✂', description: 'Pinch toward stroke axis (sharpens)' },
  { id: 'pinch',  label: 'Pinch',  icon: '🤌', description: 'Pull vertices toward brush center' },
]

/** Taubin-smooth is a double-pass smooth (inflate then smooth) at UI level. */
export const TAUBIN_ID = 'taubin'

const FALLOFF_OPTIONS = ['smooth', 'linear', 'constant']

const DEFAULT_MESH = {
  positions: [
    [0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1],
    [1, 1, 0], [1, 0, 1], [0, 1, 1], [1, 1, 1],
  ],
  triangles: [
    [0, 1, 2], [0, 2, 3], [1, 4, 2], [1, 5, 4],
    [2, 4, 6], [4, 7, 6], [3, 5, 0], [5, 1, 0],
    [0, 2, 3], [5, 7, 1], [3, 6, 5], [6, 7, 5],
  ],
}

// ---------------------------------------------------------------------------
// Exported pure helpers — used by the component and directly unit-testable
// ---------------------------------------------------------------------------

/**
 * Build args for the sculpt_apply_brush tool call.
 * @param {{mesh, kind, center, radius, strength, falloff}} opts
 */
export function makeBrushArgs({ mesh, kind, center, radius, strength, falloff }) {
  return {
    positions: mesh.positions,
    triangles: mesh.triangles,
    kind,
    center,
    direction: [0, 1, 0],
    radius,
    strength,
    falloff,
  }
}

/**
 * Build args for the sculpt_dynamesh_remesh tool call.
 * @param {{mesh, resolution}} opts
 */
export function makeRemeshArgs({ mesh, resolution }) {
  return {
    positions: mesh.positions,
    triangles: mesh.triangles,
    target_resolution: resolution,
  }
}

/**
 * Build args for the sculpt_polypaint_stroke tool call.
 * Converts '#rrggbb' hex color to normalized [r, g, b] float array.
 * @param {{mesh, vertexColors, center, radius, polyColor, polyOpacity, falloff}} opts
 */
export function makePolypaintArgs({ mesh, vertexColors, center, radius, polyColor, polyOpacity, falloff }) {
  const hexToRgb = (hex) => {
    const r = parseInt(hex.slice(1, 3), 16) / 255
    const g = parseInt(hex.slice(3, 5), 16) / 255
    const b = parseInt(hex.slice(5, 7), 16) / 255
    return [r, g, b]
  }
  const currentColors = vertexColors ?? mesh.positions.map(() => [0.5, 0.5, 0.5])
  return {
    positions: mesh.positions,
    vertex_colors: currentColors,
    opacity: polyOpacity,
    center,
    radius,
    color: hexToRgb(polyColor),
    falloff,
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

function fmtFloat(v, dp = 4) {
  return typeof v === 'number' ? v.toFixed(dp) : String(v)
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function Section({ title, icon: Icon, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div
      style={{
        borderBottom: '1px solid #1a1d24',
        paddingBottom: open ? 12 : 0,
        marginBottom: 2,
      }}
    >
      <button
        type="button"
        data-testid={`section-${title.toLowerCase().replace(/\s+/g, '-')}`}
        onClick={() => setOpen((o) => !o)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          width: '100%',
          background: 'none',
          border: 'none',
          color: '#b8bfcc',
          fontSize: 11,
          fontWeight: 600,
          letterSpacing: '0.05em',
          textTransform: 'uppercase',
          padding: '8px 0 4px 0',
          cursor: 'pointer',
          textAlign: 'left',
        }}
      >
        {Icon && <Icon size={12} style={{ color: '#5a6275' }} />}
        <span style={{ flex: 1 }}>{title}</span>
        {open ? <ChevronDown size={11} style={{ color: '#5a6275' }} /> : <ChevronRight size={11} style={{ color: '#5a6275' }} />}
      </button>
      {open && <div style={{ paddingLeft: 2 }}>{children}</div>}
    </div>
  )
}

function Slider({ label, value, min, max, step = 0.01, onChange, testId }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
        <span style={{ fontSize: 11, color: '#8a909e' }}>{label}</span>
        <span style={{ fontSize: 11, color: '#e2e6ee', fontFamily: 'monospace' }}>{fmtFloat(value, 2)}</span>
      </div>
      <input
        data-testid={testId}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        style={{ width: '100%', accentColor: '#4e9af1' }}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function SculptStudioPanel({
  file,
  content,
  projectId,
  fileId,
  callTool,
  onDispatch,
}) {
  const parsed = useMemo(() => parseContent(content), [content])

  // Mesh state (positions + triangles)
  const [mesh, setMesh] = useState(() => {
    if (parsed?.positions && parsed?.triangles) return parsed
    return DEFAULT_MESH
  })
  const [meshVersion, setMeshVersion] = useState(0)

  // Brush state
  const [activeBrush, setActiveBrush] = useState('grab')
  const [strength, setStrength] = useState(0.5)
  const [radius, setRadius] = useState(0.3)
  const [falloff, setFalloff] = useState('smooth')
  const [brushCenter, setBrushCenter] = useState([0.5, 0.5, 0.5])

  // DynaMesh remesh
  const [remeshRes, setRemeshRes] = useState(128)

  // PolyPaint
  const [polyColor, setPolyColor] = useState('#ff5500')
  const [polyOpacity, setPolyOpacity] = useState(0.8)
  const [vertexColors, setVertexColors] = useState(null)

  // Status
  const [loading, setLoading] = useState(false)
  const [lastResult, setLastResult] = useState(null)
  const [error, setError] = useState(null)

  // UI accordions
  const [paletteOpen, setPaletteOpen] = useState(true)

  // ---------------------------------------------------------------------------
  // Tool call helpers
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

  // Apply sculpt brush
  const applyBrush = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const kind = activeBrush === TAUBIN_ID ? 'smooth' : activeBrush
      const args = makeBrushArgs({ mesh, kind, center: brushCenter, radius, strength, falloff })
      const result = await doCallTool('sculpt_apply_brush', args)
      if (result?.ok === false) {
        setError(result.reason || 'brush error')
      } else {
        const newMesh = { ...mesh, positions: result.positions }
        setMesh(newMesh)
        setMeshVersion((v) => v + 1)
        setLastResult({
          op: 'apply_brush',
          kind,
          n_affected: result.n_affected,
          version: meshVersion + 1,
        })
        onDispatch?.({ type: 'SCULPT_BRUSH_APPLIED', payload: result })
      }
    } catch (err) {
      setError(String(err?.message ?? err))
    } finally {
      setLoading(false)
    }
  }, [activeBrush, mesh, brushCenter, radius, strength, falloff, meshVersion, doCallTool, onDispatch])

  // Taubin: smooth pass + inflate pass (client-composed, single smooth call)
  const applyTaubin = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      // Pass 1: smooth
      const r1 = await doCallTool('sculpt_apply_brush', {
        positions: mesh.positions,
        triangles: mesh.triangles,
        kind: 'smooth',
        center: brushCenter,
        radius,
        strength: strength * 0.8,
        falloff,
      })
      if (r1?.ok === false) { setError(r1.reason || 'Taubin pass1 error'); return }
      // Pass 2: inflate (slight) to prevent shrinkage
      const r2 = await doCallTool('sculpt_apply_brush', {
        positions: r1.positions,
        triangles: mesh.triangles,
        kind: 'inflate',
        center: brushCenter,
        radius,
        strength: strength * 0.2,
        falloff,
      })
      if (r2?.ok === false) { setError(r2.reason || 'Taubin pass2 error'); return }
      const newMesh = { ...mesh, positions: r2.positions }
      setMesh(newMesh)
      setMeshVersion((v) => v + 1)
      setLastResult({ op: 'taubin_smooth', version: meshVersion + 1 })
      onDispatch?.({ type: 'SCULPT_TAUBIN_APPLIED', payload: r2 })
    } catch (err) {
      setError(String(err?.message ?? err))
    } finally {
      setLoading(false)
    }
  }, [mesh, brushCenter, radius, strength, falloff, meshVersion, doCallTool, onDispatch])

  // DynaMesh remesh
  const doRemesh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await doCallTool('sculpt_dynamesh_remesh', makeRemeshArgs({ mesh, resolution: remeshRes }))
      if (result?.ok === false) {
        setError(result.reason || 'remesh error')
      } else {
        const newMesh = { positions: result.positions, triangles: result.triangles }
        setMesh(newMesh)
        setMeshVersion((v) => v + 1)
        setLastResult({
          op: 'dynamesh_remesh',
          resolution: result.target_resolution,
          n_verts: result.positions.length,
          n_faces: result.triangles.length,
          volume_before: result.volume_before,
          volume_after: result.volume_after,
          version: meshVersion + 1,
        })
        onDispatch?.({ type: 'SCULPT_REMESH_DONE', payload: result })
      }
    } catch (err) {
      setError(String(err?.message ?? err))
    } finally {
      setLoading(false)
    }
  }, [mesh, remeshRes, meshVersion, doCallTool, onDispatch])

  // PolyPaint stroke
  const doPolyPaintStroke = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await doCallTool('sculpt_polypaint_stroke',
        makePolypaintArgs({ mesh, vertexColors, center: brushCenter, radius, polyColor, polyOpacity, falloff })
      )
      if (result?.ok === false) {
        setError(result.reason || 'polypaint error')
      } else {
        setVertexColors(result.vertex_colors)
        setLastResult({ op: 'polypaint_stroke', version: meshVersion })
        onDispatch?.({ type: 'SCULPT_POLYPAINT_APPLIED', payload: result })
      }
    } catch (err) {
      setError(String(err?.message ?? err))
    } finally {
      setLoading(false)
    }
  }, [mesh, vertexColors, brushCenter, radius, polyColor, polyOpacity, falloff, meshVersion, doCallTool, onDispatch])

  // ---------------------------------------------------------------------------
  // Mesh stats
  // ---------------------------------------------------------------------------

  const meshStats = useMemo(() => {
    const V = mesh.positions.length
    const F = mesh.triangles.length
    return { V, F }
  }, [mesh])

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div
      data-testid="sculpt-studio-panel"
      style={{
        display: 'flex',
        height: '100%',
        background: '#0d0f14',
        color: '#e2e6ee',
        fontFamily: 'system-ui, sans-serif',
        fontSize: 12,
        overflow: 'hidden',
      }}
    >
      {/* ── Left panel ─────────────────────────────────────────────────────── */}
      <div
        data-testid="sculpt-left-panel"
        style={{
          width: 240,
          minWidth: 240,
          background: '#0f1115',
          borderRight: '1px solid #1a1d24',
          overflowY: 'auto',
          padding: '10px 12px',
          display: 'flex',
          flexDirection: 'column',
          gap: 0,
        }}
      >
        {/* ── Brush palette ───────────────────────────────────────────────── */}
        <Section title="Brush Palette" icon={Layers}>
          <div
            data-testid="brush-palette"
            style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 4, marginBottom: 8 }}
          >
            {BRUSH_KINDS.map((b) => (
              <button
                key={b.id}
                type="button"
                data-testid={`brush-${b.id}`}
                title={b.description}
                onClick={() => setActiveBrush(b.id)}
                style={{
                  background: activeBrush === b.id ? '#1e3a5f' : '#14171c',
                  border: `1px solid ${activeBrush === b.id ? '#4e9af1' : '#2d323d'}`,
                  borderRadius: 4,
                  color: activeBrush === b.id ? '#4e9af1' : '#8a909e',
                  fontSize: 10,
                  fontWeight: 600,
                  padding: '6px 4px',
                  cursor: 'pointer',
                  textAlign: 'center',
                }}
              >
                <div style={{ fontSize: 14, marginBottom: 2 }}>{b.icon}</div>
                {b.label}
              </button>
            ))}
            {/* Taubin smooth — extra brush kind wired client-side */}
            <button
              type="button"
              data-testid="brush-taubin"
              title="Taubin smooth (λ-μ double-pass anti-shrinkage)"
              onClick={() => setActiveBrush(TAUBIN_ID)}
              style={{
                background: activeBrush === TAUBIN_ID ? '#1e3a5f' : '#14171c',
                border: `1px solid ${activeBrush === TAUBIN_ID ? '#4e9af1' : '#2d323d'}`,
                borderRadius: 4,
                color: activeBrush === TAUBIN_ID ? '#4e9af1' : '#8a909e',
                fontSize: 10,
                fontWeight: 600,
                padding: '6px 4px',
                cursor: 'pointer',
                textAlign: 'center',
              }}
            >
              <div style={{ fontSize: 14, marginBottom: 2 }}>〽</div>
              Taubin
            </button>
          </div>

          <Slider
            label="Strength"
            testId="slider-strength"
            value={strength}
            min={0}
            max={1}
            step={0.01}
            onChange={setStrength}
          />
          <Slider
            label="Radius"
            testId="slider-radius"
            value={radius}
            min={0.01}
            max={2}
            step={0.01}
            onChange={setRadius}
          />

          {/* Falloff */}
          <div style={{ marginBottom: 8 }}>
            <span style={{ fontSize: 11, color: '#8a909e', display: 'block', marginBottom: 4 }}>Falloff</span>
            <div style={{ display: 'flex', gap: 4 }}>
              {FALLOFF_OPTIONS.map((f) => (
                <button
                  key={f}
                  type="button"
                  data-testid={`falloff-${f}`}
                  onClick={() => setFalloff(f)}
                  style={{
                    flex: 1,
                    background: falloff === f ? '#1a2a3a' : '#14171c',
                    border: `1px solid ${falloff === f ? '#4e9af1' : '#2d323d'}`,
                    borderRadius: 3,
                    color: falloff === f ? '#4e9af1' : '#8a909e',
                    fontSize: 9,
                    padding: '3px 0',
                    cursor: 'pointer',
                  }}
                >
                  {f}
                </button>
              ))}
            </div>
          </div>

          {/* Brush center inputs */}
          <div style={{ marginBottom: 6 }}>
            <span style={{ fontSize: 11, color: '#8a909e', display: 'block', marginBottom: 4 }}>Center XYZ</span>
            <div style={{ display: 'flex', gap: 4 }}>
              {['X', 'Y', 'Z'].map((axis, i) => (
                <div key={axis} style={{ flex: 1 }}>
                  <span style={{ fontSize: 9, color: '#5a6275', display: 'block', marginBottom: 2 }}>{axis}</span>
                  <input
                    data-testid={`center-${axis.toLowerCase()}`}
                    type="number"
                    step={0.1}
                    value={brushCenter[i]}
                    onChange={(e) => {
                      const v = parseFloat(e.target.value) || 0
                      setBrushCenter((c) => { const n = [...c]; n[i] = v; return n })
                    }}
                    style={{
                      width: '100%',
                      background: '#14171c',
                      border: '1px solid #2d323d',
                      borderRadius: 3,
                      color: '#e2e6ee',
                      fontSize: 10,
                      padding: '3px 4px',
                      fontFamily: 'monospace',
                    }}
                  />
                </div>
              ))}
            </div>
          </div>

          {/* Apply brush button */}
          <button
            type="button"
            data-testid="btn-apply-brush"
            onClick={activeBrush === TAUBIN_ID ? applyTaubin : applyBrush}
            disabled={loading || !callTool}
            style={{
              width: '100%',
              background: loading ? '#1a2030' : '#1e3a5f',
              border: '1px solid #4e9af1',
              borderRadius: 4,
              color: '#4e9af1',
              fontSize: 11,
              fontWeight: 600,
              padding: '7px 0',
              cursor: loading ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 5,
            }}
          >
            <Zap size={11} />
            {loading ? 'Applying…' : `Apply ${activeBrush === TAUBIN_ID ? 'Taubin' : activeBrush.charAt(0).toUpperCase() + activeBrush.slice(1)}`}
          </button>
        </Section>

        {/* ── DynaMesh ────────────────────────────────────────────────────── */}
        <Section title="DynaMesh Remesh" icon={Cpu} defaultOpen={true}>
          <Slider
            label="Resolution"
            testId="slider-remesh-res"
            value={remeshRes}
            min={32}
            max={512}
            step={32}
            onChange={setRemeshRes}
          />
          <button
            type="button"
            data-testid="btn-remesh"
            onClick={doRemesh}
            disabled={loading || !callTool}
            style={{
              width: '100%',
              background: loading ? '#1a2030' : '#1a2a1a',
              border: '1px solid #4ecf6f',
              borderRadius: 4,
              color: '#4ecf6f',
              fontSize: 11,
              fontWeight: 600,
              padding: '7px 0',
              cursor: loading ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 5,
              marginTop: 4,
            }}
          >
            <RotateCcw size={11} />
            {loading ? 'Remeshing…' : `Remesh @${remeshRes}`}
          </button>
        </Section>

        {/* ── PolyPaint ───────────────────────────────────────────────────── */}
        <Section title="PolyPaint" icon={Palette} defaultOpen={true}>
          <div style={{ marginBottom: 8 }}>
            <span style={{ fontSize: 11, color: '#8a909e', display: 'block', marginBottom: 4 }}>Stroke Colour</span>
            <input
              data-testid="polypaint-color"
              type="color"
              value={polyColor}
              onChange={(e) => setPolyColor(e.target.value)}
              style={{ width: '100%', height: 28, border: 'none', cursor: 'pointer', borderRadius: 3 }}
            />
          </div>
          <Slider
            label="Opacity"
            testId="slider-polypaint-opacity"
            value={polyOpacity}
            min={0}
            max={1}
            step={0.01}
            onChange={setPolyOpacity}
          />
          <button
            type="button"
            data-testid="btn-polypaint-stroke"
            onClick={doPolyPaintStroke}
            disabled={loading || !callTool}
            style={{
              width: '100%',
              background: loading ? '#1a2030' : '#2a1a2a',
              border: '1px solid #b36ff1',
              borderRadius: 4,
              color: '#b36ff1',
              fontSize: 11,
              fontWeight: 600,
              padding: '7px 0',
              cursor: loading ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 5,
            }}
          >
            <Palette size={11} />
            {loading ? 'Painting…' : 'Paint Stroke'}
          </button>
        </Section>
      </div>

      {/* ── Main area ──────────────────────────────────────────────────────── */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        {/* Header */}
        <div
          style={{
            height: 36,
            background: '#0f1115',
            borderBottom: '1px solid #1a1d24',
            display: 'flex',
            alignItems: 'center',
            padding: '0 14px',
            gap: 10,
          }}
        >
          <Activity size={13} style={{ color: '#4e9af1' }} />
          <span style={{ fontSize: 12, fontWeight: 600, color: '#e2e6ee' }}>
            Sculpt Studio
          </span>
          <span
            style={{
              marginLeft: 'auto',
              fontSize: 10,
              background: '#1a2030',
              border: '1px solid #2d3a4a',
              borderRadius: 3,
              color: '#4e9af1',
              padding: '1px 6px',
              fontFamily: 'monospace',
            }}
          >
            v{meshVersion}
          </span>
          {file?.name && (
            <span style={{ fontSize: 10, color: '#5a6275' }}>{file.name}</span>
          )}
        </div>

        {/* Viewport placeholder + mesh stats */}
        <div
          data-testid="sculpt-viewport"
          style={{
            flex: 1,
            background: '#0a0c10',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            position: 'relative',
            overflow: 'hidden',
          }}
        >
          {/* Mesh stats overlay */}
          <div
            data-testid="mesh-stats"
            style={{
              position: 'absolute',
              top: 12,
              left: 12,
              background: 'rgba(15,17,21,0.85)',
              border: '1px solid #1a1d24',
              borderRadius: 4,
              padding: '8px 12px',
              display: 'flex',
              flexDirection: 'column',
              gap: 3,
            }}
          >
            <span style={{ fontSize: 10, color: '#5a6275', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Mesh Stats</span>
            <span style={{ fontSize: 11, color: '#b8bfcc' }}>
              Vertices: <strong style={{ color: '#e2e6ee' }}>{meshStats.V.toLocaleString()}</strong>
            </span>
            <span style={{ fontSize: 11, color: '#b8bfcc' }}>
              Faces: <strong style={{ color: '#e2e6ee' }}>{meshStats.F.toLocaleString()}</strong>
            </span>
            {vertexColors && (
              <span style={{ fontSize: 10, color: '#b36ff1' }}>PolyPaint active</span>
            )}
          </div>

          {/* 3D placeholder — real GPU viewport requires Three.js integration */}
          <div style={{ textAlign: 'center', color: '#2d323d' }}>
            <div style={{ fontSize: 48, marginBottom: 8, opacity: 0.3 }}>⬡</div>
            <div style={{ fontSize: 11 }}>3D Sculpt Viewport</div>
            <div style={{ fontSize: 10, marginTop: 4, opacity: 0.6 }}>
              {meshStats.V}V · {meshStats.F}F
            </div>
          </div>

          {/* Last result overlay */}
          {lastResult && (
            <div
              data-testid="last-result"
              style={{
                position: 'absolute',
                bottom: 12,
                right: 12,
                background: 'rgba(15,17,21,0.92)',
                border: '1px solid #1a1d24',
                borderRadius: 4,
                padding: '6px 10px',
                fontSize: 10,
                color: '#8a909e',
                maxWidth: 200,
              }}
            >
              <div style={{ color: '#4e9af1', fontWeight: 600, marginBottom: 3 }}>
                Last: {lastResult.op}
              </div>
              {lastResult.n_affected != null && (
                <div>Affected: {lastResult.n_affected} verts</div>
              )}
              {lastResult.n_verts != null && (
                <div>{lastResult.n_verts}V / {lastResult.n_faces}F after remesh</div>
              )}
              <div>Mesh v{lastResult.version}</div>
            </div>
          )}
        </div>

        {/* Error bar */}
        {error && (
          <div
            data-testid="sculpt-error"
            style={{
              background: '#2a1010',
              border: '1px solid #7f2020',
              borderRadius: 0,
              padding: '6px 12px',
              fontSize: 11,
              color: '#f16f8e',
            }}
          >
            Error: {error}
          </div>
        )}
      </div>
    </div>
  )
}
