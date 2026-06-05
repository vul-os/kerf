// SimulationViewWrapper.jsx
// Wraps SimulationView for the panel registry.
// SimulationView already accepts a `content` string prop natively;
// this wrapper just passes file.name as fileName.
import Panel from '../../../components/SimulationView.jsx'

export default function SimulationViewWrapper({ content, file }) {
  const fileName = file && typeof file.name === 'string' ? file.name : undefined
  return <Panel content={content} fileName={fileName} />
}
