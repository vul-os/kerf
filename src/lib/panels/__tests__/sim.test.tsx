/**
 * sim.test.jsx
 *
 * Tests for the sim panel registry fragment (src/lib/panels/sim.js).
 *
 * Strategy
 * --------
 * 1. Import the sim fragment directly (plain ES module — no import.meta.glob).
 * 2. Build a local resolvePanelEntry() from the fragment entries so we can
 *    assert each kind/ext resolves to the correct panel entry without
 *    needing a browser Vite environment.
 * 3. Mount ≥2 wrapper components with sample content using
 *    renderToStaticMarkup (no jsdom / DOM required).
 */
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import simEntries from '../sim.js'

// ---------------------------------------------------------------------------
// Local resolve helper (mirrors panelRegistry.resolvePanelEntry logic)
// ---------------------------------------------------------------------------

function resolvePanelEntry(file) {
  if (!file) return null
  const kind = String(file.kind || '').toLowerCase()
  const name = String(file.name || '').toLowerCase()
  for (const e of simEntries) {
    const kindHit = kind && (e.kinds || []).some((k) => String(k).toLowerCase() === kind)
    const extHit = (e.exts || []).some((x) => name.endsWith(String(x).toLowerCase()))
    if (kindHit || extHit) return e
  }
  return null
}

// ---------------------------------------------------------------------------
// 1. Fragment shape
// ---------------------------------------------------------------------------

describe('sim fragment — structure', () => {
  it('exports a non-empty array', () => {
    expect(Array.isArray(simEntries)).toBe(true)
    expect(simEntries.length).toBeGreaterThan(0)
  })

  it('every entry has id, kinds|exts, load, label', () => {
    for (const e of simEntries) {
      expect(typeof e.id).toBe('string')
      expect(e.id.length).toBeGreaterThan(0)
      const hasMatcher = (e.kinds && e.kinds.length > 0) || (e.exts && e.exts.length > 0)
      expect(hasMatcher).toBe(true)
      expect(typeof e.load).toBe('function')
      expect(typeof e.label).toBe('string')
    }
  })

  it('all ids are unique', () => {
    const ids = simEntries.map((e) => e.id)
    const unique = new Set(ids)
    expect(unique.size).toBe(ids.length)
  })
})

// ---------------------------------------------------------------------------
// 2. resolvePanelEntry — kind-based resolution for every panel
// ---------------------------------------------------------------------------

const KIND_CASES = [
  // Energy
  { id: 'building-energy-export', kind: 'building_energy_export' },
  { id: 'building-energy-export', kind: 'be_export' },
  { id: 'heat-exchanger',         kind: 'heat_exchanger' },
  { id: 'heat-exchanger',         kind: 'hx_design' },
  { id: 'hourly-8760',            kind: 'hourly_8760' },
  { id: 'hourly-8760',            kind: 'building_energy_8760' },
  { id: 'thermo-cycle',           kind: 'thermo_cycle' },
  { id: 'thermo-cycle',           kind: 'thermodynamic_cycle' },
  // Optics
  { id: 'daylighting',            kind: 'daylighting' },
  { id: 'daylighting',            kind: 'daylighting_sim' },
  { id: 'lighting-sim',           kind: 'lighting_sim' },
  { id: 'lighting-sim',           kind: 'photometric_sim' },
  { id: 'sequential-trace',       kind: 'sequential_trace' },
  { id: 'sequential-trace',       kind: 'ray_trace' },
  // Acoustics
  { id: 'acoustics-result',       kind: 'acoustics_result' },
  { id: 'acoustics-result',       kind: 'acoustics_sim' },
  // Solar PV
  { id: 'solar-pv',               kind: 'solar_pv' },
  { id: 'solar-pv',               kind: 'pv_iv' },
  // Controls
  { id: 'controls',               kind: 'controls_result' },
  { id: 'controls',               kind: 'controls_analysis' },
  // Materials
  { id: 'ashby-chart',            kind: 'ashby_chart' },
  { id: 'ashby-chart',            kind: 'material_chart' },
  { id: 'lca-results',            kind: 'lca_result' },
  { id: 'lca-results',            kind: 'lca_report' },
  // Thermal
  { id: 'thermal-network',        kind: 'thermal_network' },
  { id: 'thermal-network',        kind: 'thermal_net' },
  // CFD
  { id: 'cfd-results',            kind: 'cfd_result' },
  { id: 'cfd-results',            kind: 'cfd_post' },
]

