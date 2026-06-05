/**
 * dental_parity.test.jsx — Vitest tests for 3shape parity deepening panels.
 *
 * Tests: CrownBridgePanel, ImplantPlanningPanel, RPDDenturePanel, IntraoralScanLabPanel
 * Pattern: renderToStaticMarkup (no @testing-library/react) + data-testid checks.
 */

import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

// ---------------------------------------------------------------------------
// Mocks — must be hoisted before component imports
// ---------------------------------------------------------------------------

vi.mock('../../store/auth.js', () => ({
  useAuth: () => ({ accessToken: 'test-token' }),
}))

// ---------------------------------------------------------------------------
// Component imports
// ---------------------------------------------------------------------------
import CrownBridgePanel from './CrownBridgePanel.jsx'
import ImplantPlanningPanel from './ImplantPlanningPanel.jsx'
import RPDDenturePanel from './RPDDenturePanel.jsx'
import IntraoralScanLabPanel from './IntaoralScanLabPanel.jsx'

// ============================================================================
// CrownBridgePanel
// ============================================================================

describe('CrownBridgePanel mount', () => {
  it('renders without throwing', () => {
    expect(() => renderToStaticMarkup(
      <CrownBridgePanel projectId="proj-1" />,
    )).not.toThrow()
  })

  it('shows tool name reference', () => {
    const html = renderToStaticMarkup(<CrownBridgePanel projectId="proj-1" />)
    expect(html).toContain('dental_crown_bridge_design')
  })

  it('contains tooth preset buttons', () => {
    const html = renderToStaticMarkup(<CrownBridgePanel projectId="proj-1" />)
    expect(html).toContain('UR1')
    expect(html).toContain('LL6')
  })

  it('contains margin type selector', () => {
    const html = renderToStaticMarkup(<CrownBridgePanel projectId="proj-1" />)
    expect(html).toContain('chamfer')
    expect(html).toContain('shoulder')
    expect(html).toContain('feather')
  })

  it('contains material selector', () => {
    const html = renderToStaticMarkup(<CrownBridgePanel projectId="proj-1" />)
    expect(html).toContain('zirconia')
    expect(html).toContain('lithium_disilicate')
    expect(html).toContain('pmma')
  })

  it('shows ISO 4049 cement gap label', () => {
    const html = renderToStaticMarkup(<CrownBridgePanel projectId="proj-1" />)
    expect(html).toContain('ISO 4049')
  })

  it('shows cement gap in µm', () => {
    const html = renderToStaticMarkup(<CrownBridgePanel projectId="proj-1" />)
    expect(html).toContain('µm')
  })

  it('shows min wall reference', () => {
    const html = renderToStaticMarkup(<CrownBridgePanel projectId="proj-1" />)
    expect(html).toContain('Min wall')
  })

  it('has bridge mode checkbox', () => {
    const html = renderToStaticMarkup(<CrownBridgePanel projectId="proj-1" />)
    expect(html).toContain('Bridge mode')
  })

  it('has run button', () => {
    const html = renderToStaticMarkup(<CrownBridgePanel projectId="proj-1" />)
    expect(html).toContain('Design crown')
  })
})

// ============================================================================
// ImplantPlanningPanel
// ============================================================================

describe('ImplantPlanningPanel mount', () => {
  it('renders without throwing', () => {
    expect(() => renderToStaticMarkup(
      <ImplantPlanningPanel projectId="proj-1" />,
    )).not.toThrow()
  })

  it('shows tool name reference', () => {
    const html = renderToStaticMarkup(<ImplantPlanningPanel projectId="proj-1" />)
    expect(html).toContain('dental_implant_spacing_check')
  })

  it('contains brand selector with Straumann', () => {
    const html = renderToStaticMarkup(<ImplantPlanningPanel projectId="proj-1" />)
    expect(html).toContain('Straumann BLT')
    expect(html).toContain('NobelActive')
    expect(html).toContain('Astra EV')
  })

  it('contains Tarnow/Grunder section', () => {
    const html = renderToStaticMarkup(<ImplantPlanningPanel projectId="proj-1" />)
    expect(html).toContain('Tarnow')
    expect(html).toContain('Grunder')
  })

  it('contains drill sequence button', () => {
    const html = renderToStaticMarkup(<ImplantPlanningPanel projectId="proj-1" />)
    expect(html).toContain('Get sequence')
  })

  it('contains spacing check button', () => {
    const html = renderToStaticMarkup(<ImplantPlanningPanel projectId="proj-1" />)
    expect(html).toContain('Check spacing')
  })

  it('shows position inputs for two implants', () => {
    const html = renderToStaticMarkup(<ImplantPlanningPanel projectId="proj-1" />)
    expect(html).toContain('Imp 1')
    expect(html).toContain('Imp 2')
  })

  it('shows disclaimer text', () => {
    const html = renderToStaticMarkup(<ImplantPlanningPanel projectId="proj-1" />)
    expect(html).toContain('NOT FDA-cleared')
  })
})

// ============================================================================
// RPDDenturePanel
// ============================================================================

