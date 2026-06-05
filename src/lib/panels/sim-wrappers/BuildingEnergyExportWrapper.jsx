// BuildingEnergyExportWrapper.jsx
// Thin adapter: accepts { file, content, projectId, fileId } from Editor;
// JSON.parses content and merges over defaults before forwarding to panel.
import Panel from '../../../components/energy/BuildingEnergyExportPanel.jsx'

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function BuildingEnergyExportWrapper({ content, projectId }) {
  const parsed = parseContent(content)
  const pid = parsed.projectId ?? projectId
  return <Panel projectId={pid} />
}
