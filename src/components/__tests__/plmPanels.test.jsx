/**
 * plmPanels.test.jsx
 *
 * Source-level assertions for PLM panels:
 *   - QuoteToDeliveryPanel (ISA-95 state machine)
 *   - ConfiguratorPanel (PLM variant BOM)
 *   - SysMLTracePanel (SysML traceability)
 *
 * Tests read JSX source directly (same pattern as clashPanel.test.jsx)
 * to avoid heavy DOM/Monaco/three.js setup.
 */

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'

const PLM_DIR = resolve(__dirname, '../plm')

const Q2D_SRC = readFileSync(resolve(PLM_DIR, 'QuoteToDeliveryPanel.jsx'), 'utf8')
const CONF_SRC = readFileSync(resolve(PLM_DIR, 'ConfiguratorPanel.jsx'), 'utf8')
const SYSML_SRC = readFileSync(resolve(PLM_DIR, 'SysMLTracePanel.jsx'), 'utf8')


// ===========================================================================
// QuoteToDeliveryPanel
// ===========================================================================

describe('QuoteToDeliveryPanel', () => {
  it('exports a default component function', () => {
    expect(Q2D_SRC).toMatch(/export default function QuoteToDeliveryPanel/)
  })

  it('references the plm_quote_to_delivery tool endpoint', () => {
    expect(Q2D_SRC).toMatch(/plm_quote_to_delivery/)
  })

  it('has transition operation', () => {
    expect(Q2D_SRC).toMatch(/['"]transition['"]/)
  })

  it('has status_report operation', () => {
    expect(Q2D_SRC).toMatch(/['"]status_report['"]/)
  })

  it('mentions ISA-95 in a comment or label', () => {
    expect(Q2D_SRC).toMatch(/ISA-95/)
  })

  it('renders QUOTED → INVOICED status enum values', () => {
    const statuses = ['quoted', 'quote_accepted', 'design', 'mold_making',
                      'sampling', 'production', 'qc_hold', 'shipped', 'delivered', 'invoiced']
    for (const s of statuses) {
      expect(Q2D_SRC).toMatch(new RegExp(`['"]${s}['"]`))
    }
  })

  it('has advance/transition button', () => {
    expect(Q2D_SRC).toMatch(/Advance|transition|Arrow/)
  })

  it('renders audit trail / milestone list', () => {
    expect(Q2D_SRC).toMatch(/[Aa]udit|[Mm]ilestone|[Hh]istory/)
  })

  it('has APICS reference', () => {
    expect(Q2D_SRC).toMatch(/APICS/)
  })

  it('renders overdue badge when is_overdue', () => {
    expect(Q2D_SRC).toMatch(/[Oo]verdue/)
  })

  it('has QC_HOLD rework loop in VALID_NEXT', () => {
    expect(Q2D_SRC).toMatch(/qc_hold.*production|production.*qc_hold/)
  })

  it('renders days_in_status', () => {
    expect(Q2D_SRC).toMatch(/days_in_status/)
  })
})


// ===========================================================================
// ConfiguratorPanel (already existed — verify still wired)
// ===========================================================================

describe('ConfiguratorPanel', () => {
  it('exports default function', () => {
    expect(CONF_SRC).toMatch(/export default function ConfiguratorPanel/)
  })

  it('calls plm_resolve_variant_bom tool', () => {
    expect(CONF_SRC).toMatch(/plm_resolve_variant_bom/)
  })

  it('has ISO 10303-44 reference', () => {
    expect(CONF_SRC).toMatch(/ISO 10303-44/)
  })

  it('renders Resolve BOM button', () => {
    expect(CONF_SRC).toMatch(/Resolve BOM/)
  })

  it('supports include and exclude variant conditions', () => {
    expect(CONF_SRC).toMatch(/include/)
    expect(CONF_SRC).toMatch(/exclude/)
  })
})


// ===========================================================================
// SysMLTracePanel (already existed — verify still wired)
// ===========================================================================

describe('SysMLTracePanel', () => {
  it('exports default function', () => {
    expect(SYSML_SRC).toMatch(/export default function SysMLTracePanel/)
  })

  it('uses sysml_trace_coverage tool', () => {
    expect(SYSML_SRC).toMatch(/sysml_trace_coverage/)
  })

  it('uses sysml_export_xmi tool', () => {
    expect(SYSML_SRC).toMatch(/sysml_export_xmi/)
  })

  it('has Coverage Matrix tab', () => {
    expect(SYSML_SRC).toMatch(/Coverage/)
  })
})
