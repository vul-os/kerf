// ThermalNetworkWrapper.jsx
// ThermalNetworkViewer is a pure visualiser; content JSON supplies the network object.
import Panel, { type ThermalNetworkData } from '../../../components/ThermalNetworkViewer.jsx'

const DEFAULT_NETWORK: ThermalNetworkData = { nodes: [], links: [] }

function parseContent(content?: string): { network?: ThermalNetworkData } {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export interface Props {
  content?: string
}

export default function ThermalNetworkWrapper({ content }: Props) {
  const parsed = parseContent(content)
  const network = parsed.network ?? DEFAULT_NETWORK
  return <Panel network={network} />
}
