// ICPackageWrapper.jsx
// Wraps ICPackagePanel for the panel registry.
// content JSON shape: { ic_package?: {...} }
import Panel from '../../../components/electronics/ICPackagePanel.jsx'

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function ICPackageWrapper({ content }) {
  // eslint-disable-next-line no-unused-vars
  const _parsed = parseContent(content)
  // ICPackagePanel manages its own demo state; ic_package prop could be
  // wired in future once the panel accepts it as a prop.
  return <Panel />
}
