// DRCOverlay — SVG overlay that draws live DRC violation markers on the PCB canvas.
//
// Each violation returned by the backend (or by the frontend pcbDRC engine) is
// shown as a coloured circle + optional tooltip on hover.  Errors are red,
// warnings are amber.
//
// Props
// -----
// violations   : Violation[]   — array of {kind, severity, x, y, message}
//                               (same schema as kerf_electronics/drc.py and
//                                src/lib/pcbDRC.js)
// visible      : bool  (default true)
// markerRadius : number  (default 0.3)  — radius in board units (mm)
// onHover      : (violation | null) => void  — optional hover callback
//
// TODO: wire this component into PCBView (or a parent CircuitCanvas wrapper)
//       by importing it and mounting it as a sibling SVG overlay inside the
//       pan/zoom <g> group.  Pass `violations` from `runDRC(circuitJson)` or
//       from the backend `/drc` endpoint result.  Also pass the `onHover`
//       handler if you want a tooltip rendered in the parent.

import { useCallback, useState } from 'react'

// ---------------------------------------------------------------------------
// Colour helpers
// ---------------------------------------------------------------------------

const SEVERITY_COLORS = {
  error:   '#ef4444', // red-500
  warning: '#f59e0b', // amber-500
}

const KIND_ICONS = {
  pad_clearance:       'C',
  pad_trace_clearance: 'C',
  trace_clearance:     'C',
  unconnected_pad:     'U',
  missing_footprint:   'F',
}

function markerColor(severity) {
  return SEVERITY_COLORS[severity] ?? '#94a3b8'
}

function markerLabel(kind) {
  return KIND_ICONS[kind] ?? '!'
}

// ---------------------------------------------------------------------------
// Single violation marker
// ---------------------------------------------------------------------------

function ViolationMarker({ violation, radius, onHover }) {
  const { x, y, kind, severity, message } = violation
  const color = markerColor(severity)
  const label = markerLabel(kind)

  const handleEnter = useCallback(() => {
    if (onHover) onHover(violation)
  }, [violation, onHover])

  const handleLeave = useCallback(() => {
    if (onHover) onHover(null)
  }, [onHover])

  return (
    <g
      className={`drc-marker drc-marker--${severity} drc-marker--${kind}`}
      transform={`translate(${x},${y})`}
      style={{ cursor: 'pointer' }}
      onMouseEnter={handleEnter}
      onMouseLeave={handleLeave}
      data-kind={kind}
      data-severity={severity}
      data-message={message}
    >
      {/* Outer glow ring */}
      <circle
        r={radius * 1.6}
        fill={color}
        fillOpacity={0.15}
        stroke="none"
      />
      {/* Filled marker circle */}
      <circle
        r={radius}
        fill={color}
        fillOpacity={0.85}
        stroke="#fff"
        strokeWidth={radius * 0.2}
      />
      {/* Single-character kind label — only visible at high zoom */}
      <text
        textAnchor="middle"
        dominantBaseline="central"
        fontSize={radius * 1.2}
        fill="#fff"
        style={{ userSelect: 'none', pointerEvents: 'none', fontWeight: 700 }}
      >
        {label}
      </text>
    </g>
  )
}

// ---------------------------------------------------------------------------
// React component
// ---------------------------------------------------------------------------

export default function DRCOverlay({
  violations = [],
  visible = true,
  markerRadius = 0.3,
  onHover = null,
}) {
  const [localHovered, setLocalHovered] = useState(null)

  const handleHover = useCallback(
    (v) => {
      setLocalHovered(v)
      if (onHover) onHover(v)
    },
    [onHover],
  )

  if (!visible || !violations || violations.length === 0) return null

  const errors   = violations.filter((v) => v.severity === 'error')
  const warnings = violations.filter((v) => v.severity === 'warning')

  // Render warnings first so errors appear on top
  const ordered = [...warnings, ...errors]

  return (
    <g
      className="drc-overlay"
      style={{ pointerEvents: 'all' }}
      data-error-count={errors.length}
      data-warning-count={warnings.length}
    >
      {ordered.map((v, idx) => (
        <ViolationMarker
          key={idx}
          violation={v}
          radius={markerRadius}
          onHover={handleHover}
        />
      ))}
    </g>
  )
}
