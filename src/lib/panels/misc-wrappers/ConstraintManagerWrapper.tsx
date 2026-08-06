// ConstraintManagerWrapper.jsx
// Wraps ConstraintManagerPanel for the panel registry.
// content JSON shape: { circuit_json?: {...} }
import Panel from '../../../components/electronics/ConstraintManagerPanel.jsx'
import type { ConstraintManagerPanelProps } from '../../../components/electronics/ConstraintManagerPanel.jsx'

interface ConstraintManagerContent {
  circuit_json?: ConstraintManagerPanelProps['circuitJson']
}

export interface Props {
  content?: string
}

function parseContent(content: string | undefined): ConstraintManagerContent {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function ConstraintManagerWrapper({ content }: Props) {
  const parsed = parseContent(content)
  const circuitJson = parsed.circuit_json && typeof parsed.circuit_json === 'object'
    ? parsed.circuit_json
    : null
  return <Panel circuitJson={circuitJson} />
}
