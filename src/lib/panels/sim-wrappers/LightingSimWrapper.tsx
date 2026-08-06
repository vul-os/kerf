// LightingSimWrapper.jsx
// LightingSimPanel uses onCallTool for backend calls; the wrapper passes
// undefined (panel shows its UI regardless; backend calls simply no-op).
import Panel from '../../../components/optics/LightingSimPanel.jsx'
import type { Props as LightingSimPanelProps } from '../../../components/optics/LightingSimPanel.jsx'

export interface Props {
  content?: string
}

// NOTE: LightingSimPanel.Props.onCallTool is typed as required and is called
// directly with no null-check (src/components/optics/LightingSimPanel.tsx:166),
// so triggering a run here will throw. Pre-existing bug from before this
// migration — reported, not fixed.
export default function LightingSimWrapper(_props: Props) {
  return <Panel onCallTool={undefined as unknown as LightingSimPanelProps['onCallTool']} />
}