describe('resolvePanelEntry — kind matching', () => {
  for (const { id, kind } of KIND_CASES) {
    it(`kind "${kind}" → entry id "${id}"`, () => {
      const entry = resolvePanelEntry({ kind })
      expect(entry).not.toBeNull()
      expect(entry.id).toBe(id)
    })
  }
})

// ---------------------------------------------------------------------------
// 3. resolvePanelEntry — extension-based resolution
// ---------------------------------------------------------------------------

const EXT_CASES = [
  { id: 'building-energy-export', name: 'building.gbxml' },
  { id: 'building-energy-export', name: 'building.idf' },
  { id: 'heat-exchanger',         name: 'design.hxdesign' },
  { id: 'hourly-8760',            name: 'sim.8760' },
  { id: 'thermo-cycle',           name: 'engine.thermocycle' },
  { id: 'daylighting',            name: 'office.daylight' },
  { id: 'lighting-sim',           name: 'room.lightsim' },
  { id: 'sequential-trace',       name: 'lens.raytrace' },
  { id: 'acoustics-result',       name: 'hall.acoustics' },
  { id: 'solar-pv',               name: 'array.pvresult' },
  { id: 'controls',               name: 'loop.bode' },
  { id: 'ashby-chart',            name: 'chart.ashby' },
  { id: 'lca-results',            name: 'part.lcaresult' },
  { id: 'thermal-network',        name: 'system.thermalnet' },
  { id: 'cfd-results',            name: 'domain.cfdresult' },
]

describe('resolvePanelEntry — extension matching', () => {
  for (const { id, name } of EXT_CASES) {
    it(`file "${name}" → entry id "${id}"`, () => {
      const entry = resolvePanelEntry({ name })
      expect(entry).not.toBeNull()
      expect(entry.id).toBe(id)
    })
  }
})

// ---------------------------------------------------------------------------
// 4. Unmatched file returns null
// ---------------------------------------------------------------------------

