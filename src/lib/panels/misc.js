// src/lib/panels/misc.js
//
// Panel registry fragment for miscellaneous standalone panels that do not
// belong to an existing domain fragment (aero / civilbim / mech / mfg / sim /
// verticals / motion).
//
// Panels wired here:
//   BIMPhasePanel        — Renovation phase management (BIM, ArchiCAD parity)
//   CfdViewport          — 2-D CFD canvas viewport (streamlines / arrows / pressure)
//   FirmwareDebugPanel   — RTOS-aware firmware debug side-panel (JTAG / OpenOCD)
//   KiCadRoundTripPanel  — KiCad export → route → import round-trip workflow
//   LayoutViewer         — In-browser IC layout viewer (GDS-II, KLayout-style)
//   RFViewWrapper        — S-parameter RF analysis view (Smith chart / VSWR)
//   SimulationView       — SPICE .simulation file viewer (transient / DC / AC)
//   WiringView           — WireViz YAML harness diagram renderer
//
// Each `load` points to a thin wrapper in ./misc-wrappers/*.jsx that:
//   1. Accepts the standard Editor props: { file, content, projectId, fileId, callTool, onCallTool }
//   2. JSON.parse(content) with try/catch; merges parsed keys over the panel's defaults.
//   3. Passes resolved props down to the real panel.
//
// This file stays JSX-free so the `.js` glob in panelRegistry.js picks it up.

/** @type {Array<{id:string,kinds?:string[],exts?:string[],load:()=>Promise<any>,label?:string}>} */
export default [
  // ── BIM: Renovation Phase Management ─────────────────────────────────────
  {
    id: 'bim_phase',
    kinds: ['bim_phase', 'bim_renovation_phase'],
    exts: ['.bimphase'],
    load: () => import('./misc-wrappers/BIMPhaseWrapper.jsx'),
    label: 'BIM Phase Manager',
  },

  // ── CFD: 2-D Canvas Viewport ──────────────────────────────────────────────
  // Note: CfdResultsPanel (wired in sim.js) is a distinct stats/residuals panel.
  // CfdViewport is a canvas-based streamlines/arrows/pressure visualiser.
  {
    id: 'cfd_viewport',
    kinds: ['cfd_viewport', 'cfd_field'],
    exts: ['.cfdvp', '.cfdfield'],
    load: () => import('./misc-wrappers/CfdViewportWrapper.jsx'),
    label: 'CFD Viewport',
  },

  // ── Firmware: RTOS Debug Panel ─────────────────────────────────────────────
  {
    id: 'firmware_debug',
    kinds: ['firmware_debug', 'rtos_debug'],
    exts: ['.elfdbg', '.rtosdbg'],
    load: () => import('./misc-wrappers/FirmwareDebugWrapper.jsx'),
    label: 'Firmware RTOS Debugger',
  },

  // ── Electronics: KiCad Round-Trip ─────────────────────────────────────────
  {
    id: 'kicad_roundtrip',
    kinds: ['kicad_roundtrip', 'kicad_bridge'],
    exts: ['.kicadroundtrip', '.kicadbridge'],
    load: () => import('./misc-wrappers/KiCadRoundTripWrapper.jsx'),
    label: 'KiCad Round-Trip',
  },

  // ── IC Design: GDS-II Layout Viewer ───────────────────────────────────────
  {
    id: 'ic_layout',
    kinds: ['ic_layout', 'gds_layout'],
    exts: ['.gds', '.gdsii', '.gds2'],
    load: () => import('./misc-wrappers/LayoutViewerWrapper.jsx'),
    label: 'IC Layout Viewer',
  },

  // ── RF / Antenna: S-Parameter Analysis ───────────────────────────────────
  {
    id: 'rf_analysis',
    kinds: ['rf_analysis', 'rf_result', 's_param'],
    exts: ['.rfresult', '.sparam'],
    load: () => import('./misc-wrappers/RFViewWrapper.jsx'),
    label: 'RF Analysis',
  },

  // ── Simulation: SPICE .simulation files ──────────────────────────────────
  {
    id: 'simulation_view',
    kinds: ['simulation', 'spice_simulation'],
    exts: ['.simulation'],
    load: () => import('./misc-wrappers/SimulationViewWrapper.jsx'),
    label: 'Simulation',
  },

  // ── Wiring: WireViz harness diagram ──────────────────────────────────────
  {
    id: 'wiring_view',
    kinds: ['wiring', 'wireviz_harness'],
    exts: ['.wiring'],
    load: () => import('./misc-wrappers/WiringViewWrapper.jsx'),
    label: 'Wiring Diagram',
  },

  // ── Electronics: IC Package / Substrate Designer (APD parity) ─────────────
  {
    id: 'ic_package',
    kinds: ['ic_package', 'ic_substrate', 'bga_package', 'wire_bond_package'],
    exts: ['.icpkg', '.icsubstrate'],
    load: () => import('./misc-wrappers/ICPackageWrapper.jsx'),
    label: 'IC Package Designer',
  },

  // ── Electronics: Constraint Manager Spreadsheet UI (Allegro parity) ───────
  {
    id: 'constraint_manager',
    kinds: ['constraint_manager', 'pcb_constraints', 'net_class_table'],
    exts: ['.constraints', '.cmgr'],
    load: () => import('./misc-wrappers/ConstraintManagerWrapper.jsx'),
    label: 'Constraint Manager',
  },
]
