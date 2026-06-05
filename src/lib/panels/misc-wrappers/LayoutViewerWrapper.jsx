// LayoutViewerWrapper.jsx
// Wraps LayoutViewer for the panel registry.
// content JSON shape: { layout?: { cells: [...], topCell: string }, pdk?: 'sky130'|'gf180' }
import Panel from '../../../components/LayoutViewer.jsx'

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function LayoutViewerWrapper({ content }) {
  const parsed = parseContent(content)
  const layout = parsed.layout && typeof parsed.layout === 'object' ? parsed.layout : null
  const pdk    = typeof parsed.pdk === 'string' ? parsed.pdk : null
  return <Panel layout={layout} pdk={pdk} />
}
