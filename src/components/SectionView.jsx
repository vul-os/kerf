// SectionView — 2D SVG renderer for `.section` files.
//
// A `.section` file is the output of a `feature_section` op: a compound of
// intersection edges produced by BRepAlgoAPI_Section (a 2D cross-section
// outline of a solid).  Its JSON content is the same `.feature` tree that
// produced the section compound — the worker already stored the edge geometry
// in the mesh result; SectionView re-runs the tree and renders the edge
// segments in an SVG viewport.
//
// Layout:
//   * toolbar  — zoom, reset, DXF export stub
//   * center   — SVG canvas: all edges projected to the section plane's 2D UV
//                coordinate frame (u = plane's local X, v = plane's local Y)
//
// Data flow:
//   SectionView receives `parsedFeature` (the same tree FeatureView uses),
//   plus the edge geometry from the worker's last successful evaluation.
//   It flattens all edge segments onto the section plane and renders them.
//
// DXF export:
//   Stubbed — the "Export DXF" button is wired but produces a no-op toast
//   until the DXF exporter (src/lib/exporters.js) adds a `sectionToDxf`
//   helper.  TODO: wire dxf export in v0.3.
//
// Section-plane gumball:
//   Deferred to v0.3. TODO: add a drag-to-reposition gumball in the FeatureView
//   3D viewport that snaps to face planes and writes back to the section node.
//
// Props:
//   parsedFeature  — { features: [...] } parsed tree from the .section file
//   edgeSegments   — Float32Array of edge segments from the worker (flat xyz pairs)
//                    OR null if not yet evaluated
//   sectionPlane   — { point: [x,y,z], normal: [x,y,z] } from the section node
//                    used to compute the UV frame for 2D projection
//   onExportDxf    — optional callback for DXF export (stubbed)

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Download, ZoomIn, ZoomOut, Maximize2, Info } from 'lucide-react'

// ── Plane UV frame ─────────────────────────────────────────────────────────────
// Given a plane normal, compute two orthogonal unit vectors (u, v) that lie in
// the plane. This mirrors what the OCCT face frame returns for a gp_Pln.

function normalize3(v) {
  const len = Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
  if (len < 1e-10) return [1, 0, 0]
  return [v[0] / len, v[1] / len, v[2] / len]
}

function cross3(a, b) {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ]
}

