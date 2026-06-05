/**
 * ReactingFlowPanel.jsx — Multi-species reacting-flow results panel.
 *
 * Renders output from the cfd_reacting_flow_multispecies LLM tool:
 *   - Mechanism summary + fuel info
 *   - Outlet species mass fractions bar chart
 *   - Key scalar cards: T_outlet, T_max, T_adiabatic, fuel conversion
 *   - Optional species profile plot (when return_profiles=true)
 *   - Optional temperature profile
 *
 * Props
 * -----
 * mechanism              {string}  e.g. 'CH4_1step', 'H2_1step', 'custom'
 * n_species              {number}
 * species_names          {string[]}
 * outlet_mass_fractions  {object}  { CH4: 0.001, O2: 0.05, CO2: 0.18, ... }
 * outlet_temperature_K   {number}
 * max_temperature_K      {number}
 * adiabatic_flame_temperature_K {number}
 * fuel                   {string}  fuel species name
 * outlet_fuel_conversion {number}  0–1
 * mean_fuel_conversion   {number}  0–1
 * reactor_length_m       {number}
 * velocity_m_per_s       {number}
 * x_m                    {number[]} optional — x positions
 * temperature_K_profile  {number[]} optional — T per cell
 * fuel_conversion_profile {number[]} optional
 */

// ── Utilities ────────────────────────────────────────────────────────────────

function fmt(v, digits = 4) {
  if (v == null) return '—'
  if (typeof v !== 'number') return String(v)
  if (v === 0) return '0'
  if (Math.abs(v) < 0.001 || Math.abs(v) >= 100000) return v.toExponential(2)
  return v.toPrecision(digits)
}

function pct(v) {
  if (v == null) return '—'
  return `${(v * 100).toFixed(1)}%`
}

// Temperature-mapped colour: blue (cold) → orange → red (hot)
function tempColor(T, T_min = 300, T_max = 2500) {
  const t = Math.max(0, Math.min(1, (T - T_min) / (T_max - T_min)))
  // Blue → cyan → orange → red
  if (t < 0.33) {
    const s = t / 0.33
    return `rgb(${Math.round(30 + s * 180)}, ${Math.round(100 + s * 100)}, ${Math.round(200 - s * 80)})`
  }
  if (t < 0.66) {
    const s = (t - 0.33) / 0.33
    return `rgb(${Math.round(210 + s * 45)}, ${Math.round(180 - s * 60)}, ${Math.round(120 - s * 80)})`
  }
  const s = (t - 0.66) / 0.34
  return `rgb(${Math.round(255)}, ${Math.round(120 - s * 80)}, ${Math.round(40 - s * 30)})`
}

// Species colour palette (consistent across charts)
const SPECIES_COLORS = {
  CH4:  '#f59e0b',  // amber — fuel
  H2:   '#fbbf24',  // yellow — fuel
  A:    '#f59e0b',  // amber — generic fuel
  O2:   '#60a5fa',  // blue — oxidizer
  B:    '#60a5fa',  // blue — generic oxidizer
  CO2:  '#34d399',  // emerald — product
  H2O:  '#4ade80',  // green — product
  CO:   '#a78bfa',  // purple — intermediate
  OH:   '#c084fc',  // lavender
  C:    '#fb923c',  // orange — product (generic)
  N2:   '#6b7280',  // grey — inert
  M:    '#6b7280',  // grey — bath gas
}

function speciesColor(name) {
  return SPECIES_COLORS[name] ?? '#9ca3af'
}

// ── Scalar card ───────────────────────────────────────────────────────────────

function ScalarCard({ label, value, unit, sub, color = '#e5e7eb', warn }) {
  return (
    <div style={{
      flex: '1 1 120px', borderRadius: 6,
      border: `1px solid ${warn ? '#b45309' : '#1f2937'}`,
      background: warn ? '#1c1008' : '#0d1117',
      padding: '8px 10px',
    }}>
      <div style={{ fontSize: 9, fontFamily: 'monospace', color: '#6b7280',
                    textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ fontSize: 18, fontFamily: 'monospace', color, fontWeight: 600 }}>
        {value}
        {unit && <span style={{ fontSize: 11, color: '#6b7280', marginLeft: 4 }}>{unit}</span>}
      </div>
      {sub && (
        <div style={{ fontSize: 9, color: '#4b5563', fontFamily: 'monospace', marginTop: 3 }}>
          {sub}
        </div>
      )}
    </div>
  )
}

// ── Species mass-fraction bar chart ───────────────────────────────────────────

