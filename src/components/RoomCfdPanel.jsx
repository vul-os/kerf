/**
 * RoomCfdPanel.jsx — 3-D Room Internal-Airflow CFD results panel.
 *
 * Renders results from the cfd_room_airflow_3d LLM tool:
 *   - Plan-view (horizontal) velocity + temperature field heatmaps
 *   - Vertical-section velocity + temperature heatmaps
 *   - Per-occupant thermal comfort table (PMV, PPD, DR, age-of-air)
 *   - Summary cards: mass residual, ventilation effectiveness, vertical ΔT/Δz
 *   - Diffuser config table
 *   - Honest model notes banner
 *
 * Props (all optional, gracefully render null sections if absent):
 *   grid_dims           {number[3]}  [nX, nY, nZ] cell counts
 *   grid_spacing_m      {number[3]}  [dx, dy, dz]
 *   room_dims_m         {number[3]}  [Lx, Ly, Lz]
 *   plan_velocity_mag   {number[][]} XY slice — speed field [m/s]
 *   plan_temperature_C  {number[][]} XY slice — temperature [°C]
 *   plan_age_of_air_min {number[][]} XY slice — age [min]
 *   section_velocity_w  {number[][]} XZ slice — vertical velocity [m/s]
 *   section_temperature_C {number[][]} XZ slice — temperature [°C]
 *   T_mean_C            {number}
 *   T_max_C             {number}
 *   T_min_C             {number}
 *   velocity_max_m_s    {number}
 *   velocity_mean_m_s   {number}
 *   mass_continuity_residual {number}
 *   ventilation_effectiveness {number}
 *   max_vertical_dT_K_m {number}
 *   occupant_comfort    {object[]}  per-occupant comfort dicts
 *   model_notes         {string}
 */

// ── Colour maps ───────────────────────────────────────────────────────────────

/**
 * Map a value in [0,1] to a turbo-esque RGBA hex string (velocity = blue→red,
 * temperature = blue→yellow→red).
 */
function _tempColor(t) {
  // t in [0,1]; cool blue → yellow → hot red
  const r = Math.round(255 * Math.min(1, Math.max(0, t < 0.5 ? 2 * t : 1)))
  const g = Math.round(255 * Math.min(1, Math.max(0, t < 0.5 ? 2 * t : 2 - 2 * t)))
  const b = Math.round(255 * Math.min(1, Math.max(0, 1 - 2 * t)))
  return `rgb(${r},${g},${b})`
}

function _velColor(t) {
  // t in [0,1]; dark purple → cyan → white (velocity)
  const r = Math.round(255 * Math.min(1, Math.max(0, t < 0.7 ? t / 0.7 : 1)))
  const g = Math.round(255 * Math.min(1, Math.max(0, t < 0.5 ? t * 1.6 : 1)))
  const b = Math.round(255 * Math.min(1, Math.max(0, t < 0.3 ? 1 : 1 - (t - 0.3) / 0.7)))
  return `rgb(${r},${g},${b})`
}

// ── Utility ───────────────────────────────────────────────────────────────────

function fmt(v, d = 3) {
  if (v == null) return '—'
  if (typeof v !== 'number' || !isFinite(v)) return String(v)
  if (Math.abs(v) === 0) return '0'
  if (Math.abs(v) < 0.001 || Math.abs(v) >= 10000) return v.toExponential(2)
  return v.toPrecision(d)
}

function pmvLabel(pmv) {
  if (pmv == null) return '—'
  if (pmv < -2.5) return { text: 'Cold',   color: '#38bdf8' }
  if (pmv < -1.5) return { text: 'Cool',   color: '#7dd3fc' }
  if (pmv < -0.5) return { text: 'Sl.Cool',color: '#bae6fd' }
  if (pmv <=  0.5) return { text: 'Neutral',color: '#4ade80' }
  if (pmv <=  1.5) return { text: 'Sl.Warm',color: '#fde68a' }
  if (pmv <=  2.5) return { text: 'Warm',   color: '#fb923c' }
  return { text: 'Hot', color: '#f87171' }
}

// ── Heatmap component ─────────────────────────────────────────────────────────

