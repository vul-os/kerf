/**
 * LaminateFailureEnvelope.jsx
 *
 * Biaxial first-ply-failure (FPF) envelope for a composite laminate.
 *
 * Features:
 *  - SVG polar / Cartesian failure envelope plot (Nx vs Ny biaxial space)
 *  - Calls POST /api/composites/failure_envelope → composites_failure_envelope tool
 *  - Operating-point overlay: user supplies (Nx, Ny) and the panel shows margin
 *  - Criterion selector: Tsai-Wu (default)
 *  - Legend: envelope boundary + operating point distance to boundary
 *  - Aesthetic: deep-charcoal science-lab, rose/teal colour scheme
 *
 * Design ref: Reddy (2004) Fig 6.8 — biaxial strength envelopes for CFRP laminates.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '../../store/auth.js'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''

// ---------------------------------------------------------------------------
// API call
// ---------------------------------------------------------------------------
async function callEnvelope(plies, nAngles = 36, F12star = -0.5, Nxy = 0) {
  const token = useAuth.getState().accessToken
  const body = {
    tool: 'composites_failure_envelope',
    args: { plies, n_angles: nAngles, F12_star: F12star, Nxy },
  }
  const res = await fetch(`${API_URL}/api/composites/failure_envelope`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

// ---------------------------------------------------------------------------
// Default T300/5208 [0/45/-45/90]_s quasi-isotropic laminate
// ---------------------------------------------------------------------------
const DEFAULT_PLIES = [0, 45, -45, 90, 90, -45, 45, 0].map((angle) => ({
  angle,
  E1: 181, E2: 10.3, G12: 7.17, nu12: 0.28, thickness: 0.125,
  Xt: 1500, Xc: 1500, Yt: 40, Yc: 246, S12: 68,
}))

// ---------------------------------------------------------------------------
// SVG failure envelope plot
// ---------------------------------------------------------------------------
function EnvelopePlot({ envelopePoints, operatingPoint, width = 480, height = 400 }) {
  if (!envelopePoints || envelopePoints.length === 0) {
    return (
      <svg width="100%" viewBox={`0 0 ${width} ${height}`} style={{ display: 'block' }}>
        <rect width={width} height={height} fill="#06090f" />
        <text x={width / 2} y={height / 2} fill="#334155" fontSize={12}
          fontFamily="monospace" textAnchor="middle">
          No envelope data — click Run
        </text>
      </svg>
    )
  }

  const pad = { l: 55, r: 20, t: 20, b: 45 }
  const iW = width - pad.l - pad.r
  const iH = height - pad.t - pad.b

  // Axis range: symmetric around zero with some margin
  const nxVals = envelopePoints.map((p) => p.Nx_fail_N_per_mm)
  const nyVals = envelopePoints.map((p) => p.Ny_fail_N_per_mm)
  const allVals = [...nxVals, ...nyVals]
  const absMax = Math.max(...allVals.map(Math.abs), 100) * 1.15
  const axMin = -absMax, axMax = absMax

  const px = (nx) => pad.l + ((nx - axMin) / (axMax - axMin)) * iW
  const py = (ny) => pad.t + iH - ((ny - axMin) / (axMax - axMin)) * iH

  // Close the polygon
  const closed = [...envelopePoints, envelopePoints[0]]
  const polyPoints = closed.map((p) =>
    `${px(p.Nx_fail_N_per_mm)},${py(p.Ny_fail_N_per_mm)}`
  ).join(' ')

  const opX = operatingPoint?.Nx || 0
  const opY = operatingPoint?.Ny || 0

  // Grid lines
  const gridVals = []
  const step = Math.pow(10, Math.floor(Math.log10(absMax)))
  for (let v = -Math.ceil(absMax / step) * step; v <= absMax * 1.01; v += step) {
    gridVals.push(Math.round(v * 10) / 10)
  }

  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} style={{ display: 'block' }}
      role="img" aria-label="Biaxial failure envelope">
      <defs>
        <clipPath id="envelope-clip">
          <rect x={pad.l} y={pad.t} width={iW} height={iH} />
        </clipPath>
      </defs>
      <rect width={width} height={height} fill="#06090f" />

      {/* Grid */}
      {gridVals.map((v, i) => (
        <g key={i}>
          <line x1={pad.l} y1={py(v)} x2={pad.l + iW} y2={py(v)}
            stroke="#0f172a" strokeWidth={v === 0 ? 0.8 : 0.4} />
          <line x1={px(v)} y1={pad.t} x2={px(v)} y2={pad.t + iH}
            stroke="#0f172a" strokeWidth={v === 0 ? 0.8 : 0.4} />
          {Math.abs(v) < absMax * 0.95 && (
            <>
              <text x={pad.l - 4} y={py(v) + 3} fill="#334155" fontSize={7}
                fontFamily="monospace" textAnchor="end">
                {Math.abs(v) > 999 ? (v / 1000).toFixed(1) + 'k' : v.toFixed(0)}
              </text>
              <text x={px(v)} y={pad.t + iH + 12} fill="#334155" fontSize={7}
                fontFamily="monospace" textAnchor="middle">
                {Math.abs(v) > 999 ? (v / 1000).toFixed(1) + 'k' : v.toFixed(0)}
              </text>
            </>
          )}
        </g>
      ))}

      {/* Axes labels */}
      <text x={pad.l + iW / 2} y={height - 6} fill="#475569" fontSize={9}
        fontFamily="monospace" textAnchor="middle">
        Nx [N/mm]
      </text>
      <text x={12} y={pad.t + iH / 2} fill="#475569" fontSize={9}
        fontFamily="monospace" textAnchor="middle"
        transform={`rotate(-90, 12, ${pad.t + iH / 2})`}>
        Ny [N/mm]
      </text>

      {/* Envelope polygon */}
      <g clipPath="url(#envelope-clip)">
        <polygon points={polyPoints}
          fill="rgba(244,63,94,0.06)"
          stroke="#f43f5e"
          strokeWidth={1.5}
          strokeLinejoin="round"
        />

        {/* Envelope data points */}
        {envelopePoints.map((p, i) => (
          <circle key={i}
            cx={px(p.Nx_fail_N_per_mm)}
            cy={py(p.Ny_fail_N_per_mm)}
            r={2}
            fill="#f43f5e"
            opacity={0.6}
          />
        ))}

        {/* Operating point */}
        <line x1={px(opX) - 6} y1={py(opY)} x2={px(opX) + 6} y2={py(opY)}
          stroke="#4adeae" strokeWidth={1.5} />
        <line x1={px(opX)} y1={py(opY) - 6} x2={px(opX)} y2={py(opY) + 6}
          stroke="#4adeae" strokeWidth={1.5} />
        <circle cx={px(opX)} cy={py(opY)} r={4}
          fill="none" stroke="#4adeae" strokeWidth={1.5} />
      </g>

      {/* Legend */}
      <g transform={`translate(${pad.l + 8}, ${pad.t + 8})`}>
        <rect width={110} height={36} rx={3}
          fill="rgba(6,9,15,0.85)" stroke="#1e293b" strokeWidth={0.5} />
        <line x1={8} y1={10} x2={22} y2={10} stroke="#f43f5e" strokeWidth={1.5} />
        <text x={26} y={13} fill="#94a3b8" fontSize={8} fontFamily="monospace">FPF envelope</text>
        <line x1={8} y1={24} x2={14} y2={24} stroke="#4adeae" strokeWidth={1} />
        <line x1={11} y1={21} x2={11} y2={27} stroke="#4adeae" strokeWidth={1} />
        <text x={26} y={27} fill="#94a3b8" fontSize={8} fontFamily="monospace">Op. point</text>
      </g>
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function LaminateFailureEnvelope({ plies: propPlies, onResult }) {
  const plies = propPlies || DEFAULT_PLIES

  const [envelopePoints, setEnvelopePoints] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  // Operating point inputs
  const [opNx, setOpNx] = useState(0)
  const [opNy, setOpNy] = useState(0)
  const [F12star, setF12star] = useState(-0.5)
  const [nAngles, setNAngles] = useState(36)

  const runEnvelope = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await callEnvelope(plies, nAngles, F12star, 0)
      setResult(res)
      setEnvelopePoints(res.envelope_points || [])
      onResult?.(res)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [plies, nAngles, F12star, onResult])

  // Check if operating point is inside the envelope (rough check by distance scaling)
  const margin = (() => {
    if (!envelopePoints || envelopePoints.length === 0) return null
    // For each direction from origin through the operating point, find the envelope intersection
    const opMag = Math.sqrt(opNx * opNx + opNy * opNy)
    if (opMag < 1e-6) return null
    // Find closest envelope point in the same angular direction
    const opAngle = Math.atan2(opNy, opNx)
    const diffs = envelopePoints.map((p) => {
      const a = Math.atan2(p.Ny_fail_N_per_mm, p.Nx_fail_N_per_mm)
      return { p, da: Math.abs(a - opAngle) }
    })
    diffs.sort((a, b) => a.da - b.da)
    const closest = diffs[0]?.p
    if (!closest) return null
    const envMag = Math.sqrt(
      closest.Nx_fail_N_per_mm ** 2 + closest.Ny_fail_N_per_mm ** 2
    )
    return envMag > 0 ? (envMag / opMag - 1) : null
  })()

  const styles = {
    root: {
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      background: '#06090f',
      fontFamily: '"IBM Plex Mono", "JetBrains Mono", ui-monospace, monospace',
      color: '#e2e8f0',
      overflow: 'hidden',
    },
    header: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '10px 14px 8px',
      borderBottom: '1px solid #1e293b',
      background: '#040710',
    },
    title: {
      fontSize: 11,
      fontWeight: 600,
      letterSpacing: '0.2em',
      textTransform: 'uppercase',
      color: '#f43f5e',
    },
    body: {
      display: 'flex',
      flex: 1,
      minHeight: 0,
      overflow: 'hidden',
    },
    plotArea: {
      flex: 1,
      minWidth: 0,
      overflow: 'hidden',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: 4,
    },
    sidebar: {
      width: 180,
      flexShrink: 0,
      borderLeft: '1px solid #1e293b',
      padding: '12px 10px',
      overflow: 'auto',
      background: '#040810',
      display: 'flex',
      flexDirection: 'column',
      gap: 14,
    },
    sectionLabel: {
      fontSize: 9,
      letterSpacing: '0.14em',
      textTransform: 'uppercase',
      color: '#475569',
      marginBottom: 6,
    },
    ctrlRow: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginBottom: 5,
    },
    ctrlLabel: {
      fontSize: 10,
      color: '#94a3b8',
    },
    input: {
      width: 70,
      background: '#0d1321',
      border: '1px solid #1e293b',
      borderRadius: 3,
      color: '#e2e8f0',
      fontFamily: 'inherit',
      fontSize: 10,
      padding: '2px 5px',
      textAlign: 'right',
      outline: 'none',
    },
    runBtn: {
      width: '100%',
      padding: '5px 0',
      background: loading ? 'rgba(244,63,94,0.04)' : 'rgba(244,63,94,0.1)',
      border: '1px solid rgba(244,63,94,0.35)',
      borderRadius: 3,
      color: loading ? '#475569' : '#f43f5e',
      fontFamily: 'inherit',
      fontSize: 9,
      letterSpacing: '0.12em',
      textTransform: 'uppercase',
      cursor: loading ? 'default' : 'pointer',
    },
    marginDisplay: {
      marginTop: 8,
      padding: '8px 10px',
      background: margin !== null && margin >= 0
        ? 'rgba(74,222,174,0.08)'
        : 'rgba(248,113,113,0.08)',
      border: `1px solid ${margin !== null && margin >= 0
        ? 'rgba(74,222,174,0.3)'
        : 'rgba(248,113,113,0.3)'}`,
      borderRadius: 3,
    },
    marginLabel: {
      fontSize: 8,
      color: '#475569',
      textTransform: 'uppercase',
      letterSpacing: '0.1em',
      marginBottom: 2,
    },
    marginValue: {
      fontSize: 16,
      fontWeight: 700,
      color: margin !== null && margin >= 0 ? '#4adeae' : '#f87171',
    },
  }

  return (
    <div style={styles.root} data-testid="laminate-failure-envelope">
      <div style={styles.header}>
        <span style={styles.title}>Failure Envelope (FPF)</span>
        {error && (
          <span style={{ fontSize: 9, color: '#f87171' }}>Error: {error}</span>
        )}
      </div>

      <div style={styles.body}>
        {/* Plot area */}
        <div style={styles.plotArea}>
          <EnvelopePlot
            envelopePoints={envelopePoints}
            operatingPoint={{ Nx: opNx, Ny: opNy }}
          />
        </div>

        {/* Sidebar */}
        <div style={styles.sidebar}>
          {/* Analysis params */}
          <div>
            <div style={styles.sectionLabel}>Parameters</div>
            <div style={styles.ctrlRow}>
              <span style={styles.ctrlLabel}>Angles</span>
              <input
                type="number"
                style={styles.input}
                value={nAngles}
                min={8}
                max={360}
                step={4}
                onChange={(e) => setNAngles(Math.max(8, parseInt(e.target.value) || 36))}
              />
            </div>
            <div style={styles.ctrlRow}>
              <span style={styles.ctrlLabel}>F12*</span>
              <input
                type="number"
                style={styles.input}
                value={F12star}
                min={-1}
                max={0.5}
                step={0.1}
                onChange={(e) => setF12star(parseFloat(e.target.value) || -0.5)}
              />
            </div>
          </div>

          {/* Operating point */}
          <div>
            <div style={styles.sectionLabel}>Operating Point</div>
            <div style={styles.ctrlRow}>
              <span style={styles.ctrlLabel}>Nx N/mm</span>
              <input
                type="number"
                style={styles.input}
                value={opNx}
                step={10}
                onChange={(e) => setOpNx(parseFloat(e.target.value) || 0)}
              />
            </div>
            <div style={styles.ctrlRow}>
              <span style={styles.ctrlLabel}>Ny N/mm</span>
              <input
                type="number"
                style={styles.input}
                value={opNy}
                step={10}
                onChange={(e) => setOpNy(parseFloat(e.target.value) || 0)}
              />
            </div>
            {margin !== null && (
              <div style={styles.marginDisplay}>
                <div style={styles.marginLabel}>Margin</div>
                <div style={styles.marginValue}>
                  {(margin * 100).toFixed(1)}%
                </div>
                <div style={{ fontSize: 8, color: '#475569', marginTop: 2 }}>
                  {margin >= 0 ? 'Safe' : 'Failed'}
                </div>
              </div>
            )}
          </div>

          {/* Stats */}
          {result && (
            <div>
              <div style={styles.sectionLabel}>Results</div>
              {[
                ['Max |Nx|', `${result.max_uniaxial_Nx_N_per_mm?.toFixed(1)} N/mm`],
                ['Max |Ny|', `${result.max_uniaxial_Ny_N_per_mm?.toFixed(1)} N/mm`],
                ['Points', result.envelope_points?.length],
              ].map(([label, val]) => (
                <div key={label} style={styles.ctrlRow}>
                  <span style={{ fontSize: 9, color: '#475569' }}>{label}</span>
                  <span style={{ fontSize: 10, color: '#f43f5e' }}>{val}</span>
                </div>
              ))}
            </div>
          )}

          <button
            style={styles.runBtn}
            onClick={runEnvelope}
            type="button"
            disabled={loading}
          >
            {loading ? '⟳ Running…' : '▶ Run Envelope'}
          </button>
        </div>
      </div>
    </div>
  )
}
