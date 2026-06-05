/**
 * CfdPostProcessPanel.jsx — CFD post-processing panel.
 *
 * Shows results from cfd_postprocess_filter + cfd_export_vtk tools.
 *
 * Sections:
 *  1. Filter picker + parameters (slice / contour / streamline / integral / probe / derived)
 *  2. Filter result preview (cell count, stats, streamline paths, probe values)
 *  3. VTU export card with download info + "open in ParaView" instruction
 *
 * Props
 * -----
 * filter       {string}  active filter type
 * filterResult {object}  JSON result from cfd_postprocess_filter
 * exportPath   {string}  path to exported .vtk/.vtu file
 * exportMeta   {object}  {n_points, n_cells, format, file_size_bytes}
 * fieldStats   {object}  optional field statistics
 * n_cells      {number}  total mesh cell count
 */

// ── Utilities ────────────────────────────────────────────────────────────────

function fmt(v, digits = 4) {
  if (v == null) return '—'
  if (typeof v !== 'number') return String(v)
  if (Math.abs(v) === 0) return '0'
  if (Math.abs(v) < 0.001 || Math.abs(v) >= 10000) return v.toExponential(2)
  return v.toPrecision(digits)
}

function fmtBytes(n) {
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}

// ── Colour helpers ────────────────────────────────────────────────────────────

const FILTER_COLORS = {
  slice:      '#3b82f6',
  contour:    '#8b5cf6',
  streamline: '#10b981',
  integral:   '#f59e0b',
  probe:      '#f87171',
  derived:    '#06b6d4',
}

const FILTER_DESCRIPTIONS = {
  slice:      'Cut-plane extraction — field values near an arbitrary plane',
  contour:    'Iso-surface — cells straddling a scalar value',
  streamline: 'RK4 streamline integration through velocity field',
  integral:   'Volume average / integral / min / max / RMS',
  probe:      'Field values at arbitrary probe points (nearest-cell)',
  derived:    'Vorticity · Q-criterion · grad(p) · Cp · divergence · strain rate',
}

// ── Filter picker ─────────────────────────────────────────────────────────────

const FILTERS = ['slice', 'contour', 'streamline', 'integral', 'probe', 'derived']

function FilterPicker({ active }) {
  return (
    <section>
      <p style={{ fontSize: 10, fontFamily: 'monospace', color: '#6b7280',
                  textTransform: 'uppercase', letterSpacing: '0.15em', marginBottom: 8 }}>
        Post-Processing Filters
      </p>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {FILTERS.map(f => {
          const isActive = f === active
          const color = FILTER_COLORS[f] || '#6b7280'
          return (
            <div key={f} style={{
              flex: '1 1 140px',
              borderRadius: 6,
              border: `1px solid ${isActive ? color : '#1f2937'}`,
              background: isActive ? `${color}18` : '#0d1117',
              padding: '7px 10px',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
                <span style={{
                  display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
                  background: isActive ? color : '#374151',
                }} />
                <span style={{
                  fontSize: 11, fontFamily: 'monospace',
                  color: isActive ? color : '#9ca3af',
                  fontWeight: isActive ? 600 : 400,
                  textTransform: 'uppercase', letterSpacing: '0.05em',
                }}>
                  {f}
                </span>
              </div>
              <div style={{ fontSize: 9, color: '#6b7280', fontFamily: 'monospace',
                            lineHeight: 1.4 }}>
                {FILTER_DESCRIPTIONS[f]}
              </div>
            </div>
          )
        })}
      </div>
      {active && (
        <p style={{ fontSize: 10, fontFamily: 'monospace', color: '#6b7280',
                    marginTop: 8, fontStyle: 'italic' }}>
          Use{' '}
          <code style={{ color: '#a5b4fc', background: '#1e1b4b',
                         padding: '0 4px', borderRadius: 3 }}>
            cfd_postprocess_filter
          </code>
          {' '}tool with filter=&quot;{active}&quot; to run.
        </p>
      )}
    </section>
  )
}

// ── Filter result viewer ──────────────────────────────────────────────────────

function StatRow({ label, value }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between',
                  padding: '3px 0', borderBottom: '1px solid #111827' }}>
      <span style={{ fontSize: 11, color: '#9ca3af', fontFamily: 'monospace' }}>{label}</span>
      <span style={{ fontSize: 11, color: '#e5e7eb', fontFamily: 'monospace' }}>{value}</span>
    </div>
  )
}

