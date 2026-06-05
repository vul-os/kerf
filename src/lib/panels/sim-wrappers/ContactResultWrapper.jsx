// ContactResultWrapper.jsx
// Thin wrapper for the FEM contact result panel.
// Parses JSON content from the file store and spreads parsed keys over safe
// defaults before forwarding to the inline ContactResultPanel below.
//
// Expected content JSON shape (from fem_penalty_contact or
// fem_augmented_lagrangian_contact tool output):
// {
//   method: 'penalty' | 'auglag',
//   contact_status: ['open' | 'stick' | 'slip', ...],   // per node
//   normal_forces_n: [[fx, fy], ...],                    // per node
//   tangential_forces_n: [[fx, fy], ...],                // per node (friction)
//   gaps_m: [gap, ...],                                  // per node (signed gap [m])
//   n_open: number,
//   n_stick: number,
//   n_slip: number,
//   n_active_contacts: number,
//   friction_coefficient: number,
//   penalty_penetration_m: [p, ...],    // auglag only
//   auglag_penetration_m: [p, ...],     // auglag only
//   iterations: number,                 // auglag only
//   converged: boolean,                 // auglag only
//   notes: string,
// }

const DEFAULTS = {
  method: 'penalty',
  contact_status: [],
  normal_forces_n: [],
  tangential_forces_n: [],
  gaps_m: [],
  n_open: 0,
  n_stick: 0,
  n_slip: 0,
  n_active_contacts: 0,
  friction_coefficient: 0,
  penalty_penetration_m: null,
  auglag_penetration_m: null,
  iterations: null,
  converged: null,
  notes: null,
}

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

// Status badge colors
const STATUS_COLORS = {
  open: '#64748b',   // slate
  stick: '#22c55e',  // green
  slip: '#f59e0b',   // amber
}

