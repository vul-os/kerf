// BuildingEnergyExportWrapper.jsx
// Thin adapter: accepts { file, content, projectId, fileId } from Editor;
// JSON.parses content and merges over defaults before forwarding to panel.
import Panel from '../../../components/energy/BuildingEnergyExportPanel.jsx'

export interface Props {
  content?: string
  projectId?: string
}

interface BuildingEnergyExportContent {
  projectId?: string
}

function parseContent(content: string | undefined): BuildingEnergyExportContent {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function BuildingEnergyExportWrapper({ content, projectId }: Props) {
  const parsed = parseContent(content)
  const pid = parsed.projectId ?? projectId
  return <Panel projectId={pid as string} />
}
