// BIMPhaseWrapper.jsx
// Wraps BIMPhasePanel for the panel registry.
// content JSON shape: { elementPhases: [{element_id, primary_phase, demolish_phase?, notes?},...] }
import Panel from '../../../components/BIMPhasePanel.jsx'

const DEFAULTS = {
  elementPhases: undefined, // undefined → panel uses internal state
}

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function BIMPhaseWrapper({ content }) {
  const parsed = parseContent(content)
  const props = { ...DEFAULTS }
  if (Array.isArray(parsed.elementPhases)) props.elementPhases = parsed.elementPhases
  return <Panel {...props} />
}
