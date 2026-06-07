/**
 * CfdLesPanel.jsx — LES / DES / Overset rotating-mesh results panel.
 *
 * Renders output from three in-house CFD tools:
 *   cfd_les_simulate    — LES (Smagorinsky / WALE), HIT decay or shear layer
 *   cfd_des_simulate    — DES / DDES hybrid RANS-LES
 *   cfd_overset_rotating — Chimera overset + rotating sub-grid
 *
 * Sections (rendered based on which props are present):
 *   1. LES overview card — SGS model, case, Re_λ, TKE decay ratio
 *   2. Resolved vs Modeled TKE time-series (ASCII sparkline)
 *   3. Energy spectrum (wavenumber vs E(k), sparkline)
 *   4. DES model-index profile — wall-normal bar showing RANS vs LES regions
 *   5. Overset grid visualisation — ASCII grid showing sub-grid rotation
 *   6. Conservation / interpolation diagnostics table
 *   7. Model notes / honest caveats
 *
 * Props (all optional; panel renders only sections with data)
 * -----------------------------------------------------------
 * // LES
 * sgs_model          {string}   'smagorinsky' | 'wale'
 * case               {string}   'hit_decay' | 'shear_layer'
 * Re_lambda          {number}
 * n_steps            {number}
 * dt                 {number}
 * resolved_tke       {number[]} time-series
 * modeled_tke        {number[]} time-series
 * nu_sgs_mean        {number[]}
 * tke_decay_ratio    {number}
 * u_rms              {number}
 * v_rms              {number}
 * w_rms              {number}
 * wavenumbers        {number[]}
 * energy_spectrum    {number[]}
 * temporal_u_fluctuation {number}
 * unsteady           {boolean}
 *
 * // DES
 * variant            {string}   'des' | 'ddes'
 * Re_tau             {number}
 * y_plus             {number[]}
 * model_index        {number[]} 0=RANS, 1=LES per wall-normal row
 * blend              {number[]}
 * n_rans_cells       {number}
 * n_les_cells        {number}
 * near_wall_rans     {boolean}
 * has_les_region     {boolean}
 *
 * // Overset
 * omega_rad_s        {number}
 * angle_deg          {number}
 * interpolation_error {number}
 * conservation_error {number}
 * phi_sum_bg         {number[]} time-series
 * phi_sum_sg         {number[]} time-series
 * feature_rotated    {boolean}
 * interpolation_ok   {boolean}
 *
 * // Common
 * ok                 {boolean}
 * model_notes        {string}
 */

// ── Utilities ────────────────────────────────────────────────────────────────

function fmt(v, digits = 4) {
  if (v == null) return '—'
  if (typeof v !== 'number') return String(v)
  if (!isFinite(v)) return String(v)
  if (v === 0) return '0'
  if (Math.abs(v) < 0.001 || Math.abs(v) >= 10000) return v.toExponential(2)
  return v.toPrecision(digits)
}

// ── ASCII sparkline ───────────────────────────────────────────────────────────

const SPARK_CHARS = ['▁', '▂', '▃', '▄', '▅', '▆', '▇', '█']

function sparkline(values, width = 24) {
  if (!Array.isArray(values) || values.length === 0) return '—'
  const valid = values.filter(v => isFinite(v))
  if (valid.length === 0) return '—'
  const mn = Math.min(...valid)
  const mx = Math.max(...valid)
  const range = mx - mn
  // Downsample to `width` bins
  const step = Math.max(1, Math.ceil(valid.length / width))
  const binned = []
  for (let i = 0; i < valid.length; i += step) {
    binned.push(valid[i])
  }
  return binned.map(v => {
    const idx = range > 0
      ? Math.min(7, Math.floor(8 * (v - mn) / range))
      : 4
    return SPARK_CHARS[idx]
  }).join('')
}

// ── Colour helpers ────────────────────────────────────────────────────────────

