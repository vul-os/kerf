/**
 * silicon.meta.js — SEO metadata + JSON-LD for the Silicon domain page.
 *
 * Exported constants are consumed by Silicon.jsx for <head> injection
 * and tested in landing.silicon.test.js.
 */

export const META_TITLE = 'Silicon design with chat-driven EDA — Kerf'

export const META_DESCRIPTION =
  'Chat-driven IC and ASIC layout: RTL, PnR, DRC, LVS, parasitic extraction, ' +
  'timing closure — GDS-II out, open PDKs supported.'

export const META_OG_IMAGE = 'https://kerf.sh/og/silicon.png'

export const META_URL = 'https://kerf.sh/domains/silicon'

export const TAGLINE = 'From RTL to GDS-II in a conversation.'

// Feature list — one entry per capability card.
export const FEATURES = [
  {
    id: 'rtl-synthesis',
    name: 'RTL synthesis (Yosys)',
    description:
      'Synthesise Verilog/SystemVerilog RTL to a gate netlist with Yosys. Technology mapping for Sky130, GF180MCU and OpenROAD-compatible PDKs. LUT-level output for FPGA targets.',
  },
  {
    id: 'pnr',
    name: 'Place & route (OpenROAD)',
    description:
      'Floorplan, placement, CTS and global/detailed routing via OpenROAD. DEF/LEF round-trip. Constraint-driven: timing, power-domain and DRC targets expressed in SDC/UPF.',
  },
  {
    id: 'drc-lvs',
    name: 'DRC + LVS (Magic / Netgen)',
    description:
      'Layout versus schematic and design-rule checks via Magic and Netgen. Violations surface inline with cell context. Supports Sky130 and GF180MCU rule decks out of the box.',
  },
  {
    id: 'parasitic-extraction',
    name: 'Parasitic extraction (SPEF)',
    description:
      'RC parasitics extracted from routed DEF via OpenRCX. SPEF output feeds back into STA and SPICE for post-layout simulation. Coupling caps included.',
  },
  {
    id: 'sta',
    name: 'Static timing analysis (OpenSTA)',
    description:
      'Full STA via OpenSTA. Setup/hold slack, critical-path reporting, multi-corner MMMC. SDC constraints edited in chat and re-run automatically on each PnR iteration.',
  },
  {
    id: 'spice-post-layout',
    name: 'Post-layout SPICE simulation',
    description:
      'ngspice-backed transient and AC simulations using SPEF-annotated netlists. Waveforms and measurement expressions available in the chat loop. Model library tracks PDK device corners.',
  },
  {
    id: 'gds-ii',
    name: 'GDS-II export',
    description:
      'Final GDS-II stream file produced via KLayout Python API. Includes top-level cell merge, layer mapping, and optional stream compression. Submit-ready for CMP shuttle services.',
  },
  {
    id: 'schematic-capture',
    name: 'Schematic capture + netlist',
    description:
      'Custom-cell schematic entry with PDK-aware symbol libraries. Exports SPICE netlist for pre-layout simulation. Hierarchical sheets with port connectivity carried through to PnR.',
  },
  {
    id: 'layout-viewer',
    name: 'Interactive layout viewer',
    description:
      'GDS-II and DEF rendered in the browser via KLayout WebAssembly. Layer visibility, ruler, LPP filter, DRC marker overlay — no external viewer required.',
  },
  {
    id: 'open-pdk',
    name: 'Open PDK support (Sky130, GF180MCU)',
    description:
      'Sky130B and GF180MCU PDKs bundled. Standard cell libraries, IO ring, seal ring, fill cells and decap cells included. Efabless caravel SoC wrapper template ships as a starter project.',
  },
  {
    id: 'fpga-bitstream',
    name: 'FPGA synthesis + bitstream (nextpnr)',
    description:
      'Yosys synthesis + nextpnr place-and-route for iCE40 and ECP5 targets. Pack → place → route → bitstream in a single chat command. iceprog/openFPGALoader flash integration.',
  },
  {
    id: 'kerf-sdk-silicon',
    name: 'Python SDK — kerf-sdk silicon surface',
    description:
      'pip install kerf-sdk. JSON-RPC access to all EDA tool calls: run_rtl_synth, run_pnr, run_drc, run_spice. Drive parameter sweeps, corner analysis, and CI tape-out checks from scripts.',
  },
]

export const JSON_LD = {
  '@context': 'https://schema.org',
  '@graph': [
    {
      '@type': 'WebPage',
      '@id': META_URL,
      url: META_URL,
      name: META_TITLE,
      description: META_DESCRIPTION,
      image: META_OG_IMAGE,
      publisher: {
        '@type': 'Organization',
        name: 'Kerf',
        url: 'https://kerf.sh',
      },
    },
    {
      '@type': 'ItemList',
      name: 'Kerf Silicon / IC design capabilities',
      description: 'EDA features for chip and FPGA design in Kerf',
      numberOfItems: FEATURES.length,
      itemListElement: FEATURES.map((f, i) => ({
        '@type': 'ListItem',
        position: i + 1,
        name: f.name,
        description: f.description,
      })),
    },
  ],
}
