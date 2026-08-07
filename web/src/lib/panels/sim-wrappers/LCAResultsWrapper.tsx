// LCAResultsWrapper.jsx
// LCAResultsPanel is a pure visualiser; content JSON is parsed and spread over defaults.
import Panel from '../../../components/LCAResultsPanel.jsx'

export interface Props {
  content?: string
}

// LCAResultsPanel.jsx is not yet migrated, so there's no Props type to import;
// this mirrors the fields it destructures from its own props.
interface LCAResultsContent {
  result: unknown
  lifecycle: unknown
  multi: unknown
  uncertainty: unknown
}

const DEFAULTS: LCAResultsContent = {
  result: null,
  lifecycle: undefined,
  multi: undefined,
  uncertainty: undefined,
}

function parseContent(content: string | undefined): Partial<LCAResultsContent> {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function LCAResultsWrapper({ content }: Props) {
  const props = { ...DEFAULTS, ...parseContent(content) }
  return <Panel {...props} />
}
