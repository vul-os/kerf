// CfdViewportWrapper.jsx
// Wraps CfdViewport for the panel registry.
// content JSON shape mirrors CfdViewport props:
//   { vectorField?, pressureField?, showStreamlines?, showArrows?, showPressure?,
//     streamlineCount?, arrowGridStep?, pressureAlpha?, seeds?, width?, height? }
import Panel from '../../../components/CfdViewport.jsx'
import type { CfdViewportProps } from '../../../components/CfdViewport.jsx'

const DEFAULTS: CfdViewportProps = {
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

export interface Props {
  content?: string
}

function parseContent(content: string | undefined): Partial<CfdViewportProps> {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function CfdViewportWrapper({ content }: Props) {
  const props = { ...DEFAULTS, ...parseContent(content) }
  return <Panel {...props} />
}
