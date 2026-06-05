// mfg.test.jsx — tests for the mfg panel registry fragment.
//
// Strategy:
//   1. Import the mfg fragment directly to verify all entries are present
//      and well-formed (id, kinds/exts, load function).
//   2. Import resolvePanelEntry from panelRegistry.js and confirm that each
//      registered kind resolves to a non-null entry — this exercises the
//      glob collection path end-to-end in the vitest environment.
//   3. Mount ≥2 panels with sample `content` props using renderToStaticMarkup
//      (no @testing-library/react, no browser DOM, no live fetch).

import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

// ── fragment ──────────────────────────────────────────────────────────────
import mfgEntries from '../mfg.js'

// ── registry (for resolvePanelEntry) ──────────────────────────────────────
// panelRegistry is at src/lib/panelRegistry.js; the test is at
// src/lib/panels/__tests__/mfg.test.jsx — three levels up.
import { resolvePanelEntry } from '../../panelRegistry.js'

// ── panels under test (direct imports for mount tests) ───────────────────
import InjectionFillPanel   from '../../../components/InjectionFillPanel.jsx'
import QuantitySchedulePanel from '../../../components/QuantitySchedulePanel.jsx'
import MoldCoolingWarpagePanel from '../../../components/MoldCoolingWarpagePanel.jsx'
import PartingCavityPanel   from '../../../components/PartingCavityPanel.jsx'

// ---------------------------------------------------------------------------
// 1. Fragment shape — all 12 entries must be present
// ---------------------------------------------------------------------------

const EXPECTED_IDS = [
  'cam_verify',
  'cam_machine_sim',
  'injection_fill',
  'parting_cavity',
  'mold_cooling_warpage',
  'packaging_prepress',
  'packaging_material_yield',
  'quote_to_delivery',
  'quantity_schedule',
  'geometry_import',
  'drawing_sheet',
  'gdnt_pmi',
]

