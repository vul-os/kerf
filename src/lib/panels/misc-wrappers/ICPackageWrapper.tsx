// ICPackageWrapper.jsx
// Wraps ICPackagePanel for the panel registry.
// content JSON shape: { ic_package?: {...} }
import Panel from '../../../components/electronics/ICPackagePanel.jsx'

export interface Props {
  content?: string
}

function parseContent(content: string | undefined): Record<string, unknown> {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function ICPackageWrapper({ content }: Props) {
  // eslint-disable-next-line no-unused-vars
  const _parsed = parseContent(content)
  // ICPackagePanel manages its own demo state; ic_package prop could be
  // wired in future once the panel accepts it as a prop.
  return <Panel />
}
