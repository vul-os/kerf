// EMFieldWrapper.jsx
// Thin wrapper for EMFieldPanel — parses JSON content from the file store
// and spreads parsed keys over safe defaults before forwarding to the panel.
import Panel from '../../../components/EMFieldPanel.jsx'

const DEFAULTS = {
  mode: 'electrostatics',
  ok: null,
  reason: null,
  phi: null,
  E_field: null,
  capacitance: null,
  energy: null,
  Az: null,
  B_field: null,
  inductance: null,
  force: null,
  nodes: null,
  elements: null,
}

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function EMFieldWrapper({ content }) {
  const props = { ...DEFAULTS, ...parseContent(content) }
  return <Panel {...props} />
}
