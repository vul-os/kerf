// ControlsWrapper.jsx
// ControlsPanel is a pure visualiser; content JSON is parsed and spread over defaults.
import Panel, { type ControlsPanelProps } from '../../../components/ControlsPanel'

export interface Props {
  content?: string
}

type ControlsContent = Pick<ControlsPanelProps, 'bode' | 'nyquist' | 'step'>

const DEFAULTS: ControlsContent = {
  bode: null,
  nyquist: null,
  step: null,
}

function parseContent(content: string | undefined): ControlsContent {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function ControlsWrapper({ content }: Props) {
  const props = { ...DEFAULTS, ...parseContent(content) }
  return <Panel {...props} />
}
