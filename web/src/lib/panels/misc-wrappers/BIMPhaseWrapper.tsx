// BIMPhaseWrapper.jsx
// Wraps BIMPhasePanel for the panel registry.
// content JSON shape: { elementPhases: [{element_id, primary_phase, demolish_phase?, notes?},...] }
// ElementPhase is the panel's type — a local copy typed primary_phase as bare `string`,
// which is not assignable to the panel's PhaseValue union.
import Panel, { type ElementPhase } from '../../../components/BIMPhasePanel.jsx'

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
