// ComplianceReportWrapper.jsx
// Standard panel wrapper for ComplianceReportPanel.
// content: JSON string from energy_ashrae901_appendixg_report tool output.
import Panel from '../../../components/energy/ComplianceReportPanel.jsx'
import type { ComplianceReport } from '../../../components/energy/ComplianceReportPanel.jsx'

export interface Props {
  content?: string
}

function parseContent(content: string | undefined): ComplianceReport | null {
  if (!content || typeof content !== 'string') return null
  try { return JSON.parse(content) } catch { return null }
}

export default function ComplianceReportWrapper({ content }: Props) {
  const report = parseContent(content)
  return <Panel report={report} />
}
