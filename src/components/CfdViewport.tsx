/**
 * CfdViewport.tsx — 2-D CFD results viewport.
 *
 * Renders streamlines, vector-field arrows, and a pressure contour overlay
 * onto a Canvas 2D surface from postprocessed OpenFOAM data.
 *
 * Props
 * -----
 * vectorField  {object}  Grid field { x0,y0,dx,dy,nx,ny,u[][],v[][] }
 *                        or { cells:[{x,y,Ux,Uy,p?},...] }
 *              Absent/null → empty canvas with a placeholder message.
 *
 * pressureField {object} Optional separate pressure grid { …, p[][] }.
 *               If not provided but vectorField.cells has .p values,
 *               the pressure overlay uses those.
 *
 * showStreamlines {boolean}  default true
 * showArrows      {boolean}  default true
 * showPressure    {boolean}  default true
 *
 * streamlineCount {number}   default 20   — number of auto-generated seeds
 * arrowGridStep   {number}   default 4    — every Nth grid cell gets an arrow
 * pressureAlpha   {number}   default 0.45 — opacity of the pressure overlay
 *
 * seeds  [{x,y}]  Optional manual seed overrides for streamlines.
 *
 * width   {number}  Canvas pixel width  (default 520)
 * height  {number}  Canvas pixel height (default 340)
 *
 * TODO(parent-integration): wire vectorField from the workshop CFD results
 * payload (packages/kerf-cfd postprocessing output).  See openfoam_bridge.py
 * extract_postprocessing_data() → { velocity: {cells:[…]}, pressure: {cells:[…]} }.
 */

import { useEffect, useRef, useCallback } from 'react'
import {
  drawStreamlines,
  drawVectorArrows,
  drawPressureContour,
  buildTransform,
  generateInletSeeds,
  scalarToCssColor,
} from '../lib/cfdViz.js'
import { cellsToGrid } from '../lib/streamlineIntegrator.js'

// ── Types ──────────────────────────────────────────────────────────────────────
//
// Both src/lib/cfdViz.js and src/lib/streamlineIntegrator.js (outside this slice
// — not part of src/components) are untyped JS, so the CFD field shape is
// declared locally. Every field is optional because the source branches on
// `field.cells` truthiness rather than a real discriminant — both the grid form
// and the flat OpenFOAM-bridge cell-list form fold into one interface here,
// matching that loose runtime check rather than forcing a discriminated union
// neither module actually enforces.

export interface CfdCell {
  x: number
  y: number
  Ux: number
  Uy: number
  p?: number | null
}

export interface CfdField {
  cells?: CfdCell[]
  x0?: number
  y0?: number
  dx?: number
  dy?: number
  nx?: number
  ny?: number
  u?: number[][]
  v?: number[][]
  p?: number[][] | null
}

export interface CfdViewportProps {
  vectorField?: CfdField | null
  pressureField?: CfdField | null
  showStreamlines?: boolean
  showArrows?: boolean
  showPressure?: boolean
  streamlineCount?: number
  arrowGridStep?: number
  pressureAlpha?: number
  seeds?: Array<{ x: number; y: number }> | null
  width?: number
  height?: number
}

// ── Color-bar legend ─────────────────────────────────────────────────────────

