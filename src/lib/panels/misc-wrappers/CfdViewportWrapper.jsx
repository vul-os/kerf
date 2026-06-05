// CfdViewportWrapper.jsx
// Wraps CfdViewport for the panel registry.
// content JSON shape mirrors CfdViewport props:
//   { vectorField?, pressureField?, showStreamlines?, showArrows?, showPressure?,
//     streamlineCount?, arrowGridStep?, pressureAlpha?, seeds?, width?, height? }
import Panel from '../../../components/CfdViewport.jsx'

const DEFAULTS = {
  vectorField: null,
  pressureField: null,
  showStreamlines: true,
  showArrows: true,
  showPressure: true,
  streamlineCount: 20,
  arrowGridStep: 4,
  pressureAlpha: 0.45,
  seeds: null,
  width: 520,
  height: 340,
}

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function CfdViewportWrapper({ content }) {
  const props = { ...DEFAULTS, ...parseContent(content) }
  return <Panel {...props} />
}
