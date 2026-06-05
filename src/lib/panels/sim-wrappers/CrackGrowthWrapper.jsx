// CrackGrowthWrapper.jsx
// Thin wrapper for the incremental crack-propagation result panel.
//
// Expected JSON content shape (from fem_crack_growth_simulate tool output):
// {
//   crack_path_m: [[x,y], ...],          // crack-tip positions at each increment
//   crack_length_m: [a0, a1, ...],       // crack length at each increment [m]
//   K_I_pa_sqrt_m: [K1, ...],           // Mode-I SIF history [Pa√m]
//   K_II_pa_sqrt_m: [K1, ...],          // Mode-II SIF history [Pa√m]
//   K_eff_pa_sqrt_m: [K1, ...],         // effective SIF history [Pa√m]
//   kink_angle_deg: [θ1, ...],          // kink angle at each increment [deg]
//   N_fatigue_cycles: number,            // total estimated fatigue life [cycles]
//   stable: boolean,                     // true = didn't reach K_Ic
//   stop_reason: string,                 // 'unstable_fracture'|'max_steps'|'max_crack_length'
//   n_increments: number,
//   K_handbook_initial_pa_sqrt_m: number, // handbook K_I at a_0
//   plate_geometry: { W_m, H_m, a0_m, condition },
//   paris_params: { C, m, K_Ic_pa_sqrt_m, K_th_pa_sqrt_m, R_ratio },
//   notes: string,
// }

const DEFAULTS = {
  crack_path_m: [],
  crack_length_m: [],
  K_I_pa_sqrt_m: [],
  K_II_pa_sqrt_m: [],
  K_eff_pa_sqrt_m: [],
  kink_angle_deg: [],
  N_fatigue_cycles: 0,
  stable: true,
  stop_reason: 'max_steps',
  n_increments: 0,
  K_handbook_initial_pa_sqrt_m: null,
  plate_geometry: null,
  paris_params: null,
  notes: null,
}

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

// ── Mini SVG crack-path visualiser ─────────────────────────────────────────

function CrackPathSVG({ crack_path_m, plate_geometry, K_I_pa_sqrt_m, K_Ic }) {
  if (!crack_path_m || crack_path_m.length === 0) return null
  const W = plate_geometry?.W_m ?? 0.1
  const H = plate_geometry?.H_m ?? 0.1

  const svgW = 280
  const svgH = 200
  const pad = 20

  const toSvg = ([x, y]) => [
    pad + (x / W) * (svgW - 2 * pad),
    svgH - pad - (y / H) * (svgH - 2 * pad),
  ]

  const pts = crack_path_m.map(toSvg)
  const pathD = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ')

  // Color crack segments by K_eff / K_Ic
  const nSeg = Math.max(pts.length - 1, 0)
  const K_Ic_val = K_Ic ?? 50e6

  return (
    <svg width={svgW} height={svgH} style={{ border: '1px solid #e2e8f0', borderRadius: '6px', background: '#f8fafc' }}>
      {/* Plate outline */}
      <rect
        x={pad} y={pad}
        width={svgW - 2 * pad} height={svgH - 2 * pad}
        fill="none" stroke="#cbd5e1" strokeWidth="1.5"
      />

      {/* Load arrows on top */}
      {[0.3, 0.5, 0.7].map(fx => {
        const tx = pad + fx * (svgW - 2 * pad)
        return (
          <g key={fx}>
            <line x1={tx} y1={pad - 12} x2={tx} y2={pad} stroke="#3b82f6" strokeWidth="1.5" markerEnd="url(#arrowB)" />
          </g>
        )
      })}

      {/* Crack path */}
      {nSeg > 0
        ? pts.slice(0, -1).map((p0, i) => {
            const p1 = pts[i + 1]
            const K = K_I_pa_sqrt_m?.[i] ?? 0
            const frac = Math.min(K / K_Ic_val, 1.0)
            // Color: green → yellow → red
            const r = Math.round(frac * 255)
            const g = Math.round((1 - frac) * 200)
            const color = `rgb(${r},${g},30)`
            return (
              <line
                key={i}
                x1={p0[0].toFixed(1)} y1={p0[1].toFixed(1)}
                x2={p1[0].toFixed(1)} y2={p1[1].toFixed(1)}
                stroke={color} strokeWidth="2" strokeLinecap="round"
              />
            )
          })
        : <path d={pathD} fill="none" stroke="#ef4444" strokeWidth="2" />
      }

      {/* Crack-tip marker */}
      {pts.length > 0 && (
        <circle
          cx={pts[pts.length - 1][0].toFixed(1)}
          cy={pts[pts.length - 1][1].toFixed(1)}
          r="4" fill="#ef4444" stroke="white" strokeWidth="1"
        />
      )}

      {/* Arrow defs */}
      <defs>
        <marker id="arrowB" markerWidth="6" markerHeight="6" refX="3" refY="6" orient="auto">
          <path d="M0,0 L3,6 L6,0" fill="none" stroke="#3b82f6" strokeWidth="1" />
        </marker>
      </defs>

      {/* Labels */}
      <text x={pad + 2} y={svgH - 4} fontSize="9" fill="#94a3b8">0</text>
      <text x={svgW - pad - 2} y={svgH - 4} fontSize="9" fill="#94a3b8" textAnchor="end">{(W * 1e3).toFixed(0)} mm</text>
      <text x={4} y={pad + 2} fontSize="9" fill="#94a3b8">{(H * 1e3).toFixed(0)} mm</text>
      <text x={4} y={svgH - pad} fontSize="9" fill="#94a3b8">0</text>
    </svg>
  )
}

