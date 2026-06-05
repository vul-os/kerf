/**
 * entertainment.js — panel-registry fragment for theatrical / entertainment panels.
 *
 * Wires two domain panels into the Editor's panel-registry seam:
 *   • entertainment_lighting_plot → LightingPlotPanel
 *   • entertainment_rigging       → RiggingLoadPanel
 *
 * Auto-collected by src/lib/panelRegistry.js via import.meta.glob.
 * DO NOT import panelRegistry.js here — circular dependency.
 *
 * content prop convention:
 *   The Editor passes a `content` string (raw file text / JSON) to the
 *   resolved Panel.  Each panel JSON.parse-parses it and merges recognised
 *   keys over its own default props.
 *
 * File kinds and extensions:
 *
 *   LIGHTING PLOT
 *     entertainment_lighting_plot → LightingPlotPanel   (.lxplot)
 *
 *   RIGGING LOAD ANALYSIS
 *     entertainment_rigging       → RiggingLoadPanel    (.rigging)
 */

export default [
  // ── Lighting plot + DMX patch ────────────────────────────────────────────

  {
    id: 'entertainment_lighting_plot',
    kinds: ['entertainment_lighting_plot'],
    exts: ['.lxplot'],
    label: 'Lighting Plot',
    load: () => import('../../components/entertainment/LightingPlotPanel.jsx'),
  },

  // ── Rigging load analysis ─────────────────────────────────────────────────

  {
    id: 'entertainment_rigging',
    kinds: ['entertainment_rigging'],
    exts: ['.rigging'],
    label: 'Rigging Load Analysis',
    load: () => import('../../components/entertainment/RiggingLoadPanel.jsx'),
  },
]
