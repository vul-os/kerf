// src/lib/panels/sim.js
//
// Panel registry fragment for simulation / analysis domain panels.
// Domain coverage:
//   ENERGY    — BuildingEnergyExportPanel, HeatExchangerPanel,
//               Hourly8760Panel, ThermoCyclePanel,
//               ComplianceReportPanel (ASHRAE 90.1 Appendix G + LEED + Title 24)
//   OPTICS    — DaylightingPanel, LightingSimPanel, SequentialTracePanel
//   ACOUSTICS — AcousticsResultPanel
//   SOLAR     — SolarPVPanel
//   CONTROLS  — ControlsPanel
//   MATERIALS — AshbyChartPanel, LCAResultsPanel
//   THERMAL   — ThermalNetworkViewer
//   CFD       — CfdResultsPanel
//
// Each `load` points to a thin wrapper in ./sim-wrappers/*.jsx that:
//   1. Accepts the standard Editor props: { file, content, projectId, fileId }
//   2. JSON.parse(content) with try/catch; merges parsed keys over defaults.
//   3. Passes resolved props down to the real panel.
//
// This file stays JSX-free so the `.js` glob in panelRegistry.js picks it up.

/** @type {Array<{id:string,kinds?:string[],exts?:string[],load:()=>Promise<any>,label?:string}>} */
export default [
  // ── Energy ──────────────────────────────────────────────────────────────
  {
    id: 'building-energy-export',
    kinds: ['building_energy_export', 'be_export'],
    exts: ['.bemodel', '.gbxml', '.idf'],
    load: () => import('./sim-wrappers/BuildingEnergyExportWrapper.jsx'),
    label: 'Building Energy Export',
  },
  {
    id: 'heat-exchanger',
    kinds: ['heat_exchanger', 'hx_design'],
    exts: ['.hxdesign', '.hx'],
    load: () => import('./sim-wrappers/HeatExchangerWrapper.jsx'),
    label: 'Heat Exchanger Design',
  },
  {
    id: 'hourly-8760',
    kinds: ['hourly_8760', 'building_energy_8760'],
    exts: ['.8760', '.8760sim'],
    load: () => import('./sim-wrappers/Hourly8760Wrapper.jsx'),
    label: '8760-Hour Building Energy',
  },
  {
    id: 'compliance-report',
    kinds: ['compliance_report', 'ashrae901_appendixg', 'energy_compliance'],
    exts: ['.compliance', '.appendixg'],
    load: () => import('./sim-wrappers/ComplianceReportWrapper.jsx'),
    label: 'ASHRAE 90.1 Appendix G / LEED / Title 24 Compliance',
  },
  {
    id: 'thermo-cycle',
    kinds: ['thermo_cycle', 'thermodynamic_cycle'],
    exts: ['.thermocycle', '.cycle'],
    load: () => import('./sim-wrappers/ThermoCycleWrapper.jsx'),
    label: 'Thermodynamic Cycle',
  },

  // ── Optics ──────────────────────────────────────────────────────────────
  {
    id: 'daylighting',
    kinds: ['daylighting', 'daylighting_sim'],
    exts: ['.daylight', '.daylighting'],
    load: () => import('./sim-wrappers/DaylightingWrapper.jsx'),
    label: 'Daylighting Simulation',
  },
  {
    id: 'lighting-sim',
    kinds: ['lighting_sim', 'photometric_sim'],
    exts: ['.lightsim', '.photometric'],
    load: () => import('./sim-wrappers/LightingSimWrapper.jsx'),
    label: 'Lighting Simulation',
  },
  {
    id: 'sequential-trace',
    kinds: ['sequential_trace', 'ray_trace'],
    exts: ['.raytrace', '.optrace'],
    load: () => import('./sim-wrappers/SequentialTraceWrapper.jsx'),
    label: 'Sequential Ray Trace',
  },

  // ── Acoustics ───────────────────────────────────────────────────────────
  {
    id: 'acoustics-result',
    kinds: ['acoustics_result', 'acoustics_sim'],
    exts: ['.acoustics', '.acresult'],
    load: () => import('./sim-wrappers/AcousticsWrapper.jsx'),
    label: 'Acoustics Analysis',
  },

  // ── Solar PV ────────────────────────────────────────────────────────────
  {
    id: 'solar-pv',
    kinds: ['solar_pv', 'pv_iv'],
    exts: ['.pvresult', '.pviv'],
    load: () => import('./sim-wrappers/SolarPVWrapper.jsx'),
    label: 'Solar PV I-V / P-V',
  },

  // ── Controls ────────────────────────────────────────────────────────────
  {
    id: 'controls',
    kinds: ['controls_result', 'controls_analysis'],
    exts: ['.ctrlresult', '.bode'],
    load: () => import('./sim-wrappers/ControlsWrapper.jsx'),
    label: 'Controls Analysis',
  },

  // ── Materials ────────────────────────────────────────────────────────────
  {
    id: 'ashby-chart',
    kinds: ['ashby_chart', 'material_chart'],
    exts: ['.ashby', '.matchart'],
    load: () => import('./sim-wrappers/AshbyChartWrapper.jsx'),
    label: 'Ashby Material Chart',
  },
  {
    id: 'lca-results',
    kinds: ['lca_result', 'lca_report'],
    exts: ['.lcaresult', '.lca'],
    load: () => import('./sim-wrappers/LCAResultsWrapper.jsx'),
    label: 'LCA Results',
  },

  // ── Thermal network ──────────────────────────────────────────────────────
  {
    id: 'thermal-network',
    kinds: ['thermal_network', 'thermal_net'],
    exts: ['.thermalnet', '.tnet'],
    load: () => import('./sim-wrappers/ThermalNetworkWrapper.jsx'),
    label: 'Thermal Network',
  },

  // ── CFD ─────────────────────────────────────────────────────────────────
  {
    id: 'cfd-results',
    kinds: ['cfd_result', 'cfd_post'],
    exts: ['.cfdresult', '.cfd'],
    load: () => import('./sim-wrappers/CfdResultsWrapper.jsx'),
    label: 'CFD Results',
  },
  {
    id: 'reacting-flow',
    kinds: ['reacting_flow', 'multispecies_reacting_flow', 'cfd_reacting'],
    exts: ['.reactflow', '.reactingflow'],
    load: () => import('./sim-wrappers/ReactingFlowWrapper.jsx'),
    label: 'Reacting Flow (Multi-Species)',
  },

  // ── Electromagnetics FEM ─────────────────────────────────────────────────
  {
    id: 'em-field',
    kinds: ['em_field', 'em_electrostatics', 'em_magnetostatics', 'fem_em'],
    exts: ['.emresult', '.emfield'],
    load: () => import('./sim-wrappers/EMFieldWrapper.jsx'),
    label: 'EM Field (Electrostatics / Magnetostatics)',
  },

  // ── FEM Contact (friction + augmented-Lagrange) ──────────────────────────
  {
    id: 'contact-result',
    kinds: ['contact_result', 'fem_contact', 'contact_friction'],
    exts: ['.contactresult', '.contact'],
    load: () => import('./sim-wrappers/ContactResultWrapper.jsx'),
    label: 'FEM Contact (friction / gap / augmented-Lagrange)',
  },

  // ── Plasma / gas-discharge (drift-diffusion) ─────────────────────────────
  // 1-D DC glow-discharge: electron/ion density profiles, E-field, Paschen curve.
  // Tool: plasma_discharge_simulate (kerf-cfd)
  // Model: Hagelaar & Pitchford 2005 drift-diffusion; Townsend ionisation; Poisson self-field.
  // NOTE: drift-diffusion fluid model only — not kinetic/PIC; DC only; single gas species.
  {
    id: 'plasma-discharge',
    kinds: ['plasma_discharge', 'glow_discharge', 'gas_discharge', 'plasma_dd'],
    exts: ['.plasma', '.glowdischarge', '.discharge'],
    load: () => import('./sim-wrappers/PlasmaDischargeWrapper.jsx'),
    label: 'Plasma / Gas Discharge (Drift-Diffusion)',
  },
]
