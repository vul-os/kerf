// CfdResultsWrapper.jsx
// CfdResultsPanel is a pure visualiser; content JSON is parsed and spread over defaults.
import Panel from '../../../components/CfdResultsPanel.jsx'

const DEFAULTS = {
  fieldStats: null,
  residuals: null,
  probes: null,
  yplus: null,
  n_cells: null,
  time_value: null,
  turbulenceModel: null,
  converged: false,
}

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function CfdResultsWrapper({ content }) {
  const props = { ...DEFAULTS, ...parseContent(content) }
  return <Panel {...props} />
}
