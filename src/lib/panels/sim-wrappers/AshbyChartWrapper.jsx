// AshbyChartWrapper.jsx
// AshbyChartPanel is a pure visualiser; content JSON is parsed and spread over defaults.
import Panel from '../../../components/AshbyChartPanel.jsx'

const DEFAULTS = {
  points: [],
  pareto: [],
  xLabel: 'Property X',
  yLabel: 'Property Y',
  title: 'Ashby Material Chart',
  indexLines: [],
}

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function AshbyChartWrapper({ content }) {
  const props = { ...DEFAULTS, ...parseContent(content) }
  return <Panel {...props} />
}