function SpeciesBarChart({ outletMF, speciesNames }) {
  if (!outletMF || speciesNames.length === 0) return null
  const entries = speciesNames.map(name => ({
    name,
    Y: outletMF[name] ?? 0,
    color: speciesColor(name),
  })).sort((a, b) => b.Y - a.Y)

  const maxY = Math.max(...entries.map(e => e.Y), 1e-6)

  return (
    <section>
      <p style={{ fontSize: 10, fontFamily: 'monospace', color: '#6b7280',
                  textTransform: 'uppercase', letterSpacing: '0.15em', marginBottom: 8 }}>
        Outlet Species Mass Fractions
      </p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
        {entries.map(({ name, Y, color }) => (
          <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{
              width: 40, fontSize: 11, fontFamily: 'monospace',
              color, textAlign: 'right', flexShrink: 0,
            }}>
              {name}
            </span>
            <div style={{
              flex: 1, height: 14, background: '#111827',
              borderRadius: 3, overflow: 'hidden',
            }}>
              <div style={{
                width: `${(Y / maxY) * 100}%`,
                height: '100%',
                background: color,
                borderRadius: 3,
                opacity: 0.85,
                minWidth: Y > 0 ? 2 : 0,
              }} />
            </div>
            <span style={{
              width: 68, fontSize: 10, fontFamily: 'monospace',
              color: '#9ca3af', textAlign: 'right', flexShrink: 0,
            }}>
              {Y < 1e-3 ? Y.toExponential(2) : Y.toFixed(4)}
            </span>
          </div>
        ))}
      </div>
    </section>
  )
}

// ── Inline SVG profile plot ───────────────────────────────────────────────────

function ProfilePlot({ xArr, yArr, label, unit, color = '#60a5fa', yMin, yMax }) {
  if (!xArr || !yArr || xArr.length < 2) return null
  const W = 260, H = 80, PAD = 4
  const xMin = xArr[0], xMaxV = xArr[xArr.length - 1]
  const vMin = yMin ?? Math.min(...yArr)
  const vMax = yMax ?? Math.max(...yArr)
  const xRange = xMaxV - xMin || 1
  const yRange = vMax - vMin || 1

  const toSvg = (xi, yi) => ({
    x: PAD + ((xi - xMin) / xRange) * (W - 2 * PAD),
    y: H - PAD - ((yi - vMin) / yRange) * (H - 2 * PAD),
  })

  const pts = xArr.map((x, i) => toSvg(x, yArr[i]))
  const d = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')

  return (
    <div style={{ flex: '1 1 260px' }}>
      <div style={{ fontSize: 9, fontFamily: 'monospace', color: '#6b7280',
                    textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: 3 }}>
        {label} [{unit}]
      </div>
      <svg width={W} height={H} style={{ display: 'block', borderRadius: 4,
                                         background: '#0d1117', border: '1px solid #1f2937' }}>
        <path d={d} stroke={color} strokeWidth="1.5" fill="none" opacity="0.9" />
        {/* Axis labels */}
        <text x={PAD + 1} y={H - 1} fontSize="7" fill="#4b5563" fontFamily="monospace">
          {xMin.toFixed(3)}m
        </text>
        <text x={W - PAD - 1} y={H - 1} fontSize="7" fill="#4b5563"
              fontFamily="monospace" textAnchor="end">
          {xMaxV.toFixed(3)}m
        </text>
        <text x={PAD + 1} y={10} fontSize="7" fill="#4b5563" fontFamily="monospace">
          {vMax > 1000 ? vMax.toFixed(0) : vMax.toFixed(2)}
        </text>
        <text x={PAD + 1} y={H - PAD - 3} fontSize="7" fill="#4b5563" fontFamily="monospace">
          {vMin > 1000 ? vMin.toFixed(0) : vMin.toFixed(2)}
        </text>
      </svg>
    </div>
  )
}

// ── Mechanism info header ─────────────────────────────────────────────────────

