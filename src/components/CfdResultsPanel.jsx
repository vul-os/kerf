/**
 * CfdResultsPanel.jsx — RANS CFD results panel.
 *
 * Renders a summary of post-processed CFD field data from the
 * cfd_postprocess_results / cfd_probe_field LLM tool responses.
 *
 * Sections:
 *   1. Field statistics table (U, p, k, ε, ω, nut)
 *   2. Convergence residuals bar chart (last 5 iterations per field)
 *   3. Probe results table (per-point field values)
 *   4. Wall y⁺ estimate card
 *
 * Props
 * -----
 * fieldStats    {object}  cfd_postprocess_results.field_stats
 *                         e.g. { U: {min_mag,max_mag,mean_mag,n_cells}, p: {...}, ... }
 * residuals     {object}  cfd_extract_residuals.convergence_table
 *                         e.g. { Ux: {initial,final,last_5,converged}, ... }
 * probes        {array}   cfd_probe_field.probes
 *                         e.g. [{probe_id,x,y,z,U_mag,p}, ...]
 * yplus         {object}  cfd_postprocess_results.yplus_estimate
 *                         e.g. {first_cell_height_m, target_yplus, Re_L, ...}
 * n_cells       {number}  total cell count
 * time_value    {number}  simulation time / iteration
 * turbulenceModel {string} e.g. 'kOmegaSST'
 * converged     {boolean} overall convergence flag
 */

// ── Utilities ────────────────────────────────────────────────────────────────

function fmt(v, digits = 4) {
  if (v == null) return '—'
  if (typeof v !== 'number') return String(v)
  if (Math.abs(v) === 0) return '0'
  if (Math.abs(v) < 0.001 || Math.abs(v) >= 10000) return v.toExponential(2)
  return v.toPrecision(digits)
}

// ── Colour helpers ────────────────────────────────────────────────────────────

function residualColor(r) {
  if (r == null) return '#6b7280'
  if (r < 1e-6) return '#10b981'  // emerald — converged
  if (r < 1e-4) return '#34d399'  // green-ish
  if (r < 1e-2) return '#fbbf24'  // amber
  return '#f87171'                 // red — not converged
}

// ── Field statistics table ────────────────────────────────────────────────────

const FIELD_LABELS = {
  U:       { label: 'Velocity U',         unit: 'm/s',    isVec: true },
  p:       { label: 'Pressure p',         unit: 'Pa',     isVec: false },
  k:       { label: 'TKE k',              unit: 'm²/s²',  isVec: false },
  epsilon: { label: 'Dissipation ε',      unit: 'm²/s³',  isVec: false },
  omega:   { label: 'Spec. dissipation ω',unit: '1/s',    isVec: false },
  nut:     { label: 'Eddy viscosity νt',  unit: 'm²/s',   isVec: false },
}