function dot3(a, b) {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

function computePlaneFrame(normal) {
  const n = normalize3(normal || [0, 0, 1])
  // Choose an arbitrary vector not parallel to n to build u.
  let arbitrary = [0, 1, 0]
  if (Math.abs(dot3(n, arbitrary)) > 0.9) arbitrary = [1, 0, 0]
  const u = normalize3(cross3(arbitrary, n))
  const v = normalize3(cross3(n, u))
  return { u, v, n }
}

// Project a 3D point onto the plane's 2D UV frame.
function projectToUV(pt, planePoint, frame) {
  const dp = [pt[0] - planePoint[0], pt[1] - planePoint[1], pt[2] - planePoint[2]]
  return [dot3(dp, frame.u), dot3(dp, frame.v)]
}

// ── Edge segment extraction ────────────────────────────────────────────────────
// The worker returns edge geometry as Float32Array pairs (x0,y0,z0, x1,y1,z1, …).
// We project every segment pair onto the section plane's UV frame.

function extractEdgeUV(edgeSegs, planePoint, frame) {
  if (!edgeSegs || edgeSegs.length < 6) return []
  const lines = []
  for (let i = 0; i + 5 < edgeSegs.length; i += 6) {
    const a = projectToUV([edgeSegs[i], edgeSegs[i + 1], edgeSegs[i + 2]], planePoint, frame)
    const b = projectToUV([edgeSegs[i + 3], edgeSegs[i + 4], edgeSegs[i + 5]], planePoint, frame)
    lines.push([a, b])
  }
  return lines
}

// Compute bounding box from projected UV lines.
function computeBounds(lines) {
  if (lines.length === 0) return { minU: -10, maxU: 10, minV: -10, maxV: 10 }
  let minU = Infinity, maxU = -Infinity, minV = Infinity, maxV = -Infinity
  for (const [[u0, v0], [u1, v1]] of lines) {
    minU = Math.min(minU, u0, u1)
    maxU = Math.max(maxU, u0, u1)
    minV = Math.min(minV, v0, v1)
    maxV = Math.max(maxV, v0, v1)
  }
  const padU = (maxU - minU) * 0.12 || 5
  const padV = (maxV - minV) * 0.12 || 5
  return { minU: minU - padU, maxU: maxU + padU, minV: minV - padV, maxV: maxV + padV }
}

// ── SectionView ────────────────────────────────────────────────────────────────

export default function SectionView({
  parsedFeature,
  edgeSegments,
  sectionPlane,
  onExportDxf,
  viewRef,
}) {
  const svgRef = useRef(null)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const isPanning = useRef(false)
  const panStart = useRef({ x: 0, y: 0, panX: 0, panY: 0 })

  // Expose snapshot() via viewRef for the Editor's thumbnail system.
  useEffect(() => {
    if (!viewRef) return
    viewRef.current = {
      snapshot: () => {
        const el = svgRef.current
        if (!el) return null
        try {
          const s = new XMLSerializer()
          const svgStr = s.serializeToString(el)
          const blob = new Blob([svgStr], { type: 'image/svg+xml' })
          return URL.createObjectURL(blob)
        } catch {
          return null
        }
      },
    }
  }, [viewRef])

  // Derive section plane params from the last section node in the tree.
  const planeSpec = useMemo(() => {
    if (sectionPlane) return sectionPlane
    const features = parsedFeature?.features || []
    for (let i = features.length - 1; i >= 0; i--) {
      if (features[i].op === 'section' && features[i].plane) return features[i].plane
    }
    return { point: [0, 0, 0], normal: [0, 0, 1] }
  }, [sectionPlane, parsedFeature])

  const frame      = useMemo(() => computePlaneFrame(planeSpec.normal), [planeSpec.normal])
  const planePoint = useMemo(() => planeSpec.point || [0, 0, 0], [planeSpec])

  // Project all edge segments onto the plane's UV frame.
  const lines = useMemo(
    () => extractEdgeUV(edgeSegments, planePoint, frame),
    [edgeSegments, planePoint, frame],
  )
  const bounds = useMemo(() => computeBounds(lines), [lines])

  // SVG viewBox: map UV space to SVG pixels (1 unit = 1 mm; zoom is applied
  // via the SVG transform so the viewBox stays stable for export).
  const W = bounds.maxU - bounds.minU
  const H = bounds.maxV - bounds.minV

  // ── Panning ────────────────────────────────────────────────────────────────
  const onMouseDown = useCallback((e) => {
    if (e.button !== 1 && e.button !== 0) return
    isPanning.current = true
    panStart.current = { x: e.clientX, y: e.clientY, panX: pan.x, panY: pan.y }
    e.preventDefault()
  }, [pan])

  const onMouseMove = useCallback((e) => {
    if (!isPanning.current) return
    const dx = e.clientX - panStart.current.x
    const dy = e.clientY - panStart.current.y
    setPan({ x: panStart.current.panX + dx, y: panStart.current.panY + dy })
  }, [])

  const onMouseUp = useCallback(() => { isPanning.current = false }, [])

  const onWheel = useCallback((e) => {
    e.preventDefault()
    const delta = e.deltaY > 0 ? 0.9 : 1.1
    setZoom((z) => Math.max(0.05, Math.min(50, z * delta)))
  }, [])

  const handleReset = () => { setZoom(1); setPan({ x: 0, y: 0 }) }

  const handleExportDxf = () => {
    if (onExportDxf) {
      onExportDxf({ lines, bounds, planeSpec })
    } else {
      // TODO(v0.3): wire src/lib/exporters.js sectionToDxf when available.
      // eslint-disable-next-line no-console
      console.info('[SectionView] DXF export not yet wired — coming in v0.3')
    }
  }

  const isEmpty = lines.length === 0

  return (
    <div
      className="flex flex-col h-full bg-ink-950 select-none"
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onMouseLeave={onMouseUp}
    >
      {/* Toolbar */}
      <div className="flex items-center gap-1 px-2 py-1 border-b border-ink-700 bg-ink-900 flex-shrink-0">
        <span className="text-[11px] text-ink-400 font-mono mr-2">section outline</span>
        <button
          type="button"
          onClick={() => setZoom((z) => Math.min(50, z * 1.25))}
          className="p-1 rounded hover:bg-ink-700 text-ink-300 hover:text-kerf-200"
          title="Zoom in"
        >
          <ZoomIn size={14} />
        </button>
        <button
          type="button"
          onClick={() => setZoom((z) => Math.max(0.05, z * 0.8))}
          className="p-1 rounded hover:bg-ink-700 text-ink-300 hover:text-kerf-200"
          title="Zoom out"
        >
          <ZoomOut size={14} />
        </button>
        <button
          type="button"
          onClick={handleReset}
          className="p-1 rounded hover:bg-ink-700 text-ink-300 hover:text-kerf-200"
          title="Fit to view"
        >
          <Maximize2 size={14} />
        </button>
        <div className="flex-1" />
        <span className="text-[10px] text-ink-500 font-mono mr-2">
          n=[{(planeSpec.normal || [0, 0, 1]).map((x) => x.toFixed(2)).join(', ')}]
          &nbsp;
          p=[{(planeSpec.point || [0, 0, 0]).map((x) => x.toFixed(1)).join(', ')}]
        </span>
        <button
          type="button"
          onClick={handleExportDxf}
          className="flex items-center gap-1 px-2 py-0.5 rounded text-[11px] text-ink-300 hover:text-kerf-200 hover:bg-ink-700 border border-ink-700"
          title="Export DXF (coming in v0.3)"
        >
          <Download size={12} />
          <span>DXF</span>
        </button>
      </div>

      {/* SVG canvas */}
      <div className="flex-1 min-h-0 relative overflow-hidden" onWheel={onWheel}>
        {isEmpty ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-ink-400">
            <Info size={20} className="text-ink-600" />
            <span className="text-[12px]">No section edges yet.</span>
            <span className="text-[11px] text-ink-500">
              Evaluate the feature tree to generate the cross-section outline.
            </span>
          </div>
        ) : (
          <svg
            ref={svgRef}
            className="w-full h-full"
            viewBox={`${bounds.minU} ${bounds.minV} ${W || 20} ${H || 20}`}
            preserveAspectRatio="xMidYMid meet"
            style={{
              transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
              cursor: isPanning.current ? 'grabbing' : 'grab',
            }}
            onMouseDown={onMouseDown}
          >
            {/* Grid */}
            <defs>
              <pattern id="sv-grid" width="10" height="10" patternUnits="userSpaceOnUse">
                <path d="M 10 0 L 0 0 0 10" fill="none" stroke="#334155" strokeWidth="0.3" />
              </pattern>
            </defs>
            <rect
              x={bounds.minU} y={bounds.minV}
              width={W || 20} height={H || 20}
              fill="url(#sv-grid)"
            />
            {/* Axis lines */}
            <line x1={bounds.minU} y1="0" x2={bounds.maxU} y2="0" stroke="#475569" strokeWidth="0.4" strokeDasharray="2,2" />
            <line x1="0" y1={bounds.minV} x2="0" y2={bounds.maxV} stroke="#475569" strokeWidth="0.4" strokeDasharray="2,2" />
            {/* Section edges */}
            {lines.map(([[u0, v0], [u1, v1]], i) => (
              <line
                key={i}
                x1={u0} y1={-v0}  // flip V so +Y is up
                x2={u1} y2={-v1}
                stroke="#a78bfa"
                strokeWidth="0.5"
                strokeLinecap="round"
              />
            ))}
          </svg>
        )}
      </div>
    </div>
  )
}