function ColorBar({ label, minVal, maxVal, fmtFn }: { label: string; minVal: number; maxVal: number; fmtFn: (v: number) => string }) {
  const stops = 5
  const swatches: Array<{ t: number; v: number; color: string }> = []
  for (let i = 0; i <= stops; i++) {
    const t = i / stops
    const v = minVal + (maxVal - minVal) * t
    swatches.push({ t, v, color: scalarToCssColor(t, 1) as string })
  }
  const gradient = swatches.map(s => s.color).join(', ')

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
      <span style={{ fontSize: 10, color: '#9ca3af', whiteSpace: 'nowrap', fontFamily: 'monospace' }}>
        {label}
      </span>
      <div style={{
        flex: 1, height: 8, borderRadius: 3,
        background: `linear-gradient(to right, ${gradient})`,
      }} />
      <span style={{ fontSize: 10, color: '#9ca3af', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
        {fmtFn(minVal)} – {fmtFn(maxVal)}
      </span>
    </div>
  )
}

// ── Layer legend ──────────────────────────────────────────────────────────────

function LayerChip({ color, label }: { color: string; label: string }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      fontSize: 10, color: '#d1d5db', background: '#1f2937',
      border: '1px solid #374151', borderRadius: 4,
      padding: '1px 6px',
    }}>
      <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, display: 'inline-block' }} />
      {label}
    </span>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function CfdViewport({
  vectorField = null,
  pressureField = null,
  showStreamlines = true,
  showArrows = true,
  showPressure = true,
  streamlineCount = 20,
  arrowGridStep = 4,
  pressureAlpha = 0.45,
  seeds: seedsProp = null,
  width = 520,
  height = 340,
}: CfdViewportProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  const render = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    ctx.clearRect(0, 0, canvas.width, canvas.height)

    if (!vectorField) return

    // Normalise to grid form
    const field = vectorField.cells ? (cellsToGrid(vectorField.cells) as CfdField) : vectorField

    // Build transform once and share across layers
    const transform = buildTransform(field, canvas.width, canvas.height)

    // Layer 1: Pressure contour
    if (showPressure) {
      const pField = pressureField
        ? (pressureField.cells ? { ...(cellsToGrid(pressureField.cells) as CfdField), p: null } : pressureField)
        : (vectorField.cells && vectorField.cells.some(c => c.p != null)
          ? vectorField
          : field)
      // cfdViz.js's drawPressureContour reads opts.transform via property access rather than
      // destructuring, so TS's parameter-shape inference (from the destructured subset) omits
      // it; assigning to a variable first avoids the excess-property check an inline object
      // literal would trigger.
      const pressureOpts = {
        alpha: pressureAlpha,
        transform,
        canvasW: canvas.width,
        canvasH: canvas.height,
      }
      drawPressureContour(ctx, pField, pressureOpts)
    }

    // Layer 2: Streamlines
    if (showStreamlines) {
      const seeds = seedsProp ?? (generateInletSeeds(field, streamlineCount) as Array<{ x: number; y: number }>)
      drawStreamlines(ctx, field, seeds, {
        traceOpts: { max_steps: 2000, dt: (field.dx ?? 1) * 0.5 },
        color: 'rgba(100,200,255,0.7)',
        lineWidth: 1.2,
        transform,
        canvasW: canvas.width,
        canvasH: canvas.height,
      })
    }

    // Layer 3: Vector arrows
    if (showArrows) {
      // Same TS excess-property-check workaround as drawPressureContour above.
      const arrowOpts = {
        gridStep: arrowGridStep,
        color: 'rgba(255,220,80,0.9)',
        lineWidth: 1,
        transform,
        canvasW: canvas.width,
        canvasH: canvas.height,
      }
      drawVectorArrows(ctx, field, arrowOpts)
    }
  }, [
    vectorField, pressureField,
    showStreamlines, showArrows, showPressure,
    streamlineCount, arrowGridStep, pressureAlpha,
    seedsProp, width, height,
  ])

  useEffect(() => {
    render()
  }, [render])

  // ── Pressure range for legend ─────────────────────────────────────────────
  let pMin = 0
  let pMax = 1
  if (vectorField) {
    const field = vectorField.cells ? (cellsToGrid(vectorField.cells) as CfdField) : vectorField
    if (field.p) {
      for (const row of field.p) {
        for (const pv of row) {
          if (pv < pMin) pMin = pv
          if (pv > pMax) pMax = pv
        }
      }
    } else if (vectorField.cells) {
      for (const c of vectorField.cells) {
        if (c.p != null) {
          if (c.p < pMin) pMin = c.p
          if (c.p > pMax) pMax = c.p
        }
      }
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {/* Canvas */}
      <div style={{ position: 'relative' }}>
        <canvas
          ref={canvasRef}
          width={width}
          height={height}
          style={{
            width: '100%',
            height,
            borderRadius: 6,
            border: '1px solid #1f2937',
            background: '#0d1117',
            display: 'block',
          }}
        />

        {!vectorField && (
          <div style={{
            position: 'absolute', inset: 0,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: '#4b5563', fontSize: 13,
          }}>
            No CFD data — run a simulation first
          </div>
        )}
      </div>

      {/* Layer legend */}
      {vectorField && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {showPressure && (
            <LayerChip color="rgba(100,180,255,0.7)" label="Pressure" />
          )}
          {showStreamlines && (
            <LayerChip color="rgba(100,200,255,0.85)" label="Streamlines" />
          )}
          {showArrows && (
            <LayerChip color="rgba(255,220,80,0.9)" label="Velocity" />
          )}
        </div>
      )}

      {/* Pressure colour bar */}
      {vectorField && showPressure && (
        <ColorBar
          label="p"
          minVal={pMin}
          maxVal={pMax}
          fmtFn={v => v.toFixed(1) + ' Pa'}
        />
      )}
    </div>
  )
}
