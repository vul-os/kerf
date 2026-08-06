// SolarPVWrapper.jsx
// SolarPVPanel is a pure visualiser; content JSON is parsed and spread over defaults.
import Panel from '../../../components/SolarPVPanel.jsx'

interface SolarPVProps {
  ivData: unknown
  title: string
  showPV: boolean
}

const DEFAULTS: SolarPVProps = {
  ivData: null,
  title: 'PV I-V / P-V Curve',
  showPV: true,
}

function parseContent(content?: string): Partial<SolarPVProps> {
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
