// RFViewWrapper.jsx
// Wraps RFView for the panel registry.
// content JSON shape: { status?, result?: { smith_chart_svg?, vswr?, frequency_range?,
//   frequency_unit?, return_loss_db?, insertion_loss_db?, stability_factor_k?,
//   max_gain_db?, warnings? }, errors? }
// The rfResult prop shape mirrors what the backend RF study returns.
import { useRef } from 'react'
import Panel from '../../../components/RFView.jsx'

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function RFViewWrapper({ content, fileId, callTool }) {
  const viewRef = useRef(null)
  const rfResult = parseContent(content)
  const handleRunStudy = callTool
    ? () => callTool('rf_run_study', { file_id: fileId })
    : undefined
  return (
    <Panel
      rfResult={Object.keys(rfResult).length > 0 ? rfResult : undefined}
      fileId={fileId}
      onRunStudy={handleRunStudy}
      viewRef={viewRef}
    />
  )
}
