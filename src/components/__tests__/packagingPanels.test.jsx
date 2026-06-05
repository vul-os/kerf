/**
 * packagingPanels.test.jsx
 *
 * Source-level assertions for new packaging panels:
 *   - PackagingPrePressPanel  (ISO 15930-1 / ISO 12647-2 pre-press)
 *   - PackagingMaterialYieldPanel (PMMI material yield + cost)
 *
 * Uses same pattern as clashPanel.test.jsx — reads JSX source directly.
 */

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'

const PKG_DIR = resolve(__dirname, '../packaging')

const PP_SRC   = readFileSync(resolve(PKG_DIR, 'PackagingPrePressPanel.jsx'), 'utf8')
const YIELD_SRC = readFileSync(resolve(PKG_DIR, 'PackagingMaterialYieldPanel.jsx'), 'utf8')


// ===========================================================================
// PackagingPrePressPanel
// ===========================================================================

describe('PackagingPrePressPanel', () => {
  it('exports default function', () => {
    expect(PP_SRC).toMatch(/export default function PackagingPrePressPanel/)
  })

  it('calls packaging_prepress_check tool', () => {
    expect(PP_SRC).toMatch(/packaging_prepress_check/)
  })

  it('calls packaging_prepress_gen_marks tool', () => {
    expect(PP_SRC).toMatch(/packaging_prepress_gen_marks/)
  })

  it('calls packaging_prepress_export_pdf_x1a tool', () => {
    expect(PP_SRC).toMatch(/packaging_prepress_export_pdf_x1a/)
  })

  it('references ISO 15930-1 (PDF/X-1a)', () => {
    expect(PP_SRC).toMatch(/ISO 15930-1/)
  })

  it('references ISO 12647-2', () => {
    expect(PP_SRC).toMatch(/ISO 12647-2/)
  })

  it('has bleed_mm input', () => {
    expect(PP_SRC).toMatch(/bleed/)
  })

  it('has safety zone input', () => {
    expect(PP_SRC).toMatch(/safety/)
  })

  it('has finishing checkboxes', () => {
    expect(PP_SRC).toMatch(/finishing/i)
    expect(PP_SRC).toMatch(/varnish_gloss/)
    expect(PP_SRC).toMatch(/foil_stamp/)
  })

  it('has three tabs: check, marks, export', () => {
    expect(PP_SRC).toMatch(/Pre-Press Check/)
    expect(PP_SRC).toMatch(/Registration Marks/)
    expect(PP_SRC).toMatch(/PDF\/X-1a/)
  })

  it('shows honest caveat from backend', () => {
    expect(PP_SRC).toMatch(/honest_caveat/)
  })

  it('has offline demo fallback logic', () => {
    expect(PP_SRC).toMatch(/catch|fallback|Offline/)
  })

  it('renders plate count info', () => {
    expect(PP_SRC).toMatch(/[Pp]late/)
  })
})


// ===========================================================================
// PackagingMaterialYieldPanel
// ===========================================================================

describe('PackagingMaterialYieldPanel', () => {
  it('exports default function', () => {
    expect(YIELD_SRC).toMatch(/export default function PackagingMaterialYieldPanel/)
  })

  it('calls packaging_material_yield tool', () => {
    expect(YIELD_SRC).toMatch(/packaging_material_yield/)
  })

  it('references PMMI', () => {
    expect(YIELD_SRC).toMatch(/PMMI/)
  })

  it('has material preset selectors', () => {
    expect(YIELD_SRC).toMatch(/SBS.*320.*gsm|sbs_320gsm/i)
    expect(YIELD_SRC).toMatch(/[Cc]orrugated/)
  })

  it('has job_quantity input', () => {
    expect(YIELD_SRC).toMatch(/job_quantity/)
  })

  it('has nesting_efficiency_pct input', () => {
    expect(YIELD_SRC).toMatch(/nesting_efficiency_pct/)
  })

  it('has box_outline input', () => {
    expect(YIELD_SRC).toMatch(/box_outline/)
  })

  it('displays parts_per_sheet', () => {
    expect(YIELD_SRC).toMatch(/parts_per_sheet/)
  })

  it('displays total_material_cost', () => {
    expect(YIELD_SRC).toMatch(/total_material_cost/)
  })

  it('displays material_cost_per_part', () => {
    expect(YIELD_SRC).toMatch(/material_cost_per_part/)
  })

  it('displays waste_pct', () => {
    expect(YIELD_SRC).toMatch(/waste_pct/)
  })

  it('shows honest caveat from backend', () => {
    expect(YIELD_SRC).toMatch(/honest_caveat/)
  })

  it('has offline fallback', () => {
    expect(YIELD_SRC).toMatch(/catch|fallback|Offline/)
  })

  it('has Compute button', () => {
    expect(YIELD_SRC).toMatch(/Compute/)
  })
})
