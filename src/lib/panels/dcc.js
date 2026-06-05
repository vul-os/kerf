// src/lib/panels/dcc.js — panel registry fragment for Blender-parity DCC panels.
//
// Auto-collected by src/lib/panelRegistry.js via:
//   import.meta.glob('./panels/*.js', { eager: true })
//
// Three DCC workspace panels are registered:
//
//   sculpt_studio   (.sculpt)  — brush palette, DynaMesh, PolyPaint
//   animation_clip  (.anim)    — FCurve editor, IK solver, timeline
//   geometry_nodes  (.geonodes) — NodeGraphCanvas wrapper + evaluate
//
// Each panel receives from Editor.jsx:
//   { file, content, projectId, fileId, callTool, onCallTool, onDispatch }

export default [
  // ── Sculpt Studio ──────────────────────────────────────────────────────────
  {
    id: 'sculpt_studio',
    kinds: ['sculpt_studio'],
    exts: ['.sculpt'],
    load: () => import('../../components/dcc/SculptStudioPanel.jsx'),
    label: 'Sculpt Studio',
  },

  // ── Animation Timeline ─────────────────────────────────────────────────────
  {
    id: 'animation_clip',
    kinds: ['animation_clip'],
    exts: ['.anim'],
    load: () => import('../../components/dcc/AnimationTimelinePanel.jsx'),
    label: 'Animation Timeline',
  },

  // ── Geometry Nodes ─────────────────────────────────────────────────────────
  {
    id: 'geometry_nodes',
    kinds: ['geometry_nodes'],
    exts: ['.geonodes'],
    load: () => import('../../components/dcc/GeometryNodesPanel.jsx'),
    label: 'Geometry Nodes',
  },
]
