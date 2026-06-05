// src/lib/panels/archviz.js — panel registry fragment for archviz scatter / population.
//
// Auto-collected by src/lib/panelRegistry.js via:
//   import.meta.glob('./panels/*.js', { eager: true })
//
// Panel registered:
//
//   archviz_scatter  (.archviz_scatter)  — procedural scatter + asset palette
//
// Backend tools used by this panel:
//   archviz_scatter_populate  — run the scatter engine (kerf_render.archviz_tools)
//   archviz_asset_library     — browse the built-in proxy asset catalogue

export default [
  // ── Archviz Scatter / Population ──────────────────────────────────────────
  {
    id: 'archviz_scatter',
    kinds: ['archviz_scatter'],
    exts: ['.archviz_scatter'],
    load: () => import('../../components/archviz/ArchvizScatterPanel.jsx'),
    label: 'Archviz Scatter',
  },
]