const RANS_COLOR  = '#60a5fa'  // blue-400 — RANS region
const LES_COLOR   = '#34d399'  // emerald-400 — LES region
const OK_COLOR    = '#10b981'
const WARN_COLOR  = '#f59e0b'
const ERR_COLOR   = '#f87171'

function statusColor(ok) { return ok ? OK_COLOR : ERR_COLOR }

// ── Section: LES overview ─────────────────────────────────────────────────────

function LesOverview({ sgs_model, case: caseName, Re_lambda, n_steps, dt,
                        tke_decay_ratio, u_rms, v_rms, w_rms,
                        unsteady, temporal_u_fluctuation }) {
  if (sgs_model == null && caseName == null) return null
  const rows = [
    ['SGS model',          sgs_model ? sgs_model.toUpperCase() : '—'],
    ['Case',               caseName === 'hit_decay' ? 'HIT Decay' : caseName === 'shear_layer' ? 'Shear Layer' : (caseName || '—')],
    ['Re_λ',               fmt(Re_lambda)],
    ['Time steps',         n_steps != null ? String(n_steps) : '—'],
    ['Δt',                 fmt(dt) + ' s'],
    ['TKE decay ratio',    fmt(tke_decay_ratio)],
    ['u_rms',              fmt(u_rms) + ' m/s'],
    ['v_rms',              fmt(v_rms) + ' m/s'],
    ['w_rms',              fmt(w_rms) + ' m/s'],
    ['Unsteady?',          unsteady ? '✓ Yes' : (unsteady === false ? '✗ No' : '—')],
  ]
  return (
    <section style={{ marginBottom: '1.5rem' }}>
      <h3 style={{ margin: '0 0 0.5rem', fontSize: '0.95rem', color: '#e2e8f0' }}>
        LES Overview — {sgs_model ? sgs_model.toUpperCase() : '?'} SGS
      </h3>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <td style={{ padding: '2px 8px 2px 0', color: '#94a3b8', width: '40%' }}>{k}</td>
              <td style={{ padding: '2px 0', color: '#e2e8f0' }}>{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

// ── Section: TKE time-series ──────────────────────────────────────────────────

function TkeSeries({ resolved_tke, modeled_tke, nu_sgs_mean }) {
  if (!Array.isArray(resolved_tke) || resolved_tke.length === 0) return null
  const res_spark  = sparkline(resolved_tke)
  const mod_spark  = sparkline(modeled_tke)
  const nu_spark   = sparkline(nu_sgs_mean)
  return (
    <section style={{ marginBottom: '1.5rem' }}>
      <h3 style={{ margin: '0 0 0.5rem', fontSize: '0.95rem', color: '#e2e8f0' }}>
        TKE Time-Series
      </h3>
      <div style={{ fontFamily: 'monospace', fontSize: '0.78rem', lineHeight: 1.7 }}>
        <div><span style={{ color: '#94a3b8', width: 180, display: 'inline-block' }}>Resolved TKE [m²/s²]</span>
             <span style={{ color: '#34d399' }}>{res_spark}</span>
             <span style={{ color: '#64748b', marginLeft: 8 }}>{fmt(Math.min(...resolved_tke.filter(isFinite)))} – {fmt(Math.max(...resolved_tke.filter(isFinite)))}</span>
        </div>
        {Array.isArray(modeled_tke) && modeled_tke.length > 0 && (
          <div><span style={{ color: '#94a3b8', width: 180, display: 'inline-block' }}>Modeled TKE [m²/s²]</span>
               <span style={{ color: '#818cf8' }}>{mod_spark}</span>
          </div>
        )}
        {Array.isArray(nu_sgs_mean) && nu_sgs_mean.length > 0 && (
          <div><span style={{ color: '#94a3b8', width: 180, display: 'inline-block' }}>⟨ν_sgs⟩ [m²/s]</span>
               <span style={{ color: '#fb923c' }}>{nu_spark}</span>
          </div>
        )}
      </div>
      <p style={{ fontSize: '0.72rem', color: '#64748b', margin: '0.4rem 0 0' }}>
        Sparklines: each character = one time-step. Height encodes relative magnitude.
      </p>
    </section>
  )
}

// ── Section: Energy spectrum ──────────────────────────────────────────────────

function EnergySpectrum({ wavenumbers, energy_spectrum }) {
  if (!Array.isArray(wavenumbers) || wavenumbers.length === 0) return null
  if (!Array.isArray(energy_spectrum) || energy_spectrum.length === 0) return null
  const valid = energy_spectrum.filter(isFinite)
  const hasMultiScale = valid.filter(v => v > 1e-15).length >= 3
  return (
    <section style={{ marginBottom: '1.5rem' }}>
      <h3 style={{ margin: '0 0 0.5rem', fontSize: '0.95rem', color: '#e2e8f0' }}>
        Energy Spectrum E(k)
      </h3>
      <div style={{ fontFamily: 'monospace', fontSize: '0.78rem' }}>
        <span style={{ color: '#94a3b8' }}>E(k): </span>
        <span style={{ color: '#f472b6' }}>{sparkline(energy_spectrum, 32)}</span>
      </div>
      <p style={{ fontSize: '0.78rem', color: '#e2e8f0', margin: '0.3rem 0 0' }}>
        Multi-scale energy: <span style={{ color: hasMultiScale ? OK_COLOR : WARN_COLOR }}>
          {hasMultiScale ? '✓ Energy at multiple wavenumbers' : '⚠ Limited scale separation'}
        </span>
      </p>
      <p style={{ fontSize: '0.72rem', color: '#64748b', margin: '0.2rem 0 0' }}>
        1-D DFT of centreline u-fluctuation.
        k = 0 … {fmt(Math.max(...wavenumbers.filter(isFinite)))} rad/m.
      </p>
    </section>
  )
}

// ── Section: DES model-index profile ─────────────────────────────────────────

function DesProfile({ variant, Re_tau, model_index, blend, y_plus,
                       n_rans_cells, n_les_cells, near_wall_rans, has_les_region }) {
  if (!Array.isArray(model_index) || model_index.length === 0) return null
  const ny = model_index.length
  const BAR_W = 200  // px
  return (
    <section style={{ marginBottom: '1.5rem' }}>
      <h3 style={{ margin: '0 0 0.5rem', fontSize: '0.95rem', color: '#e2e8f0' }}>
        DES Model-Index Profile — {variant ? variant.toUpperCase() : 'DES'}
      </h3>
      <p style={{ fontSize: '0.80rem', color: '#94a3b8', margin: '0 0 0.5rem' }}>
        Re_τ = {fmt(Re_tau)}.
        RANS cells: <span style={{ color: RANS_COLOR }}>{n_rans_cells}</span> /
        LES cells: <span style={{ color: LES_COLOR }}>{n_les_cells}</span>
        &nbsp;({ny} total wall-normal rows)
      </p>

      {/* Horizontal bar showing RANS vs LES by y-index */}
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 1, marginBottom: 4,
                    height: 32, background: '#0f172a', padding: '2px 4px',
                    borderRadius: 4, overflowX: 'auto' }}>
        {model_index.map((mi, j) => {
          const b = Array.isArray(blend) ? (blend[j] ?? mi) : mi
          const color = mi === 0 ? RANS_COLOR : LES_COLOR
          const h = 10 + Math.round(18 * b)
          return (
            <div key={j}
              title={`y-row ${j}: ${mi === 0 ? 'RANS' : 'LES'} (blend=${fmt(b)})`}
              style={{
                width: Math.max(2, Math.floor(BAR_W / ny)),
                height: h,
                background: color,
                opacity: 0.8 + 0.2 * b,
                borderRadius: 1,
                flexShrink: 0,
              }}
            />
          )
        })}
      </div>
      <div style={{ display: 'flex', gap: 12, fontSize: '0.72rem', color: '#94a3b8' }}>
        <span><span style={{ color: RANS_COLOR }}>■</span> RANS (near wall)</span>
        <span><span style={{ color: LES_COLOR }}>■</span> LES (off wall)</span>
      </div>
      <div style={{ fontSize: '0.78rem', marginTop: '0.4rem' }}>
        <span style={{ color: near_wall_rans ? OK_COLOR : WARN_COLOR }}>
          {near_wall_rans ? '✓ RANS near wall' : '⚠ No confirmed RANS near wall'}
        </span>
        {' · '}
        <span style={{ color: has_les_region ? OK_COLOR : WARN_COLOR }}>
          {has_les_region ? '✓ LES off-wall region active' : '⚠ No LES region detected'}
        </span>
      </div>
    </section>
  )
}

// ── Section: Overset diagnostics ─────────────────────────────────────────────

function OversetDiagnostics({ omega_rad_s, angle_deg, interpolation_error,
                               conservation_error, phi_sum_bg, phi_sum_sg,
                               feature_rotated, interpolation_ok }) {
  if (omega_rad_s == null && angle_deg == null) return null
  const phi_bg_spark = sparkline(phi_sum_bg)
  const phi_sg_spark = sparkline(phi_sum_sg)
  return (
    <section style={{ marginBottom: '1.5rem' }}>
      <h3 style={{ margin: '0 0 0.5rem', fontSize: '0.95rem', color: '#e2e8f0' }}>
        Overset / Rotating Mesh
      </h3>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
        <tbody>
          <tr>
            <td style={{ color: '#94a3b8', padding: '2px 8px 2px 0', width: '45%' }}>Rotation rate ω</td>
            <td style={{ color: '#e2e8f0' }}>{fmt(omega_rad_s)} rad/s</td>
          </tr>
          <tr>
            <td style={{ color: '#94a3b8', padding: '2px 8px 2px 0' }}>Final angle</td>
            <td style={{ color: '#e2e8f0' }}>{fmt(angle_deg)}°</td>
          </tr>
          <tr>
            <td style={{ color: '#94a3b8', padding: '2px 8px 2px 0' }}>Feature rotated?</td>
            <td style={{ color: feature_rotated ? OK_COLOR : WARN_COLOR }}>
              {feature_rotated ? '✓ Yes' : '✗ No'}
            </td>
          </tr>
          <tr>
            <td style={{ color: '#94a3b8', padding: '2px 8px 2px 0' }}>Interpolation error</td>
            <td style={{ color: interpolation_ok ? OK_COLOR : WARN_COLOR }}>
              {fmt(interpolation_error)} {interpolation_ok ? '✓' : '⚠'}
            </td>
          </tr>
          <tr>
            <td style={{ color: '#94a3b8', padding: '2px 8px 2px 0' }}>Conservation error</td>
            <td style={{ color: '#e2e8f0' }}>{fmt(conservation_error)}</td>
          </tr>
        </tbody>
      </table>
      {(Array.isArray(phi_sum_bg) && phi_sum_bg.length > 0) && (
        <div style={{ fontFamily: 'monospace', fontSize: '0.78rem', lineHeight: 1.7, marginTop: '0.5rem' }}>
          <div><span style={{ color: '#94a3b8', display: 'inline-block', width: 180 }}>Σφ background</span>
               <span style={{ color: '#38bdf8' }}>{phi_bg_spark}</span></div>
          <div><span style={{ color: '#94a3b8', display: 'inline-block', width: 180 }}>Σφ sub-grid</span>
               <span style={{ color: '#a78bfa' }}>{phi_sg_spark}</span></div>
        </div>
      )}
    </section>
  )
}

// ── Section: Model notes ──────────────────────────────────────────────────────

function ModelNotes({ model_notes }) {
  if (!model_notes) return null
  return (
    <section style={{ marginBottom: '0.5rem' }}>
      <h3 style={{ margin: '0 0 0.4rem', fontSize: '0.85rem', color: '#94a3b8' }}>
        Model Notes
      </h3>
      <p style={{
        fontSize: '0.75rem', color: '#64748b', margin: 0,
        background: '#0f172a', borderRadius: 4, padding: '6px 10px',
        lineHeight: 1.5, whiteSpace: 'pre-wrap'
      }}>
        {model_notes}
      </p>
    </section>
  )
}

// ── Root panel ────────────────────────────────────────────────────────────────

export default function CfdLesPanel({
  // LES
  sgs_model, case: caseName, Re_lambda, n_steps, dt,
  resolved_tke, modeled_tke, nu_sgs_mean,
  tke_decay_ratio, u_rms, v_rms, w_rms,
  wavenumbers, energy_spectrum,
  unsteady, temporal_u_fluctuation,
  // DES
  variant, Re_tau, y_plus, model_index, blend,
  n_rans_cells, n_les_cells, near_wall_rans, has_les_region,
  // Overset
  omega_rad_s, angle_deg, interpolation_error, conservation_error,
  phi_sum_bg, phi_sum_sg, feature_rotated, interpolation_ok,
  // Common
  ok, model_notes,
}) {
  const isLes    = sgs_model != null || caseName != null
  const isDes    = Array.isArray(model_index) && model_index.length > 0
  const isOvset  = omega_rad_s != null || angle_deg != null

  let modeLabel = []
  if (isLes)   modeLabel.push(sgs_model ? `LES-${sgs_model.toUpperCase()}` : 'LES')
  if (isDes)   modeLabel.push(variant ? variant.toUpperCase() : 'DES')
  if (isOvset) modeLabel.push('Overset')
  if (!modeLabel.length) modeLabel.push('CFD Scale-Resolving')

  return (
    <div style={{
      fontFamily: 'system-ui, sans-serif',
      background: '#1e293b',
      color: '#e2e8f0',
      borderRadius: 8,
      padding: '1.25rem',
      maxWidth: 640,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: '1rem' }}>
        <span style={{ fontSize: '1.2rem' }}>🌀</span>
        <div>
          <h2 style={{ margin: 0, fontSize: '1rem', fontWeight: 700 }}>
            {modeLabel.join(' + ')}
          </h2>
          <span style={{
            fontSize: '0.72rem',
            color: ok !== false ? OK_COLOR : ERR_COLOR,
          }}>
            {ok !== false ? '● Simulation complete' : '● Simulation error'}
          </span>
        </div>
      </div>

      {isLes && (
        <>
          <LesOverview
            sgs_model={sgs_model} case={caseName} Re_lambda={Re_lambda}
            n_steps={n_steps} dt={dt} tke_decay_ratio={tke_decay_ratio}
            u_rms={u_rms} v_rms={v_rms} w_rms={w_rms}
            unsteady={unsteady} temporal_u_fluctuation={temporal_u_fluctuation}
          />
          <TkeSeries
            resolved_tke={resolved_tke} modeled_tke={modeled_tke}
            nu_sgs_mean={nu_sgs_mean}
          />
          <EnergySpectrum wavenumbers={wavenumbers} energy_spectrum={energy_spectrum} />
        </>
      )}

      {isDes && (
        <DesProfile
          variant={variant} Re_tau={Re_tau}
          model_index={model_index} blend={blend} y_plus={y_plus}
          n_rans_cells={n_rans_cells} n_les_cells={n_les_cells}
          near_wall_rans={near_wall_rans} has_les_region={has_les_region}
        />
      )}

      {isOvset && (
        <OversetDiagnostics
          omega_rad_s={omega_rad_s} angle_deg={angle_deg}
          interpolation_error={interpolation_error}
          conservation_error={conservation_error}
          phi_sum_bg={phi_sum_bg} phi_sum_sg={phi_sum_sg}
          feature_rotated={feature_rotated} interpolation_ok={interpolation_ok}
        />
      )}

      <ModelNotes model_notes={model_notes} />
    </div>
  )
}