function MechanismHeader({ mechanism, fuel, nSpecies, length, velocity }) {
  const chips = [
    mechanism  && { label: 'Mechanism', value: mechanism },
    fuel       && { label: 'Fuel', value: fuel },
    nSpecies   && { label: 'Species', value: nSpecies },
    length     && { label: 'Length', value: `${length} m` },
    velocity   && { label: 'U', value: `${velocity} m/s` },
  ].filter(Boolean)

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginBottom: 10 }}>
      {chips.map(({ label, value }) => (
        <span key={label} style={{
          display: 'inline-flex', alignItems: 'center', gap: 4,
          fontSize: 10, fontFamily: 'monospace', color: '#9ca3af',
          background: '#111827', border: '1px solid #1f2937',
          borderRadius: 4, padding: '2px 7px',
        }}>
          <span style={{ color: '#6b7280' }}>{label}:</span>
          <span style={{ color: '#e5e7eb' }}>{value}</span>
        </span>
      ))}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function ReactingFlowPanel({
  mechanism = null,
  n_species = null,
  species_names = [],
  outlet_mass_fractions = null,
  outlet_temperature_K = null,
  max_temperature_K = null,
  adiabatic_flame_temperature_K = null,
  fuel = null,
  outlet_fuel_conversion = null,
  mean_fuel_conversion = null,
  reactor_length_m = null,
  velocity_m_per_s = null,
  x_m = null,
  temperature_K_profile = null,
  fuel_conversion_profile = null,
}) {
  const hasResults = outlet_mass_fractions || outlet_temperature_K != null

  const conversionColor = outlet_fuel_conversion >= 0.95
    ? '#34d399'
    : outlet_fuel_conversion >= 0.7
    ? '#fbbf24'
    : '#f87171'

  const TadWarn = adiabatic_flame_temperature_K > 3000

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 14,
      padding: 12, borderRadius: 8, border: '1px solid #1f2937',
      background: '#030712', color: '#e5e7eb',
    }}>
      {/* Header */}
      <MechanismHeader
        mechanism={mechanism}
        fuel={fuel}
        nSpecies={n_species}
        length={reactor_length_m}
        velocity={velocity_m_per_s}
      />

      {!hasResults && (
        <div style={{ textAlign: 'center', color: '#4b5563', fontSize: 13,
                      padding: '24px 0', fontFamily: 'monospace' }}>
          No reacting-flow results — call cfd_reacting_flow_multispecies
        </div>
      )}

      {hasResults && (
        <>
          {/* Key scalar cards */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            <ScalarCard
              label="Outlet T"
              value={outlet_temperature_K != null ? outlet_temperature_K.toFixed(0) : '—'}
              unit="K"
              color={tempColor(outlet_temperature_K ?? 300)}
            />
            <ScalarCard
              label="Peak T"
              value={max_temperature_K != null ? max_temperature_K.toFixed(0) : '—'}
              unit="K"
              color={tempColor(max_temperature_K ?? 300)}
            />
            <ScalarCard
              label="T adiabatic"
              value={adiabatic_flame_temperature_K != null
                ? adiabatic_flame_temperature_K.toFixed(0) : '—'}
              unit="K"
              color={tempColor(adiabatic_flame_temperature_K ?? 300)}
              sub="complete combustion"
              warn={TadWarn}
            />
            <ScalarCard
              label="Outlet conversion"
              value={outlet_fuel_conversion != null ? pct(outlet_fuel_conversion) : '—'}
              unit=""
              color={conversionColor}
              sub={`mean: ${pct(mean_fuel_conversion)}`}
            />
          </div>

          {/* Species bar chart */}
          <SpeciesBarChart
            outletMF={outlet_mass_fractions}
            speciesNames={species_names}
          />

          {/* Profiles (optional) */}
          {(temperature_K_profile || fuel_conversion_profile) && (
            <section>
              <p style={{ fontSize: 10, fontFamily: 'monospace', color: '#6b7280',
                          textTransform: 'uppercase', letterSpacing: '0.15em',
                          marginBottom: 8 }}>
                Reactor Profiles
              </p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                {temperature_K_profile && x_m && (
                  <ProfilePlot
                    xArr={x_m}
                    yArr={temperature_K_profile}
                    label="Temperature"
                    unit="K"
                    color={tempColor(
                      Math.max(...(temperature_K_profile ?? [1000]))
                    )}
                  />
                )}
                {fuel_conversion_profile && x_m && (
                  <ProfilePlot
                    xArr={x_m}
                    yArr={fuel_conversion_profile}
                    label={`${fuel ?? 'Fuel'} conversion`}
                    unit="–"
                    color={conversionColor}
                    yMin={0}
                    yMax={1}
                  />
                )}
              </div>
            </section>
          )}

          {/* Reference footnote */}
          <div style={{
            fontSize: 9, color: '#374151', fontFamily: 'monospace',
            borderTop: '1px solid #111827', paddingTop: 6,
          }}>
            Refs: Westbrook &amp; Dryer (1981) PECS 7:23-86 · Williams (1985) Combustion Theory ·
            Law (2006) Combustion Physics · JANAF/NIST (Chase 1998)
            &nbsp;|&nbsp; Design-exploration only — not OpenFOAM-validated
          </div>
        </>
      )}
    </div>
  )
}