function FieldStatsTable({ fieldStats }) {
  if (!fieldStats || Object.keys(fieldStats).length === 0) return null
  const rows = Object.entries(FIELD_LABELS)
    .map(([key, meta]) => ({ key, meta, stats: fieldStats[key] }))
    .filter(({ stats }) => stats != null)

  return (
    <section>
      <p style={{ fontSize: 10, fontFamily: 'monospace', color: '#6b7280',
                  textTransform: 'uppercase', letterSpacing: '0.15em', marginBottom: 6 }}>
        Field Statistics
      </p>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr>
              {['Field', 'Unit', 'Min', 'Max', 'Mean', 'RMS', 'N cells'].map(h => (
                <th key={h} style={{
                  textAlign: 'left', padding: '4px 8px',
                  borderBottom: '1px solid #1f2937',
                  color: '#9ca3af', fontWeight: 500, fontFamily: 'monospace',
                }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(({ key, meta, stats }) => {
              const minV  = meta.isVec ? stats.min_mag : stats.min
              const maxV  = meta.isVec ? stats.max_mag : stats.max
              const meanV = meta.isVec ? stats.mean_mag : stats.mean
              const rmsV  = meta.isVec ? stats.rms_mag : stats.rms
              return (
                <tr key={key} style={{ borderBottom: '1px solid #111827' }}>
                  <td style={{ padding: '4px 8px', color: '#e5e7eb', fontFamily: 'monospace' }}>
                    {meta.label}
                  </td>
                  <td style={{ padding: '4px 8px', color: '#6b7280', fontFamily: 'monospace' }}>
                    {meta.unit}
                  </td>
                  {[minV, maxV, meanV, rmsV].map((v, i) => (
                    <td key={i} style={{ padding: '4px 8px', color: '#d1d5db',
                                        fontFamily: 'monospace', textAlign: 'right' }}>
                      {fmt(v)}
                    </td>
                  ))}
                  <td style={{ padding: '4px 8px', color: '#6b7280',
                               fontFamily: 'monospace', textAlign: 'right' }}>
                    {stats.n_cells?.toLocaleString() ?? '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}

// ── Residuals panel ───────────────────────────────────────────────────────────

function ResidualsPanel({ residuals, converged }) {
  if (!residuals || Object.keys(residuals).length === 0) return null
  const fields = Object.entries(residuals)

  return (
    <section>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <p style={{ fontSize: 10, fontFamily: 'monospace', color: '#6b7280',
                    textTransform: 'uppercase', letterSpacing: '0.15em', margin: 0 }}>
          Solver Residuals
        </p>
        <span style={{
          fontSize: 10, fontFamily: 'monospace', borderRadius: 4, padding: '1px 6px',
          background: converged ? '#064e3b' : '#450a0a',
          color: converged ? '#34d399' : '#f87171',
          border: `1px solid ${converged ? '#065f46' : '#7f1d1d'}`,
        }}>
          {converged ? 'CONVERGED' : 'NOT CONVERGED'}
        </span>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {fields.map(([field, data]) => {
          const last5 = data.last_5 || [data.final]
          const barMax = Math.max(data.initial ?? 1, 1e-12)

          return (
            <div key={field} style={{
              flex: '1 1 140px', borderRadius: 6, border: '1px solid #1f2937',
              background: '#0d1117', padding: 8,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between',
                            marginBottom: 6, alignItems: 'center' }}>
                <span style={{ fontSize: 11, fontFamily: 'monospace', color: '#e5e7eb' }}>
                  {field}
                </span>
                <span style={{
                  fontSize: 9, fontFamily: 'monospace',
                  color: residualColor(data.final),
                }}>
                  {fmt(data.final)}
                </span>
              </div>
              {/* Mini sparkbar chart for last 5 residuals */}
              <div style={{ display: 'flex', gap: 2, alignItems: 'flex-end', height: 24 }}>
                {last5.map((r, i) => {
                  const h = Math.max(2, 24 * (-Math.log10(Math.max(r, 1e-12)) /
                            -Math.log10(Math.max(barMax, 1e-12))))
                  return (
                    <div key={i} style={{
                      flex: 1, height: Math.min(h, 24), borderRadius: 2,
                      background: residualColor(r), opacity: 0.8 + 0.05 * i,
                    }} />
                  )
                })}
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between',
                            marginTop: 4, fontSize: 9, fontFamily: 'monospace',
                            color: '#4b5563' }}>
                <span>initial {fmt(data.initial)}</span>
                <span>{data.converged ? '✓' : '✗'}</span>
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}

// ── Probes table ──────────────────────────────────────────────────────────────

function ProbesTable({ probes }) {
  if (!probes || probes.length === 0) return null

  // Detect available fields from first probe
  const sampleFields = Object.keys(probes[0]).filter(k =>
    !['probe_id', 'x', 'y', 'z', 'nearest_cell_idx', 'distance_m', 'note'].includes(k) &&
    !k.endsWith('_mag')
  )

  const magFields = ['U_mag', 'p', 'k', 'epsilon', 'omega'].filter(k =>
    probes.some(p => p[k] != null || p[`${k}`] != null)
  )

  const dispFields = ['U_mag', 'p', 'k'].filter(f => probes.some(p => p[f] != null))

  return (
    <section>
      <p style={{ fontSize: 10, fontFamily: 'monospace', color: '#6b7280',
                  textTransform: 'uppercase', letterSpacing: '0.15em', marginBottom: 6 }}>
        Probe Samples ({probes.length} points)
      </p>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
          <thead>
            <tr>
              {['#', 'x (m)', 'y (m)', 'z (m)',
                ...dispFields,
                'Cell dist (m)'].map(h => (
                <th key={h} style={{
                  textAlign: 'right', padding: '3px 7px',
                  borderBottom: '1px solid #1f2937',
                  color: '#9ca3af', fontWeight: 500, fontFamily: 'monospace',
                }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {probes.map(p => (
              <tr key={p.probe_id} style={{ borderBottom: '1px solid #111827' }}>
                <td style={{ padding: '3px 7px', color: '#6b7280',
                             fontFamily: 'monospace', textAlign: 'right' }}>
                  {p.probe_id}
                </td>
                {['x', 'y', 'z'].map(c => (
                  <td key={c} style={{ padding: '3px 7px', color: '#9ca3af',
                                      fontFamily: 'monospace', textAlign: 'right' }}>
                    {fmt(p[c], 3)}
                  </td>
                ))}
                {dispFields.map(f => (
                  <td key={f} style={{ padding: '3px 7px', color: '#d1d5db',
                                      fontFamily: 'monospace', textAlign: 'right' }}>
                    {fmt(p[f])}
                  </td>
                ))}
                <td style={{ padding: '3px 7px', color: '#4b5563',
                             fontFamily: 'monospace', textAlign: 'right' }}>
                  {fmt(p.distance_m, 3)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

// ── Wall y⁺ card ──────────────────────────────────────────────────────────────

function YplusCard({ yplus }) {
  if (!yplus || yplus.error || Object.keys(yplus).length === 0) return null
  const good = yplus.first_cell_height_m != null

  return (
    <section style={{
      borderRadius: 6, border: '1px solid #1f2937',
      background: '#0d1117', padding: 10,
    }}>
      <p style={{ fontSize: 10, fontFamily: 'monospace', color: '#6b7280',
                  textTransform: 'uppercase', letterSpacing: '0.15em', marginBottom: 8 }}>
        Wall y⁺ Estimate
      </p>
      {good ? (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
          {[
            { label: 'Re_L', value: fmt(yplus.Re_L, 3) },
            { label: 'u_τ', value: `${fmt(yplus.u_tau_m_s, 3)} m/s` },
            { label: 'Δy₁ (y⁺=30)', value: `${fmt(yplus.first_cell_height_m)} m` },
            { label: 'C_f', value: fmt(yplus.Cf_schlichting, 3) },
            { label: 'target y⁺', value: yplus.target_yplus },
            { label: 'method', value: 'Schlichting 1979' },
          ].map(({ label, value }) => (
            <div key={label}>
              <div style={{ fontSize: 9, color: '#6b7280', fontFamily: 'monospace' }}>
                {label}
              </div>
              <div style={{ fontSize: 12, color: '#e5e7eb', fontFamily: 'monospace' }}>
                {value}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <span style={{ fontSize: 11, color: '#6b7280', fontFamily: 'monospace' }}>
          Provide U_ref, L_ref, nu for y⁺ estimate.
        </span>
      )}
      {yplus.note && (
        <p style={{ fontSize: 9, color: '#4b5563', fontFamily: 'monospace', marginTop: 6 }}>
          {yplus.note}
        </p>
      )}
    </section>
  )
}

// ── Header bar ────────────────────────────────────────────────────────────────

function HeaderBar({ n_cells, time_value, turbulenceModel, converged }) {
  const chips = [
    n_cells != null && { label: 'Cells', value: n_cells.toLocaleString() },
    time_value != null && { label: 'Time / Iter', value: fmt(time_value, 4) },
    turbulenceModel && { label: 'Turbulence', value: turbulenceModel },
  ].filter(Boolean)

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
      {chips.map(({ label, value }) => (
        <span key={label} style={{
          display: 'inline-flex', alignItems: 'center', gap: 4,
          fontSize: 10, fontFamily: 'monospace', color: '#9ca3af',
          background: '#111827', border: '1px solid #1f2937',
          borderRadius: 4, padding: '2px 7px',
        }}>
          <span style={{ color: '#6b7280' }}>{label}:</span>
          {value}
        </span>
      ))}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function CfdResultsPanel({
  fieldStats = null,
  residuals = null,
  probes = null,
  yplus = null,
  n_cells = null,
  time_value = null,
  turbulenceModel = null,
  converged = false,
}) {
  const hasAny = fieldStats || residuals || probes || yplus

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 14,
      padding: 12, borderRadius: 8, border: '1px solid #1f2937',
      background: '#030712', color: '#e5e7eb',
    }}>
      <HeaderBar
        n_cells={n_cells}
        time_value={time_value}
        turbulenceModel={turbulenceModel}
        converged={converged}
      />

      {!hasAny && (
        <div style={{ textAlign: 'center', color: '#4b5563', fontSize: 13,
                      padding: '24px 0', fontFamily: 'monospace' }}>
          No CFD results — run a simulation and call cfd_postprocess_results
        </div>
      )}

      <FieldStatsTable fieldStats={fieldStats} />
      <ResidualsPanel residuals={residuals} converged={converged} />
      <ProbesTable probes={probes} />
      <YplusCard yplus={yplus} />
    </div>
  )
}
