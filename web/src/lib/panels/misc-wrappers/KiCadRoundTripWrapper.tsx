// KiCadRoundTripWrapper.jsx
// Wraps KiCadRoundTripPanel for the panel registry.
// content JSON shape: { circuitJson?: Array }
import Panel from '../../../components/KiCadRoundTripPanel.jsx'
import type { KiCadImportResult } from '../../../components/KiCadRoundTripPanel.jsx'
import type { CircuitJson } from '../../../types'

interface KiCadRoundTripContent {
  circuitJson?: unknown
}

export interface Props {
  content?: string
  onCallTool?: (result: KiCadImportResult) => void
}

function parseContent(content: string | undefined): KiCadRoundTripContent {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function KiCadRoundTripWrapper({ content, onCallTool }: Props) {
  const parsed = parseContent(content)
  const circuitJson: CircuitJson = Array.isArray(parsed.circuitJson) ? parsed.circuitJson : []
  return <Panel circuitJson={circuitJson} onImportResult={onCallTool} />
}
