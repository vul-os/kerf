// ControlsWrapper.jsx
// ControlsPanel is a pure visualiser; content JSON is parsed and spread over defaults.
import Panel from '../../../components/ControlsPanel.jsx'

const DEFAULTS = {
  bode: null,
  nyquist: null,
  step: null,
}

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function ControlsWrapper({ content }) {
  const props = { ...DEFAULTS, ...parseContent(content) }
  return <Panel {...props} />
}
