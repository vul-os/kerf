// LayoutViewerWrapper.jsx
// Wraps LayoutViewer for the panel registry.
// content JSON shape: { layout?: { cells: [...], topCell: string }, pdk?: 'sky130'|'gf180' }
import Panel from '../../../components/LayoutViewer.jsx'
import type { LayoutViewerProps } from '../../../components/LayoutViewer.jsx'

export interface Props {
  content?: string
}

interface LayoutViewerContent {
  layout?: unknown
  pdk?: unknown
}

function parseContent(content: string | undefined): LayoutViewerContent {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function LayoutViewerWrapper({ content }: Props) {
  const parsed = parseContent(content)
  const layout = (parsed.layout && typeof parsed.layout === 'object' ? parsed.layout : null) as LayoutViewerProps['layout']
  const pdk    = (typeof parsed.pdk === 'string' ? parsed.pdk : null) as LayoutViewerProps['pdk']
  return <Panel layout={layout} pdk={pdk} />
}
