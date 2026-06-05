// SolarPVWrapper.jsx
// SolarPVPanel is a pure visualiser; content JSON is parsed and spread over defaults.
import Panel from '../../../components/SolarPVPanel.jsx'

const DEFAULTS = {
  ivData: null,
  title: 'PV I-V / P-V Curve',
  showPV: true,
}

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function SolarPVWrapper({ content }) {
  const props = { ...DEFAULTS, ...parseContent(content) }
  return <Panel {...props} />
}
