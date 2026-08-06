// ThermoCycleWrapper.jsx
import Panel from '../../../components/energy/ThermoCyclePanel.jsx'

interface ParsedContent {
  projectId?: string
}

function parseContent(content?: string): ParsedContent {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export interface Props {
  content?: string
  projectId?: string
}

export default function ThermoCycleWrapper({ content, projectId }: Props) {
  const parsed = parseContent(content)
  const pid = parsed.projectId ?? projectId
  return <Panel projectId={pid} />
}
