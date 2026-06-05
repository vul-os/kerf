// Panel-registry fragment — Plant piping panels
//
// Collected automatically by panelRegistry.js via import.meta.glob('./panels/*.js').
// Each entry: { id, kinds, exts, load: () => import('…'), label }
//
// Panels wired here:
//   PipingRoute3DPanel     — 3D intelligent pipe routing (orthogonal + AABB avoidance)
//                             with isometric projection, fitting BOM, ASME B16.9/B31.3
//   PipingCataloguePanel   — Spec-driven ASME B16.9/B16.5 3D component catalogue picker
//                             (elbows 45/90 LR/SR, tees, reducers, flanges, valves, caps)

export default [
  {
    id: 'piping_route_3d',
    kinds: ['piping_route_3d', 'piping_isometric'],
    exts: ['.pipe3d', '.piso'],
    load: () => import('../../components/piping/PipingRoute3DPanel.jsx'),
    label: 'Pipe Route 3D (ASME B31.3)',
  },
  {
    id: 'piping_catalogue',
    kinds: ['piping_catalogue', 'piping_component'],
    exts: ['.pipefitting', '.pipecatalogue'],
    load: () => import('../../components/piping/PipingCataloguePanel.jsx'),
    label: 'Piping Component Catalogue (ASME B16.9/B16.5)',
  },
]
