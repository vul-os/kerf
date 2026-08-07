// SimulationViewWrapper.jsx
// Wraps SimulationView for the panel registry.
// SimulationView already accepts a `content` string prop natively;
// this wrapper just passes file.name as fileName.
import Panel from '../../../components/SimulationView.jsx'
import type { ApiFile } from '@/types/api'

export interface Props {
  content?: string
  // Only `name` is read, so only `name` is required — demanding a whole ApiFile
  // would force callers to synthesise ids and parents this wrapper never touches.
  file?: Pick<ApiFile, 'name'>
}

export default function SimulationViewWrapper({ content, file }: Props) {
  const fileName = file && typeof file.name === 'string' ? file.name : undefined
  return <Panel content={content} fileName={fileName} />
}
