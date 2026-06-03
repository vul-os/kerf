// parts_library.js — Symbol definitions for the schematic editor.
//
// Each part defines:
//   id        — unique part type identifier
//   label     — human-readable name shown in the sidebar
//   category  — grouping for the sidebar
//   pins      — array of {id, dx, dy, name} — offsets in mils from part origin
//   defaultProps — initial property values
//   spicePrefix — SPICE element prefix letter(s)
//
// The SVG symbol for each part is described as a list of path primitives
// (lines + arcs + circles) in a 100x60 mil bounding box centered on 0,0.
// The renderer in Canvas.jsx interprets these.

export const GRID = 25   // mil
export const VW   = 1600 // canvas viewBox width (mil)
export const VH   = 1000 // canvas viewBox height (mil)

// ── Pin directions ────────────────────────────────────────────────────────────
// dx/dy are in mils from part centre.  Convention: left pins have dx<0, etc.

const PARTS = [
  // ── Passives ──────────────────────────────────────────────────────────────
  {
    id: 'R',
    label: 'Resistor',
    category: 'Passives',
    spicePrefix: 'R',
    pins: [
      { id: 'p1', dx: -50, dy: 0, name: '1' },
      { id: 'p2', dx:  50, dy: 0, name: '2' },
    ],
    defaultProps: { resistance: '1k' },
    symbol: {
      // body: zigzag from (-30,0) to (30,0), height ±10
      lines: [
        [-50,0,-30,0], [-30,0,-20,-12], [-20,-12,0,12], [0,12,20,-12], [20,-12,30,0], [30,0,50,0],
      ],
      circles: [],
      arcs: [],
    },
  },
  {
    id: 'C',
    label: 'Capacitor',
    category: 'Passives',
    spicePrefix: 'C',
    pins: [
      { id: 'p1', dx: -50, dy: 0, name: '+' },
      { id: 'p2', dx:  50, dy: 0, name: '-' },
    ],
    defaultProps: { capacitance: '100n' },
    symbol: {
      lines: [
        [-50,0,-8,0],  // lead left
        [-8,-18,-8,18], // plate left (vertical)
        [8,-18,8,18],   // plate right
        [8,0,50,0],    // lead right
      ],
      circles: [],
      arcs: [],
    },
  },
  {
    id: 'L',
    label: 'Inductor',
    category: 'Passives',
    spicePrefix: 'L',
    pins: [
      { id: 'p1', dx: -50, dy: 0, name: '1' },
      { id: 'p2', dx:  50, dy: 0, name: '2' },
    ],
    defaultProps: { inductance: '100u' },
    symbol: {
      lines: [[-50,0,-30,0],[30,0,50,0]],
      arcs: [
        // four half-circles along x-axis
        { cx: -20, cy: 0, r: 10, a1: 180, a2: 0 },
        { cx:   0, cy: 0, r: 10, a1: 180, a2: 0 },
        { cx:  20, cy: 0, r: 10, a1: 180, a2: 0 },
      ],
      circles: [],
    },
  },

  // ── Diodes ────────────────────────────────────────────────────────────────
  {
    id: 'Diode',
    label: 'Diode',
    category: 'Diodes',
    spicePrefix: 'D',
    pins: [
      { id: 'A', dx: -50, dy: 0, name: 'A' },
      { id: 'K', dx:  50, dy: 0, name: 'K' },
    ],
    defaultProps: { model: 'D1N4148' },
    symbol: {
      lines: [
        [-50,0,-20,0],          // anode lead
        [-20,-18,-20,18],       // left vertical
        [-20,-18,20,0],         // triangle top
        [-20,18,20,0],          // triangle bottom
        [20,-18,20,18],         // cathode bar
        [20,0,50,0],            // cathode lead
      ],
      circles: [],
      arcs: [],
    },
  },
  {
    id: 'LED',
    label: 'LED',
    category: 'Diodes',
    spicePrefix: 'D',
    pins: [
      { id: 'A', dx: -50, dy: 0, name: 'A' },
      { id: 'K', dx:  50, dy: 0, name: 'K' },
    ],
    defaultProps: { model: 'D1N4148', color: 'red' },
    symbol: {
      lines: [
        [-50,0,-20,0],
        [-20,-18,-20,18],
        [-20,-18,20,0],
        [-20,18,20,0],
        [20,-18,20,18],
        [20,0,50,0],
        // emission arrows
        [28,-22,40,-10],
        [38,-22,50,-10],
      ],
      circles: [],
      arcs: [],
    },
  },
  {
    id: 'Zener',
    label: 'Zener',
    category: 'Diodes',
    spicePrefix: 'D',
    pins: [
      { id: 'A', dx: -50, dy: 0, name: 'A' },
      { id: 'K', dx:  50, dy: 0, name: 'K' },
    ],
    defaultProps: { model: 'DZENER5V1', bv: '5.1' },
    symbol: {
      lines: [
        [-50,0,-20,0],
        [-20,-18,-20,18],
        [-20,-18,20,0],
        [-20,18,20,0],
        [20,-22,20,18],  // bent top
        [20,-22,30,-22], // zener kink top
        [20,18,10,18],   // zener kink bottom
        [20,0,50,0],
      ],
      circles: [],
      arcs: [],
    },
  },

  // ── MOSFETs ───────────────────────────────────────────────────────────────
  {
    id: 'NMOS',
    label: 'NMOS',
    category: 'Transistors',
    spicePrefix: 'M',
    pins: [
      { id: 'G', dx: -50, dy: 0, name: 'G' },
      { id: 'D', dx:  0,  dy: -50, name: 'D' },
      { id: 'S', dx:  0,  dy:  50, name: 'S' },
    ],
    defaultProps: { model: 'NMOS', W: '10u', L: '1u' },
    symbol: {
      lines: [
        [-50,0,0,0],       // gate lead
        [0,-30,0,30],      // gate oxide
        [10,-30,10,-10], [10,10,10,30],  // channel
        [10,-10,30,-10],[30,-10,30,-50], // drain
        [10,10,30,10],[30,10,30,50],     // source
        // arrow body (NMOS — pointing in)
        [10,0,20,0],[20,-5,10,0],[20,5,10,0],
      ],
      circles: [],
      arcs: [],
    },
  },
  {
    id: 'PMOS',
    label: 'PMOS',
    category: 'Transistors',
    spicePrefix: 'M',
    pins: [
      { id: 'G', dx: -50, dy: 0, name: 'G' },
      { id: 'D', dx:  0,  dy:  50, name: 'D' },
      { id: 'S', dx:  0,  dy: -50, name: 'S' },
    ],
    defaultProps: { model: 'PMOS', W: '10u', L: '1u' },
    symbol: {
      lines: [
        [-50,0,0,0],
        [0,-30,0,30],
        [10,-30,10,-10],[10,10,10,30],
        [10,-10,30,-10],[30,-10,30,-50],
        [10,10,30,10],[30,10,30,50],
        // arrow (PMOS — pointing out)
        [20,0,10,0],[10,-5,20,0],[10,5,20,0],
      ],
      circles: [{ cx: -8, cy: 0, r: 6 }],
      arcs: [],
    },
  },

  // ── BJTs ─────────────────────────────────────────────────────────────────
  {
    id: 'NPN',
    label: 'NPN',
    category: 'Transistors',
    spicePrefix: 'Q',
    pins: [
      { id: 'B', dx: -50, dy: 0, name: 'B' },
      { id: 'C', dx:  0,  dy: -50, name: 'C' },
      { id: 'E', dx:  0,  dy:  50, name: 'E' },
    ],
    defaultProps: { model: 'Q2N3904' },
    symbol: {
      lines: [
        [-50,0,0,0],
        [0,-30,0,30],
        [0,-15,30,-50],    // collector
        [0,15,30,50],      // emitter
        // arrow on emitter (NPN — pointing out)
        [20,36,30,50],[22,46,30,50],
      ],
      circles: [{ cx: 15, cy: 0, r: 25, fill: 'none', stroke: true }],
      arcs: [],
    },
  },
  {
    id: 'PNP',
    label: 'PNP',
    category: 'Transistors',
    spicePrefix: 'Q',
    pins: [
      { id: 'B', dx: -50, dy: 0, name: 'B' },
      { id: 'C', dx:  0,  dy:  50, name: 'C' },
      { id: 'E', dx:  0,  dy: -50, name: 'E' },
    ],
    defaultProps: { model: 'Q2N3906' },
    symbol: {
      lines: [
        [-50,0,0,0],
        [0,-30,0,30],
        [0,-15,30,-50],
        [0,15,30,50],
        // arrow on base side of emitter (PNP — pointing in)
        [8,-8,0,-15],[14,-4,0,-15],
      ],
      circles: [{ cx: 15, cy: 0, r: 25, fill: 'none', stroke: true }],
      arcs: [],
    },
  },

  // ── Op-Amp ────────────────────────────────────────────────────────────────
  {
    id: 'OpAmp',
    label: 'Op-Amp',
    category: 'Active',
    spicePrefix: 'X',
    pins: [
      { id: 'IN+', dx: -50, dy: -20, name: '+' },
      { id: 'IN-', dx: -50, dy:  20, name: '-' },
      { id: 'OUT', dx:  50, dy: 0,   name: 'OUT' },
    ],
    defaultProps: { model: 'OPAMP_IDEAL', Av: '1e5' },
    symbol: {
      lines: [
        [-30,-40,50,0],
        [-30,40,50,0],
        [-30,-40,-30,40],
        [-50,-20,-30,-20],
        [-50,20,-30,20],
        [30,0,50,0],
      ],
      circles: [],
      arcs: [],
    },
  },

  // ── Sources ───────────────────────────────────────────────────────────────
  {
    id: 'VSource',
    label: 'V Source',
    category: 'Sources',
    spicePrefix: 'V',
    pins: [
      { id: '+', dx: 0, dy: -50, name: '+' },
      { id: '-', dx: 0, dy:  50, name: '-' },
    ],
    defaultProps: { dc: '5', ac: '0', type: 'dc' },
    symbol: {
      circles: [{ cx: 0, cy: 0, r: 28 }],
      lines: [
        [0,-50,0,-28],
        [0,28,0,50],
        [0,-18,0,-8],   // + top
        [-5,-13,5,-13], // + crossbar
        [0,8,0,18],     // − bottom
      ],
      arcs: [],
    },
  },
  {
    id: 'ISource',
    label: 'I Source',
    category: 'Sources',
    spicePrefix: 'I',
    pins: [
      { id: '+', dx: 0, dy: -50, name: '+' },
      { id: '-', dx: 0, dy:  50, name: '-' },
    ],
    defaultProps: { dc: '1m', type: 'dc' },
    symbol: {
      circles: [{ cx: 0, cy: 0, r: 28 }],
      lines: [
        [0,-50,0,-28],
        [0,28,0,50],
        // arrow pointing up
        [0,-18,0,18],
        [-8,4,0,-18],[8,4,0,-18],
      ],
      arcs: [],
    },
  },

  // ── GND ───────────────────────────────────────────────────────────────────
  {
    id: 'GND',
    label: 'Ground',
    category: 'Power',
    spicePrefix: '',
    pins: [
      { id: 'GND', dx: 0, dy: -25, name: 'GND' },
    ],
    defaultProps: { net: '0' },
    symbol: {
      lines: [
        [0,-25,0,0],
        [-25,0,25,0],
        [-16,10,16,10],
        [-8,20,8,20],
      ],
      circles: [],
      arcs: [],
    },
  },

  // ── Probe ─────────────────────────────────────────────────────────────────
  {
    id: 'Probe',
    label: 'Probe',
    category: 'Measurement',
    spicePrefix: '',
    pins: [
      { id: 'TIP', dx: 0, dy: 25, name: 'tip' },
    ],
    defaultProps: { label: 'V?', kind: 'voltage' },
    symbol: {
      lines: [
        [0,25,0,0],
        [-18,-20,18,-20],
        [-18,-20,0,0],
        [18,-20,0,0],
        [-18,-20,-18,-38],[-18,-38,18,-38],[18,-38,18,-20],
      ],
      circles: [],
      arcs: [],
    },
  },
]

export default PARTS

// Lookup by id
export const PARTS_MAP = Object.fromEntries(PARTS.map((p) => [p.id, p]))

// All categories in display order
export const CATEGORIES = [
  'Passives',
  'Diodes',
  'Transistors',
  'Active',
  'Sources',
  'Power',
  'Measurement',
]
