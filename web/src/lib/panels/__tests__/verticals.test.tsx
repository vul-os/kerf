/**
 * verticals.test.jsx — Registry integration tests for the verticals panel
 * fragment (textiles / dental / jewelry / horology / microfluidics /
 * electronics).
 *
 * Strategy
 * --------
 * Tier 1 — Fragment structure (no DOM).
 *   Verify every entry in verticals.js has id, kinds[], exts[], load().
 *   Build a minimal resolvePanelEntry equivalent directly from the fragment
 *   (avoids mocking import.meta.glob inside panelRegistry.js).
 *
 * Tier 2 — resolvePanelEntry behaviour.
 *   Confirm each registered kind resolves to its entry id.
 *
 * Tier 3 — Panel mount smoke tests (≥2 panels).
 *   Mount TextilesWeaveKnitPanel and GarmentDrapePanel with sample content
 *   via renderToStaticMarkup; assert key data-testid landmarks are present.
 *
 * Panels that own live API calls (dental, horology, microfluidics, VIBench)
 * are not mounted here — they initiate fetch on button click, not on render,
 * so they would work too, but we stick to the purely display panels for a
 * fast, deterministic test suite.
 */

import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import React from 'react'

// ── Silence lucide-react SVG in SSR (no JSDOM needed) ──────────────────────
// lucide-react renders fine in renderToStaticMarkup; no mock needed.

// ── Import the fragment directly ────────────────────────────────────────────
import ENTRIES from '../verticals.js'

// ── Minimal resolvePanelEntry built from the fragment (mirrors panelRegistry) ──
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

// ── Tier 1: Fragment structure ───────────────────────────────────────────────

describe('verticals fragment — structure', () => {
  it('exports a non-empty array', () => {
    expect(Array.isArray(ENTRIES)).toBe(true)
    expect(ENTRIES.length).toBeGreaterThan(0)
  })

  it('every entry has a string id', () => {
    for (const e of ENTRIES) {
      expect(typeof e.id).toBe('string')
      expect(e.id.length).toBeGreaterThan(0)
    }
  })

  it('every entry has a non-empty kinds array', () => {
    for (const e of ENTRIES) {
      expect(Array.isArray(e.kinds)).toBe(true)
      expect(e.kinds.length).toBeGreaterThan(0)
    }
  })

  it('every entry has a non-empty exts array', () => {
    for (const e of ENTRIES) {
      expect(Array.isArray(e.exts)).toBe(true)
      expect(e.exts.length).toBeGreaterThan(0)
    }
  })

  it('every entry has a load function', () => {
    for (const e of ENTRIES) {
      expect(typeof e.load).toBe('function')
    }
  })

  it('ids are unique', () => {
    const ids = ENTRIES.map((e) => e.id)
    expect(new Set(ids).size).toBe(ids.length)
  })
})

// ── Tier 2: resolvePanelEntry by kind ───────────────────────────────────────

describe('resolvePanelEntry — resolves each registered kind', () => {
  const EXPECTED = [
    // TEXTILES
    { kind: 'apparel_grade',       expectedId: 'apparel_grade' },
    { kind: 'textiles_weaveknit',  expectedId: 'textiles_weaveknit' },
    { kind: 'textiles_etextiles',  expectedId: 'textiles_etextiles' },
    { kind: 'garment_avatar',      expectedId: 'garment_avatar' },
    { kind: 'garment_drape',       expectedId: 'garment_drape' },
    // DENTAL
    { kind: 'dental_crown_bridge', expectedId: 'dental_crown_bridge' },
    { kind: 'dental_implant',      expectedId: 'dental_implant' },
    { kind: 'dental_intraoral',    expectedId: 'dental_intraoral' },
    { kind: 'dental_rpd',          expectedId: 'dental_rpd' },
    // JEWELRY
    { kind: 'jewelry_configurator', expectedId: 'jewelry_configurator' },
    // HOROLOGY
    { kind: 'horology_watch',      expectedId: 'horology_watch' },
    // MICROFLUIDICS
    { kind: 'microfluidics_device', expectedId: 'microfluidics_device' },
    // ELECTRONICS
    { kind: 'electronics_vi_bench', expectedId: 'electronics_vi_bench' },
  ]

  for (const { kind, expectedId } of EXPECTED) {
    it(`kind "${kind}" resolves to entry "${expectedId}"`, () => {
      const entry = resolvePanelEntry({ kind })
      expect(entry).not.toBeNull()
      expect(entry?.id).toBe(expectedId)
    })
  }

  it('unknown kind returns null', () => {
    expect(resolvePanelEntry({ kind: 'does_not_exist' })).toBeNull()
  })

  it('null file returns null', () => {
    expect(resolvePanelEntry(null)).toBeNull()
  })
})

// ── Tier 2b: resolve by extension ───────────────────────────────────────────

describe('resolvePanelEntry — resolves by file extension', () => {
  it('resolves .weaveknit extension', () => {
    const entry = resolvePanelEntry({ name: 'my-fabric.weaveknit' })
    expect(entry?.id).toBe('textiles_weaveknit')
  })

  it('resolves .horology extension', () => {
    const entry = resolvePanelEntry({ name: 'movement.horology' })
    expect(entry?.id).toBe('horology_watch')
  })

  it('resolves .vibench extension', () => {
    const entry = resolvePanelEntry({ name: 'bench.vibench' })
    expect(entry?.id).toBe('electronics_vi_bench')
  })
})

