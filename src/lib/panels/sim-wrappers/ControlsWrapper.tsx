// ControlsWrapper.jsx
// ControlsPanel is a pure visualiser; content JSON is parsed and spread over defaults.
import Panel from '../../../components/ControlsPanel.jsx'

export interface Props {
  content?: string
}

// ControlsPanel.jsx is not yet migrated, so there's no Props type to import;
// this mirrors the fields it destructures from its own props.
interface ControlsContent {
  bode?: unknown
  nyquist?: unknown
  step?: unknown
}

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