describe('mfg fragment — structure', () => {
  it('exports an array', () => {
    expect(Array.isArray(mfgEntries)).toBe(true)
  })

  it(`has exactly ${EXPECTED_IDS.length} entries`, () => {
    expect(mfgEntries).toHaveLength(EXPECTED_IDS.length)
  })

  it.each(EXPECTED_IDS)('entry %s exists', (id) => {
    const entry = mfgEntries.find((e) => e.id === id)
    expect(entry).toBeDefined()
  })

  it.each(EXPECTED_IDS)('entry %s has a load function', (id) => {
    const entry = mfgEntries.find((e) => e.id === id)
    expect(typeof entry.load).toBe('function')
  })

  it.each(EXPECTED_IDS)('entry %s has kinds or exts', (id) => {
    const entry = mfgEntries.find((e) => e.id === id)
    const hasKinds = Array.isArray(entry.kinds) && entry.kinds.length > 0
    const hasExts  = Array.isArray(entry.exts)  && entry.exts.length > 0
    expect(hasKinds || hasExts).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// 2. Registry resolution — resolvePanelEntry must return a non-null entry
//    for each registered kind.
// ---------------------------------------------------------------------------

const KIND_SAMPLES = [
  ['cam_verify',             'cam_verify'],
  ['cam_machine_sim',        'cam_machine_sim'],
  ['injection_fill',         'injection_fill'],
  ['parting_cavity',         'parting_cavity'],
  ['mold_cooling_warpage',   'mold_cooling'],
  ['packaging_prepress',     'packaging_prepress'],
  ['packaging_material_yield','packaging_yield'],
  ['quote_to_delivery',      'quote_to_delivery'],
  ['quantity_schedule',      'quantity_schedule'],
  ['geometry_import',        'geometry_import'],
  ['drawing_sheet',          'drawing_sheet'],
  ['gdnt_pmi',               'gdnt_pmi'],
]

describe('resolvePanelEntry — kind lookup', () => {
  it.each(KIND_SAMPLES)('entry %s resolves for kind "%s"', (id, kind) => {
    const result = resolvePanelEntry({ kind })
    expect(result).not.toBeNull()
    expect(result.id).toBe(id)
  })
})

describe('resolvePanelEntry — extension lookup', () => {
  it('resolves .qty_schedule extension', () => {
    const result = resolvePanelEntry({ name: 'floor.qty_schedule' })
    expect(result).not.toBeNull()
    expect(result.id).toBe('quantity_schedule')
  })

  it('resolves .step extension', () => {
    const result = resolvePanelEntry({ name: 'bracket.step' })
    expect(result).not.toBeNull()
    expect(result.id).toBe('geometry_import')
  })

  it('resolves .iges extension', () => {
    const result = resolvePanelEntry({ name: 'hull.iges' })
    expect(result).not.toBeNull()
    expect(result.id).toBe('geometry_import')
  })

  it('resolves .stp extension', () => {
    const result = resolvePanelEntry({ name: 'body.stp' })
    expect(result).not.toBeNull()
    expect(result.id).toBe('geometry_import')
  })

  it('resolves .fill_result extension', () => {
    const result = resolvePanelEntry({ name: 'part.fill_result' })
    expect(result).not.toBeNull()
    expect(result.id).toBe('injection_fill')
  })

  it('resolves .drawing extension', () => {
    const result = resolvePanelEntry({ name: 'assembly.drawing' })
    expect(result).not.toBeNull()
    expect(result.id).toBe('drawing_sheet')
  })

  it('resolves .gdnt extension', () => {
    const result = resolvePanelEntry({ name: 'shaft.gdnt' })
    expect(result).not.toBeNull()
    expect(result.id).toBe('gdnt_pmi')
  })

  it('returns null for unknown kind', () => {
    expect(resolvePanelEntry({ kind: 'unknown_xyz_panel' })).toBeNull()
  })

  it('returns null for null input', () => {
    expect(resolvePanelEntry(null)).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// 3. Mount tests — ≥2 panels with sample content via renderToStaticMarkup
// ---------------------------------------------------------------------------

// InjectionFillPanel — accepts parsedContent (or content via mfg.js wrapper,
// but we test the component directly here with parsedContent).
const INJECTION_FILL_SAMPLE = JSON.stringify({
  fill_time_s: 1.82,
  max_pressure_drop_mpa: 37.4,
  weld_line_count: 1,
  weld_lines: [[ {x: 50, y: 30}, {x: 60, y: 35} ]],
  air_trap_count: 0,
  air_traps: [],
  last_to_fill_count: 4,
  short_shot_risk_pct: 3.2,
  polymer: 'ABS_Cycolac_T',
  honest_caveat: 'SIMPLIFIED 1.5D model — commercial Moldflow/Sigmasoft required.',
})

describe('InjectionFillPanel — mount with sample content', () => {
  it('renders without throwing', () => {
    const html = renderToStaticMarkup(
      <InjectionFillPanel parsedContent={INJECTION_FILL_SAMPLE} />
    )
    expect(html.length).toBeGreaterThan(0)
  })

  it('shows polymer tag', () => {
    const html = renderToStaticMarkup(
      <InjectionFillPanel parsedContent={INJECTION_FILL_SAMPLE} />
    )
    expect(html).toContain('ABS_Cycolac_T')
  })

  it('shows fill time value', () => {
    const html = renderToStaticMarkup(
      <InjectionFillPanel parsedContent={INJECTION_FILL_SAMPLE} />
    )
    expect(html).toContain('1.820')
  })

  it('shows weld line count', () => {
    const html = renderToStaticMarkup(
      <InjectionFillPanel parsedContent={INJECTION_FILL_SAMPLE} />
    )
    // weld_line_count = 1 appears as the metric value
    expect(html).toContain('Weld lines')
  })

  it('renders empty state for empty content', () => {
    const html = renderToStaticMarkup(
      <InjectionFillPanel parsedContent="" />
    )
    expect(html).toContain('No fill simulation result')
  })

  it('renders error state for invalid JSON', () => {
    const html = renderToStaticMarkup(
      <InjectionFillPanel parsedContent="{bad json}" />
    )
    expect(html).toContain('Could not parse')
  })
})

// QuantitySchedulePanel — already accepts `content` natively (no wrapper).
const QTY_SCHEDULE_SAMPLE = JSON.stringify({
  result: {
    ok: true,
    by_category: [
      { category: 'Wall', element_count: 2, total_area_m2: 40.0, total_volume_m3: 12.0 },
    ],
    by_material: [
      { material: 'Concrete', element_count: 2, total_volume_m3: 12.0 },
    ],
    element_lines: [],
    warnings: [],
  },
})

describe('QuantitySchedulePanel — mount with sample content', () => {
  it('renders without throwing', () => {
    const html = renderToStaticMarkup(
      <QuantitySchedulePanel content={QTY_SCHEDULE_SAMPLE} />
    )
    expect(html.length).toBeGreaterThan(0)
  })

  it('has quantity-schedule-panel testid', () => {
    const html = renderToStaticMarkup(
      <QuantitySchedulePanel content={QTY_SCHEDULE_SAMPLE} />
    )
    expect(html).toContain('data-testid="quantity-schedule-panel"')
  })

  it('shows Wall category row', () => {
    const html = renderToStaticMarkup(
      <QuantitySchedulePanel content={QTY_SCHEDULE_SAMPLE} />
    )
    expect(html).toContain('data-testid="qty-cat-row-Wall"')
  })

  it('shows Concrete material row', () => {
    const html = renderToStaticMarkup(
      <QuantitySchedulePanel content={QTY_SCHEDULE_SAMPLE} />
    )
    expect(html).toContain('data-testid="qty-mat-row-Concrete"')
  })
})

// MoldCoolingWarpagePanel — accepts parsedContent.
const COOLING_SAMPLE = JSON.stringify({
  htc_w_m2_k: 4200,
  reynolds: 15000,
  cooling_time_s: 8.3,
  coolant_temp_rise_c: 1.2,
  flow_regime: 'turbulent',
  honest_caveat: 'Dittus-Boelter Re>10 000 — laminar requires different correlation.',
})

describe('MoldCoolingWarpagePanel — mount with sample content', () => {
  it('renders without throwing', () => {
    const html = renderToStaticMarkup(
      <MoldCoolingWarpagePanel parsedContent={COOLING_SAMPLE} />
    )
    expect(html.length).toBeGreaterThan(0)
  })

  it('shows HTC value', () => {
    const html = renderToStaticMarkup(
      <MoldCoolingWarpagePanel parsedContent={COOLING_SAMPLE} />
    )
    expect(html).toContain('HTC')
  })

  it('shows turbulent regime badge', () => {
    const html = renderToStaticMarkup(
      <MoldCoolingWarpagePanel parsedContent={COOLING_SAMPLE} />
    )
    // CoolingView renders "Turbulent (Dittus-Boelter valid)" badge
    expect(html).toContain('Turbulent')
  })

  it('renders empty state for blank content', () => {
    const html = renderToStaticMarkup(
      <MoldCoolingWarpagePanel parsedContent="" />
    )
    expect(html).toContain('No mold analysis result')
  })
})

// PartingCavityPanel — accepts parsedContent.
const PARTING_LINE_SAMPLE = JSON.stringify({
  ok: true,
  segments: [
    { edge_id: 'E1', classification: 'silhouette', length_mm: 45.0 },
    { edge_id: 'E2', classification: 'undercut_boundary', length_mm: 12.5 },
  ],
  total_length_mm: 57.5,
  closed_loops: 1,
  has_undercuts: true,
  undercut_face_ids: ['F3'],
  draft_deficient_face_ids: [],
  honest_caveat: 'Silhouette detection is projection-based.',
})

describe('PartingCavityPanel — mount with sample content', () => {
  it('renders without throwing', () => {
    const html = renderToStaticMarkup(
      <PartingCavityPanel parsedContent={PARTING_LINE_SAMPLE} />
    )
    expect(html.length).toBeGreaterThan(0)
  })

  it('shows Parting-Line Detection header', () => {
    const html = renderToStaticMarkup(
      <PartingCavityPanel parsedContent={PARTING_LINE_SAMPLE} />
    )
    expect(html).toContain('Parting-Line Detection')
  })

  it('shows parting length metric', () => {
    const html = renderToStaticMarkup(
      <PartingCavityPanel parsedContent={PARTING_LINE_SAMPLE} />
    )
    expect(html).toContain('Parting length')
  })

  it('renders empty state for blank content', () => {
    const html = renderToStaticMarkup(
      <PartingCavityPanel parsedContent="" />
    )
    expect(html).toContain('No parting-line result')
  })
})
