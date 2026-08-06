// BIMPhaseWrapper.jsx
// Wraps BIMPhasePanel for the panel registry.
// content JSON shape: { elementPhases: [{element_id, primary_phase, demolish_phase?, notes?},...] }
import Panel from '../../../components/BIMPhasePanel.jsx'

export interface ElementPhase {
  element_id: string
  primary_phase: string
  demolish_phase?: string | null
  notes?: string
}

interface BIMPhaseContent {
  elementPhases?: ElementPhase[]
}

export interface Props {
  content?: string
}

function parseContent(content: string | undefined): BIMPhaseContent {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function BIMPhaseWrapper({ content }: Props) {
  const parsed = parseContent(content)
  const elementPhases = Array.isArray(parsed.elementPhases) ? parsed.elementPhases : undefined
  // BIMPhasePanel.jsx destructures onPhasesChange/onFilterResult without
  // defaults; passed explicitly as undefined to satisfy its inferred shape
  // (guarded internally with `if (onPhasesChange)` — pre-existing behavior).
  return <Panel elementPhases={elementPhases} onPhasesChange={undefined} onFilterResult={undefined} />
}
