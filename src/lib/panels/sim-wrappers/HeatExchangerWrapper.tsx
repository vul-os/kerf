// HeatExchangerWrapper.jsx
import Panel from '../../../components/energy/HeatExchangerPanel.jsx'

export interface Props {
  content?: string
  projectId?: string
}

interface HeatExchangerContent {
  projectId?: string
}

function parseContent(content: string | undefined): HeatExchangerContent {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function HeatExchangerWrapper({ content, projectId }: Props) {
  const parsed = parseContent(content)
  const pid = parsed.projectId ?? projectId
  return <Panel projectId={pid} />
}
