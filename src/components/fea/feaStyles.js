// feaStyles.js — shared style tokens for FEA solve panels.
// Consistent with FEMView.jsx palette.

export const s = {
  root: {
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    fontSize: 13,
    color: '#e5e7eb',
    background: '#111827',
    borderRadius: 8,
    padding: 16,
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    borderBottom: '1px solid #1f2937',
    paddingBottom: 10,
  },
  title: {
    fontWeight: 600,
    fontSize: 14,
    color: '#f3f4f6',
  },
  section: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  sectionTitle: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    fontSize: 11,
    color: '#9ca3af',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  row: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  label: {
    color: '#9ca3af',
    width: 110,
    flexShrink: 0,
    fontSize: 12,
  },
  select: {
    flex: 1,
    background: '#1f2937',
    border: '1px solid #374151',
    borderRadius: 4,
    color: '#e5e7eb',
    padding: '3px 6px',
    fontSize: 12,
    outline: 'none',
  },
  input: {
    flex: 1,
    background: '#1f2937',
    border: '1px solid #374151',
    borderRadius: 4,
    color: '#e5e7eb',
    padding: '3px 6px',
    fontSize: 12,
    outline: 'none',
  },
  button: {
    marginTop: 4,
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    padding: '6px 14px',
    background: '#0e7490',
    border: 'none',
    borderRadius: 5,
    color: '#fff',
    fontSize: 12,
    fontWeight: 600,
    cursor: 'pointer',
  },
  buttonDisabled: {
    opacity: 0.5,
    cursor: 'not-allowed',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
  },
  td: {
    padding: '3px 8px',
    borderBottom: '1px solid #1f2937',
    color: '#d1d5db',
    fontSize: 12,
  },
  mono: {
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    color: '#22d3ee',
    textAlign: 'right',
  },
  errorBox: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 6,
    background: '#1f0707',
    border: '1px solid #7f1d1d',
    borderRadius: 5,
    padding: '6px 10px',
    color: '#fca5a5',
    fontSize: 12,
  },
  infoBox: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    color: '#93c5fd',
    fontSize: 12,
    padding: '4px 0',
  },
  badge: {
    marginLeft: 'auto',
    padding: '1px 7px',
    borderRadius: 9999,
    fontSize: 11,
    fontWeight: 600,
  },
}

export const STATUS_COLORS = {
  queued:  '#f59e0b',
  running: '#22d3ee',
  done:    '#34d399',
  error:   '#f87171',
}

export function badgeStyle(status) {
  const c = STATUS_COLORS[status] || '#6b7280'
  return {
    ...s.badge,
    background: c + '22',
    color: c,
    border: `1px solid ${c}55`,
  }
}
