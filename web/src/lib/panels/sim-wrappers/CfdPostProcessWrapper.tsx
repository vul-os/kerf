// CfdPostProcessWrapper.jsx
// Wrapper for the CFD post-processing panel.
// content JSON is parsed and passed to CfdPostProcessPanel.

import Panel from '../../../components/CfdPostProcessPanel.jsx'

export interface Props {
  content?: string
}

// CfdPostProcessPanel.jsx is not yet migrated, so there's no Props type to
// import; this mirrors its documented shape (see that file's header comment).
interface CfdPostProcessContent {
  filter?: string | null        // 'slice' | 'contour' | 'streamline' | 'integral' | 'probe' | 'derived'
  filterResult?: unknown        // result dict from cfd_postprocess_filter
  exportPath?: string | null    // path from cfd_export_vtk
  exportMeta?: unknown          // {n_points, n_cells, format, file_size_bytes}
  fieldStats?: unknown
  n_cells?: number | null
}

const DEFAULTS: CfdPostProcessContent = {
  filter: null,
  filterResult: null,
  exportPath: null,
  exportMeta: null,
  fieldStats: null,
  n_cells: null,
}

function parseContent(content: string | undefined): CfdPostProcessContent {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function CfdPostProcessWrapper({ content }: Props) {
  const props = { ...DEFAULTS, ...parseContent(content) }
  return <Panel {...props} />
}