describe('RPDDenturePanel mount', () => {
  it('renders without throwing', () => {
    expect(() => renderToStaticMarkup(
      <RPDDenturePanel projectId="proj-1" />,
    )).not.toThrow()
  })

  it('shows tool name reference', () => {
    const html = renderToStaticMarkup(<RPDDenturePanel projectId="proj-1" />)
    expect(html).toContain('dental_denture_design_v2')
  })

  it('shows arch selector', () => {
    const html = renderToStaticMarkup(<RPDDenturePanel projectId="proj-1" />)
    expect(html).toContain('mandibular')
    expect(html).toContain('maxillary')
  })

  it('shows partial/complete type selector', () => {
    const html = renderToStaticMarkup(<RPDDenturePanel projectId="proj-1" />)
    expect(html).toContain('partial')
    expect(html).toContain('complete')
  })

  it('shows Kennedy class panel', () => {
    const html = renderToStaticMarkup(<RPDDenturePanel projectId="proj-1" />)
    expect(html).toContain('Class I')
  })

  it('shows Kennedy classification description', () => {
    const html = renderToStaticMarkup(<RPDDenturePanel projectId="proj-1" />)
    expect(html).toContain('Bilateral')
  })

  it('contains FDI tooth buttons', () => {
    const html = renderToStaticMarkup(<RPDDenturePanel projectId="proj-1" />)
    expect(html).toContain('36')
    expect(html).toContain('46')
  })

  it('contains clasp type selector', () => {
    const html = renderToStaticMarkup(<RPDDenturePanel projectId="proj-1" />)
    expect(html).toContain('circumferential')
    expect(html).toContain('I-bar')
  })

  it('shows McCracken reference', () => {
    const html = renderToStaticMarkup(<RPDDenturePanel projectId="proj-1" />)
    expect(html).toContain('McCracken')
  })

  it('shows Applegate reference', () => {
    const html = renderToStaticMarkup(<RPDDenturePanel projectId="proj-1" />)
    expect(html).toContain('Applegate')
  })

  it('has run button', () => {
    const html = renderToStaticMarkup(<RPDDenturePanel projectId="proj-1" />)
    expect(html).toContain('Design partial')
  })
})

// ============================================================================
// IntraoralScanLabPanel
// ============================================================================

describe('IntraoralScanLabPanel mount', () => {
  it('renders without throwing', () => {
    expect(() => renderToStaticMarkup(
      <IntraoralScanLabPanel projectId="proj-1" />,
    )).not.toThrow()
  })

  it('shows tool name reference', () => {
    const html = renderToStaticMarkup(<IntraoralScanLabPanel projectId="proj-1" />)
    expect(html).toContain('dental_intraoral_scan_process')
  })

  it('contains scanner brand options including Trios', () => {
    const html = renderToStaticMarkup(<IntraoralScanLabPanel projectId="proj-1" />)
    expect(html).toContain('Trios')
    expect(html).toContain('Itero Element')
    expect(html).toContain('Medit i700')
  })

  it('contains arch selector', () => {
    const html = renderToStaticMarkup(<IntraoralScanLabPanel projectId="proj-1" />)
    expect(html).toContain('maxillary')
    expect(html).toContain('mandibular')
  })

  it('contains Import button for scan', () => {
    const html = renderToStaticMarkup(<IntraoralScanLabPanel projectId="proj-1" />)
    expect(html).toContain('Import')
  })

  it('contains Export button for lab', () => {
    const html = renderToStaticMarkup(<IntraoralScanLabPanel projectId="proj-1" />)
    expect(html).toContain('Export')
  })

  it('mentions ICP algorithm', () => {
    const html = renderToStaticMarkup(<IntraoralScanLabPanel projectId="proj-1" />)
    expect(html).toContain('ICP')
  })

  it('shows Besl-McKay reference', () => {
    const html = renderToStaticMarkup(<IntraoralScanLabPanel projectId="proj-1" />)
    expect(html).toContain('Besl-McKay')
  })

  it('shows Chen-Medioni reference', () => {
    const html = renderToStaticMarkup(<IntraoralScanLabPanel projectId="proj-1" />)
    expect(html).toContain('Chen-Medioni')
  })

  it('shows Roland DWX lab export reference', () => {
    const html = renderToStaticMarkup(<IntraoralScanLabPanel projectId="proj-1" />)
    expect(html).toContain('Roland DWX')
  })

  it('shows NOT FDA-cleared disclaimer', () => {
    const html = renderToStaticMarkup(<IntraoralScanLabPanel projectId="proj-1" />)
    expect(html).toContain('NOT FDA-cleared')
  })
})

// ============================================================================
// Client-side Kennedy classification (RPDDenturePanel internal logic test)
// ============================================================================

// Test the Kennedy classification pure logic by extracting what the component
// renders in the default state (36, 46 selected = bilateral posterior = Class I)
describe('RPDDenturePanel Kennedy default state', () => {
  it('shows Class I for default bilateral posterior selection', () => {
    const html = renderToStaticMarkup(<RPDDenturePanel projectId="proj-1" />)
    // Default selection is 36 + 46 (bilateral posterior) = Class I
    expect(html).toContain('Class I')
  })
})