describe('resolvePanelEntry — no match', () => {
  it('returns null for unknown kind', () => {
    expect(resolvePanelEntry({ kind: 'unknown_xyz_kind' })).toBeNull()
  })

  it('returns null for unknown extension', () => {
    expect(resolvePanelEntry({ name: 'file.unknown123' })).toBeNull()
  })

  it('returns null for null input', () => {
    expect(resolvePanelEntry(null)).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// 5. Panel mount tests — ≥2 wrapper components with sample content
// ---------------------------------------------------------------------------

// Import wrappers directly (they are the default export of each wrapper module)
import SolarPVWrapper     from '../sim-wrappers/SolarPVWrapper.jsx'
import ControlsWrapper    from '../sim-wrappers/ControlsWrapper.jsx'
import AshbyChartWrapper  from '../sim-wrappers/AshbyChartWrapper.jsx'
import LCAResultsWrapper  from '../sim-wrappers/LCAResultsWrapper.jsx'
import ThermalNetworkWrapper from '../sim-wrappers/ThermalNetworkWrapper.jsx'
import CfdResultsWrapper  from '../sim-wrappers/CfdResultsWrapper.jsx'
import AcousticsWrapper   from '../sim-wrappers/AcousticsWrapper.jsx'

describe('Wrapper mount — renderToStaticMarkup', () => {
  // ── SolarPVWrapper ────────────────────────────────────────────────────────
  it('SolarPVWrapper mounts with null content (default empty state)', () => {
    expect(() => renderToStaticMarkup(<SolarPVWrapper content={null} />)).not.toThrow()
  })

  it('SolarPVWrapper mounts with valid IV data JSON', () => {
    const ivData = {
      iv_curve: [
        { v: 0, i: 9.0, p: 0 },
        { v: 18, i: 8.0, p: 144 },
        { v: 36, i: 0, p: 0 },
      ],
      isc_a: 9.0,
      voc_v: 36.0,
      mpp: { p_w: 245, v_v: 29.0, i_a: 8.4 },
    }
    const content = JSON.stringify({ ivData, title: 'Test Panel' })
    const html = renderToStaticMarkup(<SolarPVWrapper content={content} />)
    expect(html).toContain('Test Panel')
  })

  it('SolarPVWrapper ignores malformed JSON', () => {
    expect(() =>
      renderToStaticMarkup(<SolarPVWrapper content="NOT_VALID_JSON{{{" />)
    ).not.toThrow()
  })

  // ── ControlsWrapper ───────────────────────────────────────────────────────
  it('ControlsWrapper mounts with empty content (null data — shows empty tabs)', () => {
    expect(() => renderToStaticMarkup(<ControlsWrapper content={null} />)).not.toThrow()
  })

  it('ControlsWrapper renders Bode tab by default', () => {
    const html = renderToStaticMarkup(<ControlsWrapper content={null} />)
    expect(html).toMatch(/[Bb]ode/)
  })

  it('ControlsWrapper accepts content with partial bode data', () => {
    const content = JSON.stringify({
      bode: {
        omega: [1, 10, 100],
        mag_db: [0, -20, -40],
        phase_deg: [0, -45, -90],
        gain_margin_db: 10,
        phase_margin_deg: 45,
      },
    })
    expect(() => renderToStaticMarkup(<ControlsWrapper content={content} />)).not.toThrow()
  })

  // ── AshbyChartWrapper ─────────────────────────────────────────────────────
  it('AshbyChartWrapper mounts with empty content (no points — shows empty state)', () => {
    expect(() => renderToStaticMarkup(<AshbyChartWrapper content={null} />)).not.toThrow()
  })

  it('AshbyChartWrapper renders with sample material points', () => {
    const content = JSON.stringify({
      points: [
        { name: 'Steel', x: 200, y: 400, family: 'steel' },
        { name: 'Al', x: 70, y: 300, family: 'aluminium' },
      ],
      xLabel: 'E (GPa)',
      yLabel: 'σy (MPa)',
      title: 'Stiffness vs Strength',
    })
    const html = renderToStaticMarkup(<AshbyChartWrapper content={content} />)
    expect(html).toContain('Stiffness vs Strength')
  })

  // ── LCAResultsWrapper ─────────────────────────────────────────────────────
  it('LCAResultsWrapper mounts with no result (shows empty-state prompt)', () => {
    const html = renderToStaticMarkup(<LCAResultsWrapper content={null} />)
    expect(html).toMatch(/lca_report|No LCA/i)
  })

  it('LCAResultsWrapper mounts with a minimal result payload', () => {
    const content = JSON.stringify({
      result: {
        total_carbon_kg_co2: 120,
        functional_unit: '1 unit',
        phase_breakdown: {},
        materials: [],
        warnings: [],
      },
    })
    const html = renderToStaticMarkup(<LCAResultsWrapper content={content} />)
    expect(html).toContain('120')
  })

  // ── ThermalNetworkWrapper ─────────────────────────────────────────────────
  it('ThermalNetworkWrapper mounts with empty network', () => {
    expect(() => renderToStaticMarkup(<ThermalNetworkWrapper content={null} />)).not.toThrow()
  })

  it('ThermalNetworkWrapper mounts with a simple 2-node network', () => {
    const content = JSON.stringify({
      network: {
        nodes: [
          { id: 'n1', label: 'Source', temperature_K: 373 },
          { id: 'n2', label: 'Sink',   temperature_K: 293 },
        ],
        links: [
          { from_id: 'n1', to_id: 'n2', type: 'conductive', flux_W: 10 },
        ],
      },
    })
    const html = renderToStaticMarkup(<ThermalNetworkWrapper content={content} />)
    expect(html).toMatch(/<svg\b/)
  })

  // ── CfdResultsWrapper ─────────────────────────────────────────────────────
  it('CfdResultsWrapper mounts with no data', () => {
    const html = renderToStaticMarkup(<CfdResultsWrapper content={null} />)
    // Panel renders an empty container when no data present
    expect(html).toBeTruthy()
    expect(html.length).toBeGreaterThan(0)
  })

  it('CfdResultsWrapper mounts with field stats content', () => {
    const content = JSON.stringify({
      fieldStats: {
        U: { min_mag: 0, max_mag: 10, mean_mag: 5, n_cells: 100000 },
        p: { min_mag: -10, max_mag: 10, mean_mag: 0, n_cells: 100000 },
      },
      turbulenceModel: 'kOmegaSST',
      converged: true,
      n_cells: 100000,
    })
    const html = renderToStaticMarkup(<CfdResultsWrapper content={content} />)
    expect(html).toContain('kOmegaSST')
  })

  // ── AcousticsWrapper ──────────────────────────────────────────────────────
  it('AcousticsWrapper mounts (standalone panel — no content needed)', () => {
    const html = renderToStaticMarkup(<AcousticsWrapper />)
    expect(html.length).toBeGreaterThan(0)
  })
})