function StatsBlock({ stats, title }) {
  if (!stats || Object.keys(stats).length === 0) return null
  return (
    <div style={{ marginTop: 8 }}>
      {title && (
        <p style={{ fontSize: 9, color: '#6b7280', fontFamily: 'monospace',
                    textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 4 }}>
          {title}
        </p>
      )}
      {['min', 'max', 'mean', 'rms'].map(k => stats[k] != null && (
        <StatRow key={k} label={k} value={fmt(stats[k])} />
      ))}
      {stats.n != null && <StatRow label="n cells" value={stats.n?.toLocaleString()} />}
    </div>
  )
}

function SliceResult({ result }) {
  if (!result) return null
  return (
    <div>
      <StatRow label="Cells on plane" value={result.n_cells_on_plane?.toLocaleString() ?? '—'} />
      <StatRow label="Plane normal"
               value={(result.plane_normal || []).map(v => v.toFixed(3)).join(', ')} />
      <StatRow label="Tolerance" value={result.tolerance_m != null
               ? `${result.tolerance_m.toExponential(3)} m` : '—'} />
      <StatRow label="Field" value={result.field ?? '—'} />
      <StatsBlock stats={result.field_stats} title="Field statistics on plane" />
    </div>
  )
}

function ContourResult({ result }) {
  if (!result) return null
  return (
    <div>
      <StatRow label="Iso-value" value={fmt(result.iso_value)} />
      <StatRow label="Cells on iso-surface" value={result.n_cells?.toLocaleString() ?? '—'} />
      <StatRow label="Field" value={result.field ?? '—'} />
      <StatsBlock stats={result.field_stats} title="Values near iso-surface" />
    </div>
  )
}

