// ConstraintManagerWrapper.jsx
// Wraps ConstraintManagerPanel for the panel registry.
// content JSON shape: { circuit_json?: {...} }
import Panel from '../../../components/electronics/ConstraintManagerPanel.jsx'

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function ConstraintManagerWrapper({ content }) {
  const parsed = parseContent(content)
  const circuitJson = parsed.circuit_json && typeof parsed.circuit_json === 'object'
    ? parsed.circuit_json
    : null
  return <Panel circuitJson={circuitJson} />
}
