// AshbyChartWrapper.jsx
// AshbyChartPanel is a pure visualiser; content JSON is parsed and spread over defaults.
import Panel from '../../../components/AshbyChartPanel.jsx'
import type { Props as AshbyChartPanelProps } from '../../../components/AshbyChartPanel.jsx'

export interface Props {
  content?: string
}

const DEFAULTS: AshbyChartPanelProps = {
  points: [],
  pareto: [],
  xLabel: 'Property X',
  yLabel: 'Property Y',
  title: 'Ashby Material Chart',
  indexLines: [],
}

function parseContent(content: string | undefined): AshbyChartPanelProps {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function AshbyChartWrapper({ content }: Props) {
  const props = { ...DEFAULTS, ...parseContent(content) }
  return <Panel {...props} />
}
