// CfdResultsWrapper.jsx
// CfdResultsPanel is a pure visualiser; content JSON is parsed and spread over defaults.
import Panel from '../../../components/CfdResultsPanel.jsx'
import type { Props as CfdResultsPanelProps } from '../../../components/CfdResultsPanel.jsx'

export interface Props {
  content?: string
}

const DEFAULTS: CfdResultsPanelProps = {
  fieldStats: null,
  residuals: null,
  probes: null,
  yplus: null,
  n_cells: null,
  time_value: null,
  turbulenceModel: null,
  converged: false,
}

function parseContent(content: string | undefined): CfdResultsPanelProps {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function CfdResultsWrapper({ content }: Props) {
  const props = { ...DEFAULTS, ...parseContent(content) }
  return <Panel {...props} />
}
