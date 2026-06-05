// LightingSimWrapper.jsx
// LightingSimPanel uses onCallTool for backend calls; the wrapper passes
// undefined (panel shows its UI regardless; backend calls simply no-op).
import Panel from '../../../components/optics/LightingSimPanel.jsx'

export default function LightingSimWrapper() {
  return <Panel onCallTool={undefined} />
}
