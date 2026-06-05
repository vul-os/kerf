// Hourly8760Wrapper.jsx
import Panel from '../../../components/energy/Hourly8760Panel.jsx'

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function Hourly8760Wrapper({ content, projectId }) {
  const parsed = parseContent(content)
  const pid = parsed.projectId ?? projectId
  return <Panel projectId={pid} />
}
