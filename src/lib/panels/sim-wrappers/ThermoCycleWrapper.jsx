// ThermoCycleWrapper.jsx
import Panel from '../../../components/energy/ThermoCyclePanel.jsx'

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function ThermoCycleWrapper({ content, projectId }) {
  const parsed = parseContent(content)
  const pid = parsed.projectId ?? projectId
  return <Panel projectId={pid} />
}
