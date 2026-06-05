// CfdPostProcessWrapper.jsx
// Wrapper for the CFD post-processing panel.
// content JSON is parsed and passed to CfdPostProcessPanel.

import Panel from '../../../components/CfdPostProcessPanel.jsx'

const DEFAULTS = {
  filter: null,        // 'slice' | 'contour' | 'streamline' | 'integral' | 'probe' | 'derived'
  filterResult: null,  // result dict from cfd_postprocess_filter
  exportPath: null,    // path from cfd_export_vtk
  exportMeta: null,    // {n_points, n_cells, format, file_size_bytes}
  fieldStats: null,
  n_cells: null,
}

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function CfdPostProcessWrapper({ content }) {
  const props = { ...DEFAULTS, ...parseContent(content) }
  return <Panel {...props} />
}