// ── Tier 3: Panel mount smoke tests ─────────────────────────────────────────
// Mount two display panels (no API calls on render).

// Pass through actual lucide-react so named exports work in SSR
vi.mock('lucide-react', async (importOriginal) => {
  return await importOriginal()
})

describe('TextilesWeaveKnitPanel — mount with empty content', () => {
  it('renders empty-state testid when no result provided', async () => {
    const { default: TextilesWeaveKnitPanel } = await import(
      '../../../components/TextilesWeaveKnitPanel.jsx'
    )
    const html = renderToStaticMarkup(
      React.createElement(TextilesWeaveKnitPanel, {})
    )
    expect(html).toContain('data-testid="textiles-panel-empty"')
  })

  it('renders with content string (invalid JSON → empty state)', async () => {
    const { default: TextilesWeaveKnitPanel } = await import(
      '../../../components/TextilesWeaveKnitPanel.jsx'
    )
    const html = renderToStaticMarkup(
      React.createElement(TextilesWeaveKnitPanel, { content: 'not-json' })
    )
    // Invalid JSON falls back to result=null → empty state
    expect(html).toContain('data-testid="textiles-panel-empty"')
  })

  it('renders with valid weave content (content string)', async () => {
    const { default: TextilesWeaveKnitPanel } = await import(
      '../../../components/TextilesWeaveKnitPanel.jsx'
    )
    const sampleContent = JSON.stringify({
      name: 'plain_weave',
      float_stats: { warp_mean_float: 1.0, weft_mean_float: 1.0, max_float: 1 },
      analytic_warp_mean_float: 1.0,
      analytic_weft_mean_float: 1.0,
    })
    const html = renderToStaticMarkup(
      React.createElement(TextilesWeaveKnitPanel, { content: sampleContent })
    )
    expect(html).toContain('data-testid="textiles-weave-knit-panel"')
    expect(html).toContain('data-testid="weave-stats"')
    expect(html).toContain('data-testid="textiles-structure-name"')
  })
})

describe('GarmentDrapePanel — mount with empty content', () => {
  it('renders empty-state testid when no result provided', async () => {
    const { default: GarmentDrapePanel } = await import(
      '../../../components/GarmentDrapePanel.jsx'
    )
    const html = renderToStaticMarkup(
      React.createElement(GarmentDrapePanel, {})
    )
    expect(html).toContain('data-testid="drape-panel-empty"')
  })

  it('renders with content string carrying valid drape result', async () => {
    const { default: GarmentDrapePanel } = await import(
      '../../../components/GarmentDrapePanel.jsx'
    )
    // Minimal valid drape result matching parseDrapeResult requirements
    const fitTension = Array.from({ length: 100 }, (_, i) => (i % 10) * 0.002 - 0.01)
    const sampleContent = JSON.stringify({
      ok: true,
      target_region: 'torso',
      panel_rows: 10,
      panel_cols: 10,
      converged: true,
      steps_taken: 500,
      max_penetration_cm: 0.05,
      no_deep_penetration: true,
      symmetry_error_cm: 0.01,
      fit_tension: fitTension,
      vertices_3d: fitTension.map((_, i) => [i, 0, 0]),
      fit_tension_mean: 0.001,
      fit_tension_max: 0.009,
      fit_tension_min: -0.01,
      fit_tension_rms: 0.005,
      avatar: { height_cm: 168, bust_cm: 88, waist_cm: 68, hip_cm: 96 },
    })
    const html = renderToStaticMarkup(
      React.createElement(GarmentDrapePanel, { content: sampleContent })
    )
    expect(html).toContain('data-testid="garment-drape-panel"')
    expect(html).toContain('data-testid="drape-status-bar"')
    expect(html).toContain('data-testid="drape-heatmap-section"')
  })
})

// ── Tier 3b: ApparelGradingPanel mount ──────────────────────────────────────

describe('ApparelGradingPanel — mount with sample content', () => {
  it('renders empty state when no content', async () => {
    const { default: ApparelGradingPanel } = await import(
      '../../../components/ApparelGradingPanel.jsx'
    )
    const html = renderToStaticMarkup(
      React.createElement(ApparelGradingPanel, {})
    )
    expect(html).toContain('data-testid="grading-panel-empty"')
  })

  it('renders size-run table from content string', async () => {
    const { default: ApparelGradingPanel } = await import(
      '../../../components/ApparelGradingPanel.jsx'
    )
    const sampleContent = JSON.stringify({
      base_size: 'M',
      sizes: {
        S:  { bust_girth_cm: 84, width_cm: 42, height_cm: 62, area_cm2: 2604, grade_dx_mm: -10, grade_dy_mm: -10 },
        M:  { bust_girth_cm: 88, width_cm: 44, height_cm: 64, area_cm2: 2816, grade_dx_mm: 0,   grade_dy_mm: 0 },
        L:  { bust_girth_cm: 94, width_cm: 47, height_cm: 66, area_cm2: 3102, grade_dx_mm: 10,  grade_dy_mm: 10 },
      },
    })
    const html = renderToStaticMarkup(
      React.createElement(ApparelGradingPanel, { content: sampleContent })
    )
    expect(html).toContain('data-testid="apparel-grading-panel"')
    expect(html).toContain('data-testid="grading-size-run-table"')
  })
})