function ContactResultPanel({
  method,
  contact_status,
  normal_forces_n,
  tangential_forces_n,
  gaps_m,
  n_open,
  n_stick,
  n_slip,
  n_active_contacts,
  friction_coefficient,
  penalty_penetration_m,
  auglag_penetration_m,
  iterations,
  converged,
  notes,
}) {
  const total = contact_status.length

  const maxPen = auglag_penetration_m
    ? Math.max(...auglag_penetration_m)
    : gaps_m.length > 0 ? Math.max(...gaps_m.map(g => Math.max(0, -g))) : 0

  const maxPenPenalty = penalty_penetration_m
    ? Math.max(...penalty_penetration_m)
    : null

  return (
    <div style={{ fontFamily: 'system-ui, sans-serif', padding: '16px', color: '#1e293b' }}>
      <h3 style={{ margin: '0 0 12px', fontSize: '15px', fontWeight: 600 }}>
        FEM Contact Results
        <span style={{
          marginLeft: '8px', fontSize: '11px', fontWeight: 400,
          background: method === 'auglag' ? '#dbeafe' : '#f1f5f9',
          color: method === 'auglag' ? '#1d4ed8' : '#475569',
          borderRadius: '4px', padding: '2px 6px',
        }}>
          {method === 'auglag' ? 'Augmented-Lagrange' : 'Penalty'}
        </span>
      </h3>

      {/* Summary badges */}
      <div style={{ display: 'flex', gap: '8px', marginBottom: '16px', flexWrap: 'wrap' }}>
        {[
          { label: 'Open', count: n_open, color: STATUS_COLORS.open },
          { label: 'Stick', count: n_stick, color: STATUS_COLORS.stick },
          { label: 'Slip', count: n_slip, color: STATUS_COLORS.slip },
        ].map(({ label, count, color }) => (
          <div key={label} style={{
            display: 'flex', alignItems: 'center', gap: '6px',
            background: '#f8fafc', border: '1px solid #e2e8f0',
            borderRadius: '6px', padding: '6px 10px',
          }}>
            <span style={{
              width: '10px', height: '10px', borderRadius: '50%',
              background: color, display: 'inline-block',
            }} />
            <span style={{ fontSize: '13px', fontWeight: 600 }}>{count}</span>
            <span style={{ fontSize: '12px', color: '#64748b' }}>{label}</span>
          </div>
        ))}
        {total > 0 && (
          <div style={{
            fontSize: '12px', color: '#94a3b8', alignSelf: 'center', marginLeft: '4px',
          }}>
            / {total} nodes
          </div>
        )}
      </div>

      {/* Friction coefficient */}
      {friction_coefficient > 0 && (
        <div style={{ marginBottom: '12px', fontSize: '13px', color: '#475569' }}>
          Friction coefficient <strong>μ = {friction_coefficient.toFixed(3)}</strong>
        </div>
      )}

      {/* Penetration comparison (auglag only) */}
      {auglag_penetration_m && penalty_penetration_m && (
        <div style={{
          background: '#f0fdf4', border: '1px solid #bbf7d0',
          borderRadius: '8px', padding: '10px 12px', marginBottom: '12px',
        }}>
          <div style={{ fontSize: '12px', fontWeight: 600, color: '#15803d', marginBottom: '6px' }}>
            Penetration Comparison
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
            <div>
              <div style={{ fontSize: '11px', color: '#64748b' }}>Pure Penalty</div>
              <div style={{ fontSize: '14px', fontWeight: 600, color: '#dc2626' }}>
                {(maxPenPenalty * 1e6).toFixed(2)} μm
              </div>
            </div>
            <div>
              <div style={{ fontSize: '11px', color: '#64748b' }}>Augmented-Lagrange</div>
              <div style={{ fontSize: '14px', fontWeight: 600, color: '#15803d' }}>
                {(maxPen * 1e6).toFixed(2)} μm
              </div>
            </div>
          </div>
          {maxPenPenalty > 0 && maxPen < maxPenPenalty && (
            <div style={{ fontSize: '11px', color: '#15803d', marginTop: '4px' }}>
              {((1 - maxPen / maxPenPenalty) * 100).toFixed(1)}% reduction in penetration
            </div>
          )}
        </div>
      )}

      {/* Auglag convergence info */}
      {iterations != null && (
        <div style={{
          fontSize: '12px', color: '#475569', marginBottom: '12px',
          display: 'flex', gap: '16px',
        }}>
          <span>
            Uzawa iterations: <strong>{iterations}</strong>
          </span>
          <span style={{ color: converged ? '#15803d' : '#dc2626' }}>
            {converged ? 'Converged' : 'Not converged'}
          </span>
        </div>
      )}

      {/* Per-node table (first 20 nodes max) */}
      {contact_status.length > 0 && (
        <div style={{ marginBottom: '12px' }}>
          <div style={{ fontSize: '12px', fontWeight: 600, color: '#475569', marginBottom: '6px' }}>
            Node Status {contact_status.length > 20 ? `(first 20 of ${contact_status.length})` : ''}
          </div>
          <table style={{
            width: '100%', borderCollapse: 'collapse', fontSize: '12px',
          }}>
            <thead>
              <tr style={{ background: '#f1f5f9' }}>
                <th style={{ padding: '4px 6px', textAlign: 'left', fontWeight: 600 }}>Node</th>
                <th style={{ padding: '4px 6px', textAlign: 'left', fontWeight: 600 }}>Status</th>
                <th style={{ padding: '4px 6px', textAlign: 'right', fontWeight: 600 }}>Gap (μm)</th>
                <th style={{ padding: '4px 6px', textAlign: 'right', fontWeight: 600 }}>|Fn| (N)</th>
                <th style={{ padding: '4px 6px', textAlign: 'right', fontWeight: 600 }}>|Ft| (N)</th>
              </tr>
            </thead>
            <tbody>
              {contact_status.slice(0, 20).map((status, i) => {
                const gap = gaps_m[i] != null ? gaps_m[i] : null
                const fn = normal_forces_n[i]
                  ? Math.sqrt(normal_forces_n[i].reduce((s, v) => s + v * v, 0))
                  : 0
                const ft = tangential_forces_n[i]
                  ? Math.sqrt(tangential_forces_n[i].reduce((s, v) => s + v * v, 0))
                  : 0
                return (
                  <tr key={i} style={{ borderBottom: '1px solid #e2e8f0' }}>
                    <td style={{ padding: '4px 6px', color: '#64748b' }}>{i}</td>
                    <td style={{ padding: '4px 6px' }}>
                      <span style={{
                        background: STATUS_COLORS[status] + '22',
                        color: STATUS_COLORS[status],
                        borderRadius: '4px', padding: '1px 5px',
                        fontWeight: 600, fontSize: '11px',
                      }}>
                        {status}
                      </span>
                    </td>
                    <td style={{ padding: '4px 6px', textAlign: 'right', fontFamily: 'monospace' }}>
                      {gap != null ? (gap * 1e6).toFixed(2) : '—'}
                    </td>
                    <td style={{ padding: '4px 6px', textAlign: 'right', fontFamily: 'monospace' }}>
                      {fn > 0 ? fn.toExponential(2) : '0'}
                    </td>
                    <td style={{ padding: '4px 6px', textAlign: 'right', fontFamily: 'monospace' }}>
                      {ft > 0 ? ft.toExponential(2) : '0'}
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
          fontSize: '11px', color: '#94a3b8', marginTop: '8px',
          borderTop: '1px solid #e2e8f0', paddingTop: '8px',
        }}>
          {notes}
        </div>
      )}
    </div>
  )
}

export default function ContactResultWrapper({ content }) {
  const props = { ...DEFAULTS, ...parseContent(content) }
  return <ContactResultPanel {...props} />
}
