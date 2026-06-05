/**
 * misc.test.jsx
 *
 * Vitest tests for the misc panel-registry fragment (src/lib/panels/misc.js).
 *
 * Panels wired:
 *   BIMPhasePanel          bim_phase         / .bimphase
 *   CfdViewport            cfd_viewport      / .cfdvp
 *   FirmwareDebugPanel     firmware_debug    / .elfdbg
 *   KiCadRoundTripPanel    kicad_roundtrip   / .kicadroundtrip
 *   LayoutViewer           ic_layout         / .gds
 *   RFView                 rf_analysis       / .rfresult
 *   SimulationView         simulation_view   / .simulation
 *   WiringView             wiring_view       / .wiring
 *
 * Strategy
 * --------
 * 1. Import the misc fragment directly (no import.meta.glob needed).
 * 2. Inline resolvePanelEntry mirrors panelRegistry.js logic.
 * 3. Mount tests use renderToStaticMarkup (react-dom/server, no DOM env).
 *    Panels that call hooks on render are mocked at the module level.
 * 4. Heavy canvas draw calls happen inside useEffect / useCallback and are
 *    no-ops during SSR → safe to renderToStaticMarkup without jsdom.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import React from 'react'

// ---------------------------------------------------------------------------
// Module-level mocks — must be declared before imports that consume them
// ---------------------------------------------------------------------------

// SimulationView uses useWorkspace + useAuth
vi.mock('../../../store/workspace.js', () => ({
  useWorkspace: () => ({
    projectId: null,
    currentFileId: null,
    editContent: vi.fn(),
    setState: vi.fn(),
  }),
}))

vi.mock('../../../store/auth.js', () => ({
  useAuth: () => ({ accessToken: null }),
}))

// WiringView uses api.runWireviz
vi.mock('../../../lib/api.js', () => ({
  api: {
    runWireviz: vi.fn().mockResolvedValue({ svg: null, warnings: [] }),
  },
}))

// FirmwareDebugPanel fetches on mount — stub fetch globally
const JTAG_SENTINEL = {
  ok: false,
  error: 'JTAG_LOCAL_ONLY',
  message: 'JTAG requires the local Kerf CLI',
  tasks: [],
  sync_objects: [],
  edges: [],
  warnings: [],
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: () => Promise.resolve(JTAG_SENTINEL),
  }))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

// ---------------------------------------------------------------------------
// Fragment under test
// ---------------------------------------------------------------------------

import ENTRIES from '../misc.js'

// ---------------------------------------------------------------------------
// Inline resolvePanelEntry — mirrors panelRegistry.js logic exactly
// ---------------------------------------------------------------------------

function resolvePanelEntry(file) {
  if (!file) return null
  const kind = String(file.kind || '').toLowerCase()
  const name = String(file.name || '').toLowerCase()
  for (const e of ENTRIES) {
    const kindHit = kind && (e.kinds || []).some((k) => String(k).toLowerCase() === kind)
    const extHit  = (e.exts  || []).some((x) => name.endsWith(String(x).toLowerCase()))
    if (kindHit || extHit) return e
  }
  return null
}

// ---------------------------------------------------------------------------
// Direct panel imports (static — no lazy() in tests)
// ---------------------------------------------------------------------------

import BIMPhasePanel       from '../../../components/BIMPhasePanel.jsx'
import CfdViewport         from '../../../components/CfdViewport.jsx'
import FirmwareDebugPanel  from '../../../components/FirmwareDebugPanel.jsx'
import KiCadRoundTripPanel from '../../../components/KiCadRoundTripPanel.jsx'
import LayoutViewer        from '../../../components/LayoutViewer.jsx'
import RFView              from '../../../components/RFView.jsx'
import SimulationView      from '../../../components/SimulationView.jsx'
import WiringView          from '../../../components/WiringView.jsx'

// Wrappers under test for mount tests
import BIMPhaseWrapper       from '../misc-wrappers/BIMPhaseWrapper.jsx'
import CfdViewportWrapper    from '../misc-wrappers/CfdViewportWrapper.jsx'
import FirmwareDebugWrapper  from '../misc-wrappers/FirmwareDebugWrapper.jsx'
import KiCadRoundTripWrapper from '../misc-wrappers/KiCadRoundTripWrapper.jsx'
import LayoutViewerWrapper   from '../misc-wrappers/LayoutViewerWrapper.jsx'
import RFViewWrapper         from '../misc-wrappers/RFViewWrapper.jsx'
import SimulationViewWrapper from '../misc-wrappers/SimulationViewWrapper.jsx'
import WiringViewWrapper     from '../misc-wrappers/WiringViewWrapper.jsx'

// ===========================================================================
// 1. Fragment structure
// ===========================================================================

describe('misc fragment — structure', () => {
  it('exports a non-empty array', () => {
    expect(Array.isArray(ENTRIES)).toBe(true)
    expect(ENTRIES.length).toBeGreaterThan(0)
  })

  it('contains exactly 8 entries', () => {
    expect(ENTRIES).toHaveLength(8)
  })

  it('every entry has id, kinds, exts, load, label', () => {
    for (const e of ENTRIES) {
      expect(typeof e.id, `${e.id}: id`).toBe('string')
      expect(Array.isArray(e.kinds), `${e.id}: kinds`).toBe(true)
      expect(e.kinds.length, `${e.id}: kinds non-empty`).toBeGreaterThan(0)
      expect(Array.isArray(e.exts), `${e.id}: exts`).toBe(true)
      expect(e.exts.length, `${e.id}: exts non-empty`).toBeGreaterThan(0)
      expect(typeof e.load, `${e.id}: load`).toBe('function')
      expect(typeof e.label, `${e.id}: label`).toBe('string')
    }
  })

  it('all ids are unique', () => {
    const ids = ENTRIES.map(e => e.id)
    expect(new Set(ids).size).toBe(ids.length)
  })
})

// ===========================================================================
// 2. resolvePanelEntry — kind-based resolution
// ===========================================================================

describe('resolvePanelEntry — kind resolution', () => {
  const cases = [
    ['bim_phase',            'bim_phase'],
    ['bim_renovation_phase', 'bim_phase'],
    ['cfd_viewport',         'cfd_viewport'],
    ['cfd_field',            'cfd_viewport'],
    ['firmware_debug',       'firmware_debug'],
    ['rtos_debug',           'firmware_debug'],
    ['kicad_roundtrip',      'kicad_roundtrip'],
    ['kicad_bridge',         'kicad_roundtrip'],
    ['ic_layout',            'ic_layout'],
    ['gds_layout',           'ic_layout'],
    ['rf_analysis',          'rf_analysis'],
    ['rf_result',            'rf_analysis'],
    ['s_param',              'rf_analysis'],
    ['simulation',           'simulation_view'],
    ['spice_simulation',     'simulation_view'],
    ['wiring',               'wiring_view'],
    ['wireviz_harness',      'wiring_view'],
  ]

  for (const [kind, expectedId] of cases) {
    it(`kind '${kind}' → entry id '${expectedId}'`, () => {
      const entry = resolvePanelEntry({ kind })
      expect(entry).not.toBeNull()
      expect(entry.id).toBe(expectedId)
    })
  }

  it('returns null for unknown kind', () => {
    expect(resolvePanelEntry({ kind: 'not_a_misc_kind_xyz' })).toBeNull()
  })
})

// ===========================================================================
// 3. resolvePanelEntry — extension-based resolution
// ===========================================================================

describe('resolvePanelEntry — extension resolution', () => {
  const cases = [
    ['phase.bimphase',           'bim_phase'],
    ['domain.cfdvp',             'cfd_viewport'],
    ['domain.cfdfield',          'cfd_viewport'],
    ['firmware.elfdbg',          'firmware_debug'],
    ['firmware.rtosdbg',         'firmware_debug'],
    ['board.kicadroundtrip',     'kicad_roundtrip'],
    ['board.kicadbridge',        'kicad_roundtrip'],
    ['chip.gds',                 'ic_layout'],
    ['chip.gdsii',               'ic_layout'],
    ['chip.gds2',                'ic_layout'],
    ['antenna.rfresult',         'rf_analysis'],
    ['antenna.sparam',           'rf_analysis'],
    ['circuit.simulation',       'simulation_view'],
    ['harness.wiring',           'wiring_view'],
  ]

  for (const [filename, expectedId] of cases) {
    it(`filename '${filename}' → entry id '${expectedId}'`, () => {
      const entry = resolvePanelEntry({ name: filename })
      expect(entry).not.toBeNull()
      expect(entry.id).toBe(expectedId)
    })
  }

  it('returns null for unknown extension', () => {
    expect(resolvePanelEntry({ name: 'file.totally_unknown_ext_xyz' })).toBeNull()
  })
})

// ===========================================================================
// 4. load() returns a Promise (dynamic import contract)
// ===========================================================================

describe('resolvePanelEntry — load() returns a thenable', () => {
  const kinds = [
    'bim_phase', 'cfd_viewport', 'firmware_debug', 'kicad_roundtrip',
    'ic_layout', 'rf_analysis', 'simulation', 'wiring',
  ]

  for (const kind of kinds) {
    it(`kind '${kind}' load() is a thenable`, () => {
      const entry = resolvePanelEntry({ kind })
      expect(entry).not.toBeNull()
      const result = entry.load()
      expect(typeof result.then).toBe('function')
    })
  }
})

// ===========================================================================
// 5. Panel + wrapper mount tests — renderToStaticMarkup
// ===========================================================================

// ── 5a. BIMPhasePanel / BIMPhaseWrapper ─────────────────────────────────────

describe('BIMPhasePanel — mount', () => {
  it('is a React function component', () => {
    expect(typeof BIMPhasePanel).toBe('function')
  })

  it('renders without crashing (no content)', () => {
    expect(() => renderToStaticMarkup(<BIMPhaseWrapper />)).not.toThrow()
  })

  it('renders with elementPhases JSON', () => {
    const content = JSON.stringify({
      elementPhases: [
        { element_id: 'wall-001', primary_phase: 'existing', demolish_phase: null },
        { element_id: 'col-002', primary_phase: 'new_construction', demolish_phase: null },
      ],
    })
    const html = renderToStaticMarkup(<BIMPhaseWrapper content={content} />)
    expect(html.length).toBeGreaterThan(0)
    expect(html).toMatch(/Phase|BIM|Tag|Filter/i)
  })

  it('gracefully ignores invalid JSON content', () => {
    expect(() =>
      renderToStaticMarkup(<BIMPhaseWrapper content="INVALID{{JSON" />)
    ).not.toThrow()
  })
})

// ── 5b. CfdViewport / CfdViewportWrapper ────────────────────────────────────

describe('CfdViewport — mount', () => {
  it('is a React function component', () => {
    expect(typeof CfdViewport).toBe('function')
  })

  it('renders without crashing (no content → no vectorField)', () => {
    const html = renderToStaticMarkup(<CfdViewportWrapper />)
    expect(html).toContain('canvas')
    expect(html).toContain('No CFD data')
  })

  it('renders with a grid vectorField from JSON content', () => {
    const nx = 4; const ny = 4
    const u = Array.from({ length: ny }, () => Array(nx).fill(1.0))
    const v = Array.from({ length: ny }, () => Array(nx).fill(0.0))
    const p = Array.from({ length: ny }, (_, row) =>
      Array.from({ length: nx }, (_, col) => col * 10 + row)
    )
    const content = JSON.stringify({ vectorField: { x0: 0, y0: 0, dx: 1, dy: 1, nx, ny, u, v, p } })
    const html = renderToStaticMarkup(<CfdViewportWrapper content={content} />)
    expect(html).toContain('canvas')
    // No placeholder when field is provided
    expect(html).not.toContain('No CFD data')
  })

  it('gracefully ignores invalid JSON content', () => {
    expect(() =>
      renderToStaticMarkup(<CfdViewportWrapper content="BAD{{{" />)
    ).not.toThrow()
  })
})

// ── 5c. FirmwareDebugPanel / FirmwareDebugWrapper ───────────────────────────
// FirmwareDebugPanel calls fetchDebugSnapshot() on mount (via useEffect, which
// is a no-op during SSR). renderToStaticMarkup is safe.

describe('FirmwareDebugPanel — mount', () => {
  it('is a React function component', () => {
    expect(typeof FirmwareDebugPanel).toBe('function')
  })

  it('renders without crashing (no content)', () => {
    expect(() => renderToStaticMarkup(<FirmwareDebugWrapper />)).not.toThrow()
  })

  it('renders with elfPath/target/rtos from JSON content', () => {
    const content = JSON.stringify({ elfPath: '/app/firmware.elf', target: 'stm32h7', rtos: 'freertos' })
    const html = renderToStaticMarkup(<FirmwareDebugWrapper content={content} />)
    expect(html.length).toBeGreaterThan(0)
    expect(html).toMatch(/RTOS|Debugger|Attach|Debug/i)
  })

  it('falls back to defaults for invalid JSON', () => {
    expect(() =>
      renderToStaticMarkup(<FirmwareDebugWrapper content="NOT_JSON" />)
    ).not.toThrow()
  })
})

// ── 5d. KiCadRoundTripPanel / KiCadRoundTripWrapper ─────────────────────────
// Uses useState/useCallback (no fetch on render). Safe for renderToStaticMarkup.

describe('KiCadRoundTripPanel — mount', () => {
  it('is a React function component', () => {
    expect(typeof KiCadRoundTripPanel).toBe('function')
  })

  it('renders without crashing (no content → empty circuitJson)', () => {
    expect(() => renderToStaticMarkup(<KiCadRoundTripWrapper />)).not.toThrow()
  })

  it('renders with circuitJson from content', () => {
    const content = JSON.stringify({
      circuitJson: [
        { id: 'C1', type: 'capacitor', value: '100nF' },
        { id: 'R1', type: 'resistor',  value: '10k' },
      ],
    })
    const html = renderToStaticMarkup(<KiCadRoundTripWrapper content={content} />)
    expect(html.length).toBeGreaterThan(0)
    expect(html).toMatch(/KiCad|Export|Import|Round/i)
  })

  it('ignores non-array circuitJson gracefully', () => {
    const content = JSON.stringify({ circuitJson: 'not-an-array' })
    expect(() => renderToStaticMarkup(<KiCadRoundTripWrapper content={content} />)).not.toThrow()
  })
})

// ── 5e. LayoutViewer / LayoutViewerWrapper ──────────────────────────────────
// Canvas draw is in useEffect (no-op in SSR). renderToStaticMarkup is safe.

describe('LayoutViewer — mount', () => {
  it('is a React function component', () => {
    expect(typeof LayoutViewer).toBe('function')
  })

  it('renders without crashing (no content → null layout)', () => {
    expect(() => renderToStaticMarkup(<LayoutViewerWrapper />)).not.toThrow()
  })

  it('renders with a layout tree from JSON content', () => {
    const content = JSON.stringify({
      pdk: 'sky130',
      layout: {
        topCell: 'inverter',
        cells: [
          {
            name: 'inverter',
            shapes: [
              { kind: 'box', layer: 65, x: 0, y: 0, w: 100, h: 200 },
              { kind: 'polygon', layer: 66, points: [{ x: 0, y: 0 }, { x: 100, y: 0 }, { x: 50, y: 100 }] },
            ],
          },
        ],
      },
    })
    const html = renderToStaticMarkup(<LayoutViewerWrapper content={content} />)
    expect(html.length).toBeGreaterThan(0)
    // LayoutViewer renders a toolbar and canvas
    expect(html).toMatch(/canvas|Fit|Layers/i)
  })

  it('gracefully ignores malformed layout JSON', () => {
    expect(() =>
      renderToStaticMarkup(<LayoutViewerWrapper content="{{BAD" />)
    ).not.toThrow()
  })
})

// ── 5f. RFView / RFViewWrapper ───────────────────────────────────────────────
// Uses useImperativeHandle (no-op in SSR). Safe for renderToStaticMarkup.

describe('RFView — mount', () => {
  it('is a React function component', () => {
    expect(typeof RFView).toBe('function')
  })

  it('renders without crashing (no content → queued status)', () => {
    expect(() => renderToStaticMarkup(<RFViewWrapper />)).not.toThrow()
  })

  it('renders in queued state with empty content', () => {
    const html = renderToStaticMarkup(<RFViewWrapper content="" />)
    expect(html).toMatch(/RF Analysis|Queued|queued|Run RF/i)
  })

  it('renders done state with result payload from content', () => {
    const content = JSON.stringify({
      status: 'done',
      result: {
        frequency_range: [1.0, 2.0, 3.0],
        vswr: [1.1, 1.2, 1.3],
        return_loss_db: [-25, -20, -15],
        insertion_loss_db: [0.1, 0.2, 0.3],
        stability_factor_k: [1.5, 1.6, 1.7],
        max_gain_db: [10, 9, 8],
        frequency_unit: 'GHz',
        warnings: [],
      },
    })
    const html = renderToStaticMarkup(<RFViewWrapper content={content} />)
    expect(html).toMatch(/RF Analysis|VSWR|Smith|Metrics/i)
  })
})

// ── 5g. SimulationView / SimulationViewWrapper ──────────────────────────────
// Uses useWorkspace + useAuth (mocked above). Safe for renderToStaticMarkup.

describe('SimulationView — mount', () => {
  it('is a React function component', () => {
    expect(typeof SimulationView).toBe('function')
  })

  it('renders without crashing (empty content)', () => {
    expect(() => renderToStaticMarkup(<SimulationViewWrapper content="" />)).not.toThrow()
  })

  it('renders a transient simulation spec from JSON content', () => {
    const content = JSON.stringify({
      version: 1,
      circuit_file_id: 'aaaaaaaa-0000-0000-0000-000000000001',
      analysis: { type: 'transient', tstep: '1us', tstop: '10ms' },
      probes: [{ name: 'VOUT', kind: 'V' }],
      results: { waveforms: [], warnings: [], errors: [] },
    })
    const html = renderToStaticMarkup(<SimulationViewWrapper content={content} />)
    expect(html.length).toBeGreaterThan(0)
    expect(html).toMatch(/Simulation|transient|VOUT|Run/i)
  })

  it('renders an invalid file without crashing (shows unsupported message)', () => {
    const html = renderToStaticMarkup(<SimulationViewWrapper content="not valid json" />)
    expect(html).toMatch(/Unsupported|unsupported|invalid/i)
  })

  it('passes fileName from file prop', () => {
    const html = renderToStaticMarkup(
      <SimulationViewWrapper
        content=""
        file={{ name: 'my-circuit.simulation' }}
      />
    )
    expect(html).toMatch(/Simulation/i)
  })
})

// ── 5h. WiringView / WiringViewWrapper ──────────────────────────────────────
// api.runWireviz is mocked. useEffect is no-op in SSR. Safe for renderToStaticMarkup.

describe('WiringView — mount', () => {
  it('is a React function component', () => {
    expect(typeof WiringView).toBe('function')
  })

  it('renders without crashing (no content)', () => {
    expect(() => renderToStaticMarkup(<WiringViewWrapper />)).not.toThrow()
  })

  it('renders with YAML source from content', () => {
    const yaml = `
connectors:
  CON1:
    pincount: 2
    pins: [1, 2]
cables:
  W1:
    gauge: 0.5 mm²
    wirecount: 2
connections:
  - from: CON1:1
    via: W1:1
    to: CON2:1
`
    const html = renderToStaticMarkup(
      <WiringViewWrapper content={yaml} projectId="proj-1" fileId="file-1" />
    )
    // WiringView shows loading/placeholder while API runs (useEffect no-op in SSR)
    expect(html.length).toBeGreaterThan(0)
  })

  it('renders empty-content placeholder without crashing', () => {
    const html = renderToStaticMarkup(
      <WiringViewWrapper content="" projectId="proj-1" fileId="file-1" />
    )
    expect(html.length).toBeGreaterThan(0)
  })
})
