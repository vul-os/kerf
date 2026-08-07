// Hourly8760Wrapper.jsx
import Panel from '../../../components/energy/Hourly8760Panel.jsx'

export interface Props {
  content?: string
  projectId?: string
}

interface Hourly8760Content {
  projectId?: string
}

function parseContent(content: string | undefined): Hourly8760Content {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function Hourly8760Wrapper({ content, projectId }: Props) {
  const parsed = parseContent(content)
  const pid = parsed.projectId ?? projectId
  return <Panel projectId={pid} />
}
