// src/lib/panels/elec.js
//
// Panel-registry fragment — Electronics / EDA panels.
// Collected automatically by panelRegistry.js via import.meta.glob('./panels/*.js').
// Each entry: { id, kinds, exts, load: () => import('…'), label }
//
// Panels registered here:
//   SpiceComponentLibraryPanel — categorized SPICE model browser:
//     - Category tree (diode_rectifier / schottky / zener / TVS / LED,
//       BJT NPN/PNP/Darlington/RF, MOSFET N/P, JFET, op-amp, comparator,
//       voltage reference, regulator, passives, logic gates, ICs)
//     - Keyword + spec-filter search
//     - Model-card preview (full .MODEL / .SUBCKT SPICE text)
//     - "Insert into netlist" action (fires a kerf:spice-insert custom event)

/** @type {Array<{id:string,kinds?:string[],exts?:string[],load:()=>Promise<any>,label?:string}>} */
export default [
  // ── SPICE Component / Model Library Browser ──────────────────────────────
  {
    id: 'spice-component-library',
    kinds: ['spice_library', 'spice_component_browser', 'eda_library'],
    exts: ['.spicelib', '.spice_lib', '.spicedb'],
    load: () => import('./elec-wrappers/SpiceComponentLibraryWrapper.jsx'),
    label: 'SPICE Component Library',
  },
];
