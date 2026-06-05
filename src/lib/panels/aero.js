// aero.js — panel registry fragment for aerospace + marine panels.
//
// Auto-collected by src/lib/panelRegistry.js via import.meta.glob('./panels/*.js').
// Each entry maps a file kind and/or extension to a lazily-loaded React panel.
// Editor.jsx wraps the resolved panel in <Suspense> and passes:
//   { file, content, projectId, fileId }
//
// All panels accept a `content` string prop and JSON.parse it for backward-
// compatible stand-alone usage (direct props still work).

export default [
  // ── Aerospace ──────────────────────────────────────────────────────────────

  {
    id: 'motor_select',
    kinds: ['aero_motor'],
    exts: ['.motor'],
    load: () => import('../../components/aerospace/MotorSelectPanel.jsx'),
    label: 'Motor Database',
  },

  {
    id: 'orbit_determination',
    kinds: ['aero_orbit_det'],
    exts: ['.orbitdet'],
    load: () => import('../../components/aerospace/OrbitDeterminationPanel.jsx'),
    label: 'Orbit Determination',
  },

  {
    id: 'flutter',
    kinds: ['aero_flutter'],
    exts: ['.flutter'],
    load: () => import('../../components/FlutterPanel.jsx'),
    label: 'Flutter Analysis',
  },

  {
    id: 'reentry_heat_flux',
    kinds: ['aero_reentry'],
    exts: ['.reentry'],
    load: () => import('../../components/ReentryHeatFluxPanel.jsx'),
    label: 'Re-entry Heat Flux',
  },

  {
    id: 'sixdof',
    kinds: ['aero_sixdof'],
    exts: ['.sixdof'],
    load: () => import('../../components/SixDOFPanel.jsx'),
    label: '6-DOF Flight Dynamics',
  },

  {
    id: 'staging',
    kinds: ['aero_staging'],
    exts: ['.staging'],
    load: () => import('../../components/StagingPanel.jsx'),
    label: 'Staging Analysis',
  },

  {
    id: 'attitude',
    kinds: ['aero_attitude'],
    exts: ['.attitude'],
    load: () => import('../../components/AttitudeViewer.jsx'),
    label: 'Attitude Viewer',
  },

  // ── Marine ─────────────────────────────────────────────────────────────────

  {
    id: 'seakeeping_rao',
    kinds: ['marine_rao'],
    exts: ['.rao'],
    load: () => import('../../components/SeakeepingRAOPanel.jsx'),
    label: 'Seakeeping RAOs',
  },

  {
    id: 'hull_form',
    kinds: ['marine_hull'],
    exts: ['.hullform'],
    load: () => import('../../components/HullFormPanel.jsx'),
    label: 'Hull Form',
  },

  {
    id: 'hull_exchange',
    kinds: ['marine_hull_exchange'],
    exts: ['.hullx'],
    load: () => import('../../components/HullExchangePanel.jsx'),
    label: 'Hull Exchange',
  },
]
