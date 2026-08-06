// SequentialTraceWrapper.jsx
// SequentialTracePanel uses onCallTool for backend calls; the wrapper passes
// undefined (panel shows its UI regardless; backend calls simply no-op).
import Panel from '../../../components/optics/SequentialTracePanel.jsx'

export interface Props {
  content?: string
}

export default function SequentialTraceWrapper(_props: Props) {
  return <Panel onCallTool={undefined} />
}