function Heatmap({ data, colorFn, title, xLabel, yLabel, unit, width = 240, height = 160 }) {
  if (!data || data.length === 0) return null

  const rows = data.length
  const cols = data[0]?.length || 0
  if (rows === 0 || cols === 0) return null

  // Flatten for min/max
  const flat = data.flat()
  const vMin = Math.min(...flat)
  const vMax = Math.max(...flat)
  const vRange = vMax - vMin || 1

  const cellW = width  / cols
  const cellH = height / rows

  return (
    <div style={{ flex: '1 1 260px' }}>
      <p style={{ fontSize: 10, fontFamily: 'monospace', color: '#9ca3af',
                  textTransform: 'uppercase', letterSpacing: '0.12em', margin: '0 0 4px' }}>
        {title}
      </p>
      <div style={{ position: 'relative', display: 'inline-block' }}>
        <svg width={width} height={height} style={{ display: 'block', borderRadius: 4,
                                                    border: '1px solid #1f2937' }}>
          {data.map((row, ri) =>
            row.map((v, ci) => {
              const t = (v - vMin) / vRange
              return (
                <rect
                  key={`${ri}-${ci}`}
                  x={ci * cellW}
                  y={(rows - 1 - ri) * cellH}
                  width={cellW + 0.5}
                  height={cellH + 0.5}
                  fill={colorFn(t)}
                />
              )
            })
          )}
        </svg>
        {/* Colour bar */}
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 3,
                      fontSize: 9, fontFamily: 'monospace', color: '#6b7280' }}>
          <span>{fmt(vMin, 3)} {unit}</span>
          <span>{fmt(vMax, 3)} {unit}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 2 }}>
          {xLabel && (
            <span style={{ fontSize: 9, color: '#4b5563', fontFamily: 'monospace' }}>
              → {xLabel}
            </span>
          )}
          {yLabel && (
            <span style={{ fontSize: 9, color: '#4b5563', fontFamily: 'monospace' }}>
              ↑ {yLabel}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Summary cards ─────────────────────────────────────────────────────────────

function SummaryCard({ label, value, unit, badge, badgeColor }) {
  return (
    <div style={{
      flex: '1 1 140px',
      background: '#0d1117',
      border: '1px solid #1f2937',
      borderRadius: 8, padding: '10px 14px',
    }}>
      <p style={{ fontSize: 9, color: '#6b7280', textTransform: 'uppercase',
                  letterSpacing: '0.12em', fontFamily: 'monospace', margin: '0 0 4px' }}>
        {label}
      </p>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
        <span style={{ fontSize: 20, fontWeight: 700, color: '#e5e7eb', fontFamily: 'monospace' }}>
          {value ?? '—'}
        </span>
        {unit && (
          <span style={{ fontSize: 11, color: '#9ca3af', fontFamily: 'monospace' }}>
            {unit}
          </span>
        )}
      </div>
      {badge && (
        <span style={{
          display: 'inline-block', marginTop: 4, fontSize: 9, padding: '1px 6px',
          borderRadius: 4, background: badgeColor || '#1f2937', color: '#e5e7eb',
          fontFamily: 'monospace',
        }}>
          {badge}
        </span>
      )}
    </div>
  )
}

// ── Occupant comfort table ────────────────────────────────────────────────────

function OccupantComfortTable({ occupant_comfort }) {
  if (!occupant_comfort || occupant_comfort.length === 0) return null

  const HEADERS = ['#', 'Position', 'T_air', 'T_MRT', '|v|', 'PMV', 'PPD', 'DR', 'Age', 'ΔT/Δz']
  const UNITS   = ['', '(m)', '(°C)', '(°C)', '(m/s)', '[-]', '(%)', '(%)', '(min)', '(K/m)']

  return (
    <section>
      <p style={{ fontSize: 10, fontFamily: 'monospace', color: '#6b7280',
                  textTransform: 'uppercase', letterSpacing: '0.15em', marginBottom: 6 }}>
        Occupant Thermal Comfort
      </p>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
          <thead>
            <tr>
              {HEADERS.map((h, i) => (
                <th key={h} style={{
                  textAlign: i === 0 ? 'center' : 'right',
                  padding: '4px 8px',
                  borderBottom: '1px solid #1f2937',
                  color: '#9ca3af', fontWeight: 500, fontFamily: 'monospace',
                }}>
                  {h}<br />
                  <span style={{ fontSize: 9, color: '#4b5563' }}>{UNITS[i]}</span>
                </th>
              ))}
              <th style={{ padding: '4px 8px', borderBottom: '1px solid #1f2937',
                           color: '#9ca3af', fontFamily: 'monospace', fontSize: 10 }}>
                Sensation
              </th>
            </tr>
          </thead>
          <tbody>
            {occupant_comfort.map(oc => {
              const pmvInfo = pmvLabel(oc.pmv)
              const pos = oc.position_m ? `(${oc.position_m.map(v => v.toFixed(1)).join(',')})` : '—'
              const ppd_bad = oc.ppd > 10
              const dr_bad  = oc.draught_rate_pct > 15
              const dtdz_bad = Math.abs(oc.vertical_dT_K_m) > 3.0  // ISO 7730 threshold

              return (
                <tr key={oc.occupant_idx} style={{ borderBottom: '1px solid #111827' }}>
                  <td style={{ padding: '4px 8px', color: '#6b7280',
                               fontFamily: 'monospace', textAlign: 'center' }}>
                    {oc.occupant_idx}
                  </td>
                  <td style={{ padding: '4px 8px', color: '#9ca3af', fontFamily: 'monospace',
                               textAlign: 'right', fontSize: 9 }}>
                    {pos}
                  </td>
                  <td style={{ padding: '4px 8px', color: '#d1d5db', fontFamily: 'monospace',
                               textAlign: 'right' }}>
                    {fmt(oc.T_air_C, 3)}
                  </td>
                  <td style={{ padding: '4px 8px', color: '#d1d5db', fontFamily: 'monospace',
                               textAlign: 'right' }}>
                    {fmt(oc.T_mrt_C, 3)}
                  </td>
                  <td style={{ padding: '4px 8px', color: '#d1d5db', fontFamily: 'monospace',
                               textAlign: 'right' }}>
                    {fmt(oc.velocity_m_s, 3)}
                  </td>
                  <td style={{ padding: '4px 8px', fontFamily: 'monospace',
                               textAlign: 'right',
                               color: Math.abs(oc.pmv) <= 0.5 ? '#4ade80' : '#fbbf24' }}>
                    {fmt(oc.pmv, 3)}
                  </td>
                  <td style={{ padding: '4px 8px', fontFamily: 'monospace',
                               textAlign: 'right',
                               color: ppd_bad ? '#f87171' : '#4ade80' }}>
                    {fmt(oc.ppd, 3)}
                  </td>
                  <td style={{ padding: '4px 8px', fontFamily: 'monospace',
                               textAlign: 'right',
                               color: dr_bad ? '#fb923c' : '#d1d5db' }}>
                    {fmt(oc.draught_rate_pct, 3)}
                  </td>
                  <td style={{ padding: '4px 8px', color: '#d1d5db', fontFamily: 'monospace',
                               textAlign: 'right' }}>
                    {fmt(oc.age_of_air_min, 3)}
                  </td>
                  <td style={{ padding: '4px 8px', fontFamily: 'monospace',
                               textAlign: 'right',
                               color: dtdz_bad ? '#fbbf24' : '#d1d5db' }}>
                    {fmt(oc.vertical_dT_K_m, 3)}
                    {dtdz_bad && ' ⚠'}
                  </td>
                  <td style={{ padding: '4px 8px' }}>
                    <span style={{
                      display: 'inline-block', fontSize: 9, padding: '2px 7px',
                      borderRadius: 4, background: '#1f2937',
                      color: pmvInfo?.color || '#e5e7eb', fontFamily: 'monospace',
                      border: `1px solid ${pmvInfo?.color || '#374151'}33`,
                    }}>
                      {pmvInfo?.text || '—'}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p style={{ fontSize: 9, color: '#4b5563', fontFamily: 'monospace', marginTop: 6 }}>
        PMV: ±0.5 = comfort zone (ASHRAE 55-2020) | PPD: &lt;10% acceptable |
        DR: &lt;15% acceptable (ISO 7730) | ΔT/Δz: &lt;3 K/m acceptable (ISO 7730) |
        Age: lower = fresher supply air
      </p>
    </section>
  )
}

// ── Model notes banner ────────────────────────────────────────────────────────

function ModelNotesBanner({ model_notes }) {
  if (!model_notes) return null
  return (
    <section style={{
      background: '#0c1a2e', border: '1px solid #1e3a5f', borderRadius: 6,
      padding: '8px 12px',
    }}>
      <p style={{ fontSize: 9, color: '#6b7280', textTransform: 'uppercase',
                  letterSpacing: '0.12em', margin: '0 0 4px', fontFamily: 'monospace' }}>
        Model Limitations
      </p>
      <p style={{ fontSize: 10, color: '#93c5fd', fontFamily: 'monospace',
                  lineHeight: 1.5, margin: 0 }}>
        {model_notes}
      </p>
    </section>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

const SECTION = {
  marginBottom: 20,
}

export default function RoomCfdPanel({
  grid_dims,
  grid_spacing_m,
  room_dims_m,
  plan_velocity_mag,
  plan_temperature_C,
  plan_age_of_air_min,
  section_velocity_w,
  section_temperature_C,
  T_mean_C,
  T_max_C,
  T_min_C,
  velocity_max_m_s,
  velocity_mean_m_s,
  mass_continuity_residual,
  ventilation_effectiveness,
  max_vertical_dT_K_m,
  occupant_comfort,
  model_notes,
}) {
  const hasGrid   = grid_dims && grid_dims.length === 3
  const hasPlan   = plan_velocity_mag?.length > 0
  const hasSect   = section_temperature_C?.length > 0
  const hasComfort= occupant_comfort?.length > 0
  const hasRoom   = room_dims_m?.length === 3

  // Residual badge
  const resid = mass_continuity_residual
  const residBadge = resid != null
    ? resid < 0.01 ? 'LOW' : resid < 0.5 ? 'MED' : 'HIGH'
    : null
  const residColor = resid != null
    ? resid < 0.01 ? '#064e3b' : resid < 0.5 ? '#451a03' : '#450a0a'
    : '#1f2937'

  // Ventilation effectiveness badge
  const veBadge = ventilation_effectiveness != null
    ? ventilation_effectiveness >= 1.0 ? 'GOOD' : ventilation_effectiveness >= 0.5 ? 'OK' : 'LOW'
    : null

  // Vertical ΔT/Δz flag
  const dTdz_bad = max_vertical_dT_K_m != null && Math.abs(max_vertical_dT_K_m) > 3.0

  return (
    <div style={{
      fontFamily: 'monospace', fontSize: 12, color: '#e5e7eb',
      background: '#030712', padding: 20,
      minHeight: '100%',
    }}>

      {/* Header */}
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: '#f9fafb',
                     letterSpacing: '0.02em' }}>
          3-D Room Airflow CFD
        </h2>
        <p style={{ margin: '4px 0 0', fontSize: 10, color: '#6b7280' }}>
          SIMPLE RANS · Mixing-length turbulence · Boussinesq buoyancy
          {hasGrid && ` · Grid ${grid_dims[0]}×${grid_dims[1]}×${grid_dims[2]}`}
          {hasRoom && ` · Room ${room_dims_m.map(v => v.toFixed(1)).join('×')} m`}
        </p>
      </div>

      {/* Summary cards */}
      <div style={{ ...SECTION, display: 'flex', flexWrap: 'wrap', gap: 10 }}>
        <SummaryCard label="Mean Temp" value={fmt(T_mean_C, 3)} unit="°C" />
        <SummaryCard label="Max Speed" value={fmt(velocity_max_m_s, 3)} unit="m/s" />
        <SummaryCard
          label="Continuity Residual"
          value={fmt(resid, 2)}
          unit="m⁻¹"
          badge={residBadge}
          badgeColor={residColor}
        />
        <SummaryCard
          label="Vent. Effectiveness"
          value={fmt(ventilation_effectiveness, 3)}
          badge={veBadge}
          badgeColor={veBadge === 'GOOD' ? '#064e3b' : veBadge === 'OK' ? '#451a03' : '#450a0a'}
        />
        <SummaryCard
          label="Vert. ΔT/Δz"
          value={fmt(max_vertical_dT_K_m, 3)}
          unit="K/m"
          badge={dTdz_bad ? 'EXCEEDS ISO 7730 (>3 K/m)' : 'OK (<3 K/m)'}
          badgeColor={dTdz_bad ? '#450a0a' : '#064e3b'}
        />
      </div>

      {/* Field heatmaps — plan view */}
      {hasPlan && (
        <div style={{ ...SECTION }}>
          <p style={{ fontSize: 10, color: '#6b7280', textTransform: 'uppercase',
                      letterSpacing: '0.15em', marginBottom: 10 }}>
            Plan View (mid-height horizontal slice)
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
            <Heatmap
              data={plan_velocity_mag}
              colorFn={_velColor}
              title="Velocity |u| — Plan"
              xLabel="X"
              yLabel="Y"
              unit="m/s"
            />
            <Heatmap
              data={plan_temperature_C}
              colorFn={_tempColor}
              title="Temperature — Plan"
              xLabel="X"
              yLabel="Y"
              unit="°C"
            />
            {plan_age_of_air_min?.length > 0 && (
              <Heatmap
                data={plan_age_of_air_min}
                colorFn={_tempColor}
                title="Age of Air — Plan"
                xLabel="X"
                yLabel="Y"
                unit="min"
              />
            )}
          </div>
        </div>
      )}

      {/* Field heatmaps — vertical section */}
      {hasSect && (
        <div style={{ ...SECTION }}>
          <p style={{ fontSize: 10, color: '#6b7280', textTransform: 'uppercase',
                      letterSpacing: '0.15em', marginBottom: 10 }}>
            Vertical Section (mid-width XZ slice)
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
            {section_velocity_w?.length > 0 && (
              <Heatmap
                data={section_velocity_w}
                colorFn={_velColor}
                title="Vertical Velocity W — Section"
                xLabel="X"
                yLabel="Z (height)"
                unit="m/s"
              />
            )}
            <Heatmap
              data={section_temperature_C}
              colorFn={_tempColor}
              title="Temperature — Section"
              xLabel="X"
              yLabel="Z (height)"
              unit="°C"
            />
          </div>
        </div>
      )}

      {/* Occupant comfort table */}
      {hasComfort && (
        <div style={SECTION}>
          <OccupantComfortTable occupant_comfort={occupant_comfort} />
        </div>
      )}

      {/* Model notes */}
      <div style={SECTION}>
        <ModelNotesBanner model_notes={model_notes} />
      </div>

    </div>
  )
}
