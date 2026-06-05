// ThermalNetworkWrapper.jsx
// ThermalNetworkViewer is a pure visualiser; content JSON supplies the network object.
import Panel from '../../../components/ThermalNetworkViewer.jsx'

const DEFAULT_NETWORK = { nodes: [], links: [] }

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function ThermalNetworkWrapper({ content }) {
  const parsed = parseContent(content)
  const network = parsed.network ?? DEFAULT_NETWORK
  return <Panel network={network} />
}
