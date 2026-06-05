// LCAResultsWrapper.jsx
// LCAResultsPanel is a pure visualiser; content JSON is parsed and spread over defaults.
import Panel from '../../../components/LCAResultsPanel.jsx'

const DEFAULTS = {
  result: null,
  lifecycle: undefined,
  multi: undefined,
  uncertainty: undefined,
}

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function LCAResultsWrapper({ content }) {
  const props = { ...DEFAULTS, ...parseContent(content) }
  return <Panel {...props} />
}
