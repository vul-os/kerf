// WiringViewWrapper.jsx
// Wraps WiringView for the panel registry.
// WiringView takes: source (= raw YAML string from file content), projectId, fileId.
// The registry passes content as the raw file text (YAML, not JSON for .wiring files).
import Panel from '../../../components/WiringView.jsx'

export default function WiringViewWrapper({ content, projectId, fileId }) {
  return <Panel source={content || ''} projectId={projectId} fileId={fileId} />
}
