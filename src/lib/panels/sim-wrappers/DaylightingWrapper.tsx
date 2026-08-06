// DaylightingWrapper.jsx
import Panel from '../../../components/optics/DaylightingPanel.jsx'

export interface Props {
  content?: string
  projectId?: string
}

interface DaylightingContent {
  projectId?: string
}

function parseContent(content: string | undefined): DaylightingContent {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function DaylightingWrapper({ content, projectId }: Props) {
  const parsed = parseContent(content)
  const pid = parsed.projectId ?? projectId
  return <Panel projectId={pid as string} />
}