function StreamlineResult({ result }) {
  if (!result) return null
  const lines = result.streamlines || []
  return (
    <div>
      <StatRow label="Streamlines" value={result.n_streamlines ?? '—'} />
      <StatRow label="Direction" value={result.direction ?? '—'} />
      <StatRow label="Step size" value={result.step_size_m != null
               ? `${result.step_size_m.toExponential(3)} m` : '—'} />
      <StatRow label="Max steps" value={result.max_steps ?? '—'} />
      {lines.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <p style={{ fontSize: 9, color: '#6b7280', fontFamily: 'monospace',
                      textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 4 }}>
            Streamline lengths
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {lines.slice(0, 8).map((sl, i) => (
              <span key={i} style={{
                fontSize: 10, fontFamily: 'monospace',
                color: '#10b981', background: '#064e3b',
                border: '1px solid #065f46', borderRadius: 3,
                padding: '1px 6px',
              }}>
                #{i}: {sl.n_points} pts
              </span>
            ))}
            {lines.length > 8 && (
              <span style={{ fontSize: 10, color: '#6b7280', fontFamily: 'monospace' }}>
                +{lines.length - 8} more
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function IntegralResult({ result }) {
  if (!result) return null
  return (
    <div>
      <StatRow label="Operation" value={result.operation ?? '—'} />
      <StatRow label="Field" value={result.field ?? '—'} />
      <StatRow label="Result" value={fmt(result.result)} />
      <StatRow label="Total volume" value={result.total_volume_m3 != null
               ? `${result.total_volume_m3.toExponential(3)} m³` : '—'} />
      <StatRow label="N cells" value={result.n_cells?.toLocaleString() ?? '—'} />
    </div>
  )
}

function ProbeResult({ result }) {
  if (!result) return null
  const probes = result.probes || []
  const dispFields = result.fields?.slice(0, 3) || ['p']

  return (
    <div>
      <StatRow label="N probes" value={result.n_probes ?? '—'} />
      {probes.length > 0 && (
        <div style={{ marginTop: 8, overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
            <thead>
              <tr>
                {['#', 'x', 'y', 'z', ...dispFields, 'dist (m)'].map(h => (
                  <th key={h} style={{
                    textAlign: 'right', padding: '3px 6px',
                    color: '#9ca3af', fontFamily: 'monospace', fontWeight: 500,
                    borderBottom: '1px solid #1f2937',
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {probes.slice(0, 10).map((p, i) => (
                <tr key={i} style={{ borderBottom: '1px solid #111827' }}>
                  <td style={{ padding: '2px 6px', color: '#6b7280',
                               fontFamily: 'monospace', textAlign: 'right' }}>{i}</td>
                  {['x', 'y', 'z'].map(c => (
                    <td key={c} style={{ padding: '2px 6px', color: '#9ca3af',
                                        fontFamily: 'monospace', textAlign: 'right' }}>
                      {fmt(p[c], 3)}
                    </td>
                  ))}
                  {dispFields.map(f => {
                    const v = p[`${f}_mag`] ?? p[f]
                    return (
                      <td key={f} style={{ padding: '2px 6px', color: '#d1d5db',
                                          fontFamily: 'monospace', textAlign: 'right' }}>
                        {Array.isArray(v)
                          ? `[${v.map(x => x.toFixed(3)).join(', ')}]`
                          : fmt(v)}
                      </td>
                    )
                  })}
                  <td style={{ padding: '2px 6px', color: '#6b7280',
                               fontFamily: 'monospace', textAlign: 'right' }}>
                    {fmt(p.distance_m, 3)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {probes.length > 10 && (
            <p style={{ fontSize: 9, color: '#6b7280', fontFamily: 'monospace',
                        marginTop: 4 }}>
              Showing 10 of {probes.length} probes.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function DerivedResult({ result }) {
  if (!result) return null
  return (
    <div>
      <StatRow label="Quantity" value={result.quantity ?? '—'} />
      <StatRow label="N cells" value={result.n_cells?.toLocaleString() ?? '—'} />
      {result.note && (
        <p style={{ fontSize: 9, color: '#6b7280', fontFamily: 'monospace',
                    marginTop: 6, lineHeight: 1.4 }}>
          {result.note}
        </p>
      )}
      <StatsBlock stats={result.stats} title="Value statistics" />
    </div>
  )
}

function FilterResultPanel({ filter, result }) {
  if (!result) return null

  const color = FILTER_COLORS[filter] || '#6b7280'
  const hasError = 'error' in result

  return (
    <section style={{
      borderRadius: 6, border: `1px solid ${hasError ? '#7f1d1d' : '#1f2937'}`,
      background: hasError ? '#1c0505' : '#0d1117',
      padding: 10,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <p style={{ fontSize: 10, fontFamily: 'monospace', color: '#6b7280',
                    textTransform: 'uppercase', letterSpacing: '0.15em', margin: 0 }}>
          Filter Result
        </p>
        <span style={{
          fontSize: 10, fontFamily: 'monospace', padding: '1px 6px',
          borderRadius: 4, border: `1px solid ${color}40`,
          background: `${color}15`, color,
        }}>
          {filter}
        </span>
        {hasError && (
          <span style={{ fontSize: 10, color: '#f87171', fontFamily: 'monospace' }}>
            Error: {result.error}
          </span>
        )}
      </div>

      {!hasError && filter === 'slice'      && <SliceResult result={result} />}
      {!hasError && filter === 'contour'    && <ContourResult result={result} />}
      {!hasError && filter === 'streamline' && <StreamlineResult result={result} />}
      {!hasError && filter === 'integral'   && <IntegralResult result={result} />}
      {!hasError && filter === 'probe'      && <ProbeResult result={result} />}
      {!hasError && filter === 'derived'    && <DerivedResult result={result} />}
    </section>
  )
}

// ── VTU Export card ───────────────────────────────────────────────────────────

function ExportCard({ exportPath, exportMeta }) {
  if (!exportPath && !exportMeta) return null

  const fmt_label = exportMeta?.format_label ?? exportMeta?.format ?? 'VTK'
  const sizeStr = exportMeta?.file_size_bytes != null
    ? fmtBytes(exportMeta.file_size_bytes)
    : '—'

  return (
    <section style={{
      borderRadius: 6, border: '1px solid #1e3a5f',
      background: '#0c1a2e', padding: 10,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <p style={{ fontSize: 10, fontFamily: 'monospace', color: '#93c5fd',
                    textTransform: 'uppercase', letterSpacing: '0.15em', margin: 0 }}>
          Export for ParaView
        </p>
        <span style={{
          fontSize: 10, fontFamily: 'monospace', padding: '1px 6px', borderRadius: 4,
          background: '#1e3a5f', color: '#93c5fd', border: '1px solid #1e40af',
        }}>
          {fmt_label}
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 8 }}>
        {[
          { label: 'Format', value: fmt_label },
          { label: 'Points', value: exportMeta?.n_points?.toLocaleString() ?? '—' },
          { label: 'Cells',  value: exportMeta?.n_cells?.toLocaleString() ?? '—' },
          { label: 'Size',   value: sizeStr },
          { label: 'Point fields', value: (exportMeta?.point_data_fields || []).join(', ') || '—' },
          { label: 'Cell fields',  value: (exportMeta?.cell_data_fields || []).join(', ') || '—' },
        ].map(({ label, value }) => (
          <div key={label}>
            <div style={{ fontSize: 9, color: '#6b7280', fontFamily: 'monospace' }}>{label}</div>
            <div style={{ fontSize: 11, color: '#e5e7eb', fontFamily: 'monospace',
                          wordBreak: 'break-all' }}>
              {value}
            </div>
          </div>
        ))}
      </div>

      {exportPath && (
        <div style={{ background: '#0a1628', borderRadius: 4, padding: '6px 10px',
                      border: '1px solid #1e3a5f' }}>
          <p style={{ fontSize: 9, color: '#6b7280', fontFamily: 'monospace',
                      marginBottom: 3 }}>
            File path
          </p>
          <code style={{ fontSize: 11, color: '#93c5fd', fontFamily: 'monospace',
                         wordBreak: 'break-all' }}>
            {exportPath}
          </code>
        </div>
      )}

      <div style={{ marginTop: 8, padding: '6px 10px', background: '#0a1628',
                    borderRadius: 4, border: '1px solid #1e3a5f' }}>
        <p style={{ fontSize: 10, color: '#6b7280', fontFamily: 'monospace', marginBottom: 3 }}>
          Open in ParaView
        </p>
        <p style={{ fontSize: 10, color: '#93c5fd', fontFamily: 'monospace', lineHeight: 1.5 }}>
          File &#8250; Open &#8250; select file &#8250; Apply
          <br />
          Then use: Filters &#8250; Common &#8250; Slice / Contour / Stream Tracer / Glyph
        </p>
        <p style={{ fontSize: 9, color: '#4b5563', fontFamily: 'monospace', marginTop: 4 }}>
          Note: filters run server-side in kerf; .vtu export lets you apply ParaView&apos;s
          own native pipeline including volume rendering and advanced glyphs.
        </p>
      </div>
    </section>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function CfdPostProcessPanel({
  filter = null,
  filterResult = null,
  exportPath = null,
  exportMeta = null,
  fieldStats = null,
  n_cells = null,
}) {
  const hasAny = filter || filterResult || exportPath || exportMeta

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 14,
      padding: 12, borderRadius: 8, border: '1px solid #1f2937',
      background: '#030712', color: '#e5e7eb',
    }}>
      {/* Header chips */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {n_cells != null && (
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 4,
            fontSize: 10, fontFamily: 'monospace', color: '#9ca3af',
            background: '#111827', border: '1px solid #1f2937',
            borderRadius: 4, padding: '2px 7px',
          }}>
            <span style={{ color: '#6b7280' }}>Cells:</span>
            {n_cells.toLocaleString()}
          </span>
        )}
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: 4,
          fontSize: 10, fontFamily: 'monospace', color: '#9ca3af',
          background: '#111827', border: '1px solid #1f2937',
          borderRadius: 4, padding: '2px 7px',
        }}>
          <span style={{ color: '#6b7280' }}>Pipeline:</span>
          server-side (NumPy)
        </span>
      </div>

      {!hasAny && (
        <div style={{ textAlign: 'center', color: '#4b5563', fontSize: 13,
                      padding: '24px 0', fontFamily: 'monospace' }}>
          No post-processing results — call cfd_postprocess_filter or cfd_export_vtk
        </div>
      )}

      <FilterPicker active={filter} />

      {filterResult && filter && (
        <FilterResultPanel filter={filter} result={filterResult} />
      )}

      <ExportCard exportPath={exportPath} exportMeta={exportMeta} />
    </div>
  )
}
