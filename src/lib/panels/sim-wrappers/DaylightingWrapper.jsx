// DaylightingWrapper.jsx
import Panel from '../../../components/optics/DaylightingPanel.jsx'

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function DaylightingWrapper({ content, projectId }) {
  const parsed = parseContent(content)
  const pid = parsed.projectId ?? projectId
  return <Panel projectId={pid} />
}
