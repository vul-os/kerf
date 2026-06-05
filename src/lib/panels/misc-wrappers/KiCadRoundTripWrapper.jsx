// KiCadRoundTripWrapper.jsx
// Wraps KiCadRoundTripPanel for the panel registry.
// content JSON shape: { circuitJson?: Array }
import Panel from '../../../components/KiCadRoundTripPanel.jsx'

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function KiCadRoundTripWrapper({ content, onCallTool }) {
  const parsed = parseContent(content)
  const circuitJson = Array.isArray(parsed.circuitJson) ? parsed.circuitJson : []
  return <Panel circuitJson={circuitJson} onImportResult={onCallTool} />
}
