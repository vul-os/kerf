// ComplianceReportWrapper.jsx
// Standard panel wrapper for ComplianceReportPanel.
// content: JSON string from energy_ashrae901_appendixg_report tool output.
import Panel from '../../../components/energy/ComplianceReportPanel.jsx'

function parseContent(content) {
  if (!content || typeof content !== 'string') return null
  try { return JSON.parse(content) } catch { return null }
}

export default function ComplianceReportWrapper({ content }) {
  const report = parseContent(content)
  return <Panel report={report} />
}
