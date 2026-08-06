// AcousticsWrapper.jsx
// AcousticsResultPanel is standalone (manages its own form state; no external props).
import Panel from '../../../components/acoustics/AcousticsResultPanel.jsx'

export interface Props {
  content?: string
}

export default function AcousticsWrapper(_props: Props) {
  return <Panel />
}
