// SolarPVWrapper.jsx
// SolarPVPanel is a pure visualiser; content JSON is parsed and spread over defaults.
import Panel, { type SolarPVPanelProps } from '../../../components/SolarPVPanel.jsx'

const DEFAULTS: SolarPVPanelProps = {
  ivData: null,
  title: 'PV I-V / P-V Curve',
  showPV: true,
}

function parseContent(content?: string): Partial<SolarPVPanelProps> {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export interface Props {
  content?: string
}

export default function SolarPVWrapper({ content }: Props) {
  const props = { ...DEFAULTS, ...parseContent(content) }
  return <Panel {...props} />
}