// ── K history chart (simple inline bars) ──────────────────────────────────

function KHistoryChart({ crack_length_m, K_I_pa_sqrt_m, K_II_pa_sqrt_m, K_Ic }) {
  if (!crack_length_m || crack_length_m.length === 0) return null
  const n = Math.min(crack_length_m.length, K_I_pa_sqrt_m?.length ?? 0)
  if (n === 0) return null

  const K_Ic_val = K_Ic ?? 50e6
  const maxK = Math.max(...(K_I_pa_sqrt_m ?? [0]).map(Math.abs), K_Ic_val)

  const W = 280
  const H = 100
  const pad = { l: 36, r: 10, t: 10, b: 24 }
  const cw = W - pad.l - pad.r
  const ch = H - pad.t - pad.b

  const toX = (i) => pad.l + (i / Math.max(n - 1, 1)) * cw
  const toY = (v) => pad.t + ch - (Math.abs(v) / maxK) * ch

  const K1pts = (K_I_pa_sqrt_m ?? []).slice(0, n).map((v, i) => `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(' ')
  const K2pts = (K_II_pa_sqrt_m ?? []).slice(0, n).map((v, i) => `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(' ')

  const yKic = toY(K_Ic_val)

  return (
    <svg width={W} height={H} style={{ border: '1px solid #e2e8f0', borderRadius: '6px', background: '#f8fafc', display: 'block' }}>
      {/* K_Ic line */}
      <line x1={pad.l} y1={yKic.toFixed(1)} x2={W - pad.r} y2={yKic.toFixed(1)} stroke="#ef4444" strokeWidth="1" strokeDasharray="4,2" />
      <text x={W - pad.r + 2} y={yKic + 3} fontSize="8" fill="#ef4444">K_Ic</text>

      {/* K_I line */}
      {n > 1 && (
        <polyline points={K1pts} fill="none" stroke="#2563eb" strokeWidth="1.5" />
      )}
      {n > 1 && K_II_pa_sqrt_m?.length > 0 && (
        <polyline points={K2pts} fill="none" stroke="#f59e0b" strokeWidth="1.5" />
      )}

      {/* Axes */}
      <line x1={pad.l} y1={pad.t} x2={pad.l} y2={pad.t + ch} stroke="#94a3b8" strokeWidth="1" />
      <line x1={pad.l} y1={pad.t + ch} x2={W - pad.r} y2={pad.t + ch} stroke="#94a3b8" strokeWidth="1" />

      {/* Labels */}
      <text x={pad.l - 2} y={pad.t + 4} fontSize="8" fill="#94a3b8" textAnchor="end">{(maxK / 1e6).toFixed(0)}</text>
      <text x={pad.l - 2} y={pad.t + ch} fontSize="8" fill="#94a3b8" textAnchor="end">0</text>
      <text x={pad.l} y={H - 4} fontSize="8" fill="#94a3b8">a₀</text>
      <text x={W - pad.r} y={H - 4} fontSize="8" fill="#94a3b8" textAnchor="end">aₙ</text>
      <text x={pad.l + 4} y={pad.t + 8} fontSize="8" fill="#64748b">K [MPa√m]</text>

      {/* Legend */}
      <line x1={W - 70} y1={pad.t + 8} x2={W - 58} y2={pad.t + 8} stroke="#2563eb" strokeWidth="1.5" />
      <text x={W - 56} y={pad.t + 11} fontSize="8" fill="#2563eb">K_I</text>
      <line x1={W - 70} y1={pad.t + 18} x2={W - 58} y2={pad.t + 18} stroke="#f59e0b" strokeWidth="1.5" />
      <text x={W - 56} y={pad.t + 21} fontSize="8" fill="#f59e0b">K_II</text>
    </svg>
  )
}

// ── Main panel ─────────────────────────────────────────────────────────────

function CrackGrowthPanel({
  crack_path_m,
  crack_length_m,
  K_I_pa_sqrt_m,
  K_II_pa_sqrt_m,
  K_eff_pa_sqrt_m,
  kink_angle_deg,
  N_fatigue_cycles,
  stable,
  stop_reason,
  n_increments,
  K_handbook_initial_pa_sqrt_m,
  plate_geometry,
  paris_params,
  notes,
}) {
  const stopColors = {
    unstable_fracture: '#dc2626',
    max_steps: '#f59e0b',
    max_crack_length: '#f59e0b',
  }
  const stopColor = stopColors[stop_reason] ?? '#64748b'
  const K_Ic = paris_params?.K_Ic_pa_sqrt_m

  // Determine max K from history
  const maxKI = K_I_pa_sqrt_m?.length > 0 ? Math.max(...K_I_pa_sqrt_m) : 0

  return (
    <div style={{ fontFamily: 'system-ui, sans-serif', padding: '16px', color: '#1e293b', maxWidth: '640px' }}>
      <h3 style={{ margin: '0 0 4px', fontSize: '15px', fontWeight: 600 }}>
        Crack Propagation Simulation
        <span style={{
          marginLeft: '8px', fontSize: '11px', fontWeight: 400,
          background: stable ? '#dcfce7' : '#fee2e2',
          color: stable ? '#15803d' : '#dc2626',
          borderRadius: '4px', padding: '2px 6px',
        }}>
          {stable ? 'Stable' : 'Unstable Fracture'}
        </span>
      </h3>
      <div style={{ fontSize: '11px', color: '#94a3b8', marginBottom: '14px' }}>
        {plate_geometry?.condition ?? 'plane_stress'} · {n_increments} increments · {stop_reason?.replace(/_/g, ' ')}
      </div>

      {/* Summary row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px', marginBottom: '14px' }}>
        {[
          { label: 'Fatigue life N', value: N_fatigue_cycles > 0 ? `${N_fatigue_cycles.toExponential(2)}` : '—', unit: 'cycles' },
          { label: 'K_I (max)', value: maxKI > 0 ? `${(maxKI / 1e6).toFixed(1)}` : '—', unit: 'MPa√m' },
          { label: 'Handbook K_I (a₀)', value: K_handbook_initial_pa_sqrt_m != null ? `${(K_handbook_initial_pa_sqrt_m / 1e6).toFixed(1)}` : '—', unit: 'MPa√m' },
        ].map(({ label, value, unit }) => (
          <div key={label} style={{
            background: '#f8fafc', border: '1px solid #e2e8f0',
            borderRadius: '6px', padding: '8px 10px',
          }}>
            <div style={{ fontSize: '10px', color: '#64748b', marginBottom: '2px' }}>{label}</div>
            <div style={{ fontSize: '14px', fontWeight: 700, color: '#1e293b' }}>
              {value} <span style={{ fontSize: '10px', fontWeight: 400, color: '#94a3b8' }}>{unit}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Crack path visualiser */}
      <div style={{ marginBottom: '14px' }}>
        <div style={{ fontSize: '11px', fontWeight: 600, color: '#475569', marginBottom: '6px' }}>
          Crack Path (colour = K_I / K_Ic)
        </div>
        <CrackPathSVG
          crack_path_m={crack_path_m}
          plate_geometry={plate_geometry}
          K_I_pa_sqrt_m={K_I_pa_sqrt_m}
          K_Ic={K_Ic}
        />
        <div style={{ fontSize: '10px', color: '#94a3b8', marginTop: '4px', display: 'flex', gap: '12px' }}>
          <span>
            <span style={{ display: 'inline-block', width: '12px', height: '3px', background: 'rgb(0,200,30)', verticalAlign: 'middle', marginRight: '3px' }} />
            Low K
          </span>
          <span>
            <span style={{ display: 'inline-block', width: '12px', height: '3px', background: 'rgb(255,100,30)', verticalAlign: 'middle', marginRight: '3px' }} />
            High K
          </span>
        </div>
      </div>

      {/* K history chart */}
      <div style={{ marginBottom: '14px' }}>
        <div style={{ fontSize: '11px', fontWeight: 600, color: '#475569', marginBottom: '6px' }}>
          K_I / K_II vs Crack Length
        </div>
        <KHistoryChart
          crack_length_m={crack_length_m}
          K_I_pa_sqrt_m={K_I_pa_sqrt_m}
          K_II_pa_sqrt_m={K_II_pa_sqrt_m}
          K_Ic={K_Ic}
        />
      </div>

      {/* Paris params */}
      {paris_params && (
        <div style={{
          background: '#f0f9ff', border: '1px solid #bae6fd',
          borderRadius: '6px', padding: '8px 10px', marginBottom: '12px',
          fontSize: '11px', color: '#0369a1',
        }}>
          <span style={{ fontWeight: 600 }}>Paris:</span>
          {' '}C = {paris_params.C?.toExponential(1)}
          {' '}· m = {paris_params.m}
          {' '}· K_Ic = {((paris_params.K_Ic_pa_sqrt_m ?? 0) / 1e6).toFixed(0)} MPa√m
          {paris_params.R_ratio ? ` · R = ${paris_params.R_ratio}` : ''}
        </div>
      )}

      {/* Kink angle table (first 10 increments) */}
      {kink_angle_deg?.length > 0 && (
        <div style={{ marginBottom: '12px' }}>
          <div style={{ fontSize: '11px', fontWeight: 600, color: '#475569', marginBottom: '6px' }}>
            Increment Data {kink_angle_deg.length > 10 ? `(first 10 of ${kink_angle_deg.length})` : ''}
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '11px' }}>
            <thead>
              <tr style={{ background: '#f1f5f9' }}>
                <th style={{ padding: '3px 6px', textAlign: 'left', fontWeight: 600 }}>Step</th>
                <th style={{ padding: '3px 6px', textAlign: 'right', fontWeight: 600 }}>a [mm]</th>
                <th style={{ padding: '3px 6px', textAlign: 'right', fontWeight: 600 }}>K_I [MPa√m]</th>
                <th style={{ padding: '3px 6px', textAlign: 'right', fontWeight: 600 }}>K_II [MPa√m]</th>
                <th style={{ padding: '3px 6px', textAlign: 'right', fontWeight: 600 }}>θ_c [°]</th>
              </tr>
            </thead>
            <tbody>
              {kink_angle_deg.slice(0, 10).map((theta, i) => {
                const a_mm = (crack_length_m?.[i] ?? 0) * 1e3
                const Ki = (K_I_pa_sqrt_m?.[i] ?? 0) / 1e6
                const Kii = (K_II_pa_sqrt_m?.[i] ?? 0) / 1e6
                return (
                  <tr key={i} style={{ borderBottom: '1px solid #e2e8f0' }}>
                    <td style={{ padding: '3px 6px', color: '#64748b' }}>{i + 1}</td>
                    <td style={{ padding: '3px 6px', textAlign: 'right', fontFamily: 'monospace' }}>{a_mm.toFixed(1)}</td>
                    <td style={{ padding: '3px 6px', textAlign: 'right', fontFamily: 'monospace' }}>{Ki.toFixed(2)}</td>
                    <td style={{ padding: '3px 6px', textAlign: 'right', fontFamily: 'monospace' }}>{Kii.toFixed(2)}</td>
                    <td style={{ padding: '3px 6px', textAlign: 'right', fontFamily: 'monospace', color: Math.abs(theta) > 5 ? '#f59e0b' : '#1e293b' }}>
                      {theta.toFixed(1)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Notes */}
      {notes && (
        <div style={{
          fontSize: '10px', color: '#94a3b8', marginTop: '8px',
          borderTop: '1px solid #e2e8f0', paddingTop: '8px',
        }}>
          {notes}
        </div>
      )}
    </div>
  )
}

export default function CrackGrowthWrapper({ content }) {
  const props = { ...DEFAULTS, ...parseContent(content) }
  return <CrackGrowthPanel {...props} />
}
