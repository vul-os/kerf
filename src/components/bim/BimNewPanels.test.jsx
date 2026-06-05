/**
 * BimNewPanels.test.jsx
 *
 * Vitest / renderToStaticMarkup smoke tests for the five new BIM panels:
 *   ConstructionSequencingPanel
 *   CostEstimationPanel
 *   ParametricFamilyEditorPanel
 *   GDLLibraryPanel
 *   SiteTerrainPanel
 *
 * Tests are intentionally shallow (SSR render-without-crash + key content
 * assertions) because the panels have no backend during test time.
 */
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import ConstructionSequencingPanel from './ConstructionSequencingPanel.jsx'
import CostEstimationPanel         from './CostEstimationPanel.jsx'
import ParametricFamilyEditorPanel from './ParametricFamilyEditorPanel.jsx'
import GDLLibraryPanel             from './GDLLibraryPanel.jsx'
import SiteTerrainPanel            from './SiteTerrainPanel.jsx'

// ---------------------------------------------------------------------------
// 1. ConstructionSequencingPanel
// ---------------------------------------------------------------------------

describe('ConstructionSequencingPanel', () => {
  it('renders without crashing (no props)', () => {
    expect(() => renderToStaticMarkup(<ConstructionSequencingPanel />)).not.toThrow()
  })

  it('renders a root element', () => {
    const html = renderToStaticMarkup(<ConstructionSequencingPanel />)
    expect(html.length).toBeGreaterThan(0)
  })

  it('shows 4D or construction sequencing label', () => {
    const html = renderToStaticMarkup(<ConstructionSequencingPanel />)
    const lower = html.toLowerCase()
    expect(
      lower.includes('4d') || lower.includes('sequencing') || lower.includes('schedule') || lower.includes('timeline')
    ).toBe(true)
  })

  it('contains Timeline or Tasks tab label', () => {
    const html = renderToStaticMarkup(<ConstructionSequencingPanel />)
    expect(html).toMatch(/Timeline|Tasks|Validation/i)
  })

  it('renders task-related UI elements', () => {
    const html = renderToStaticMarkup(<ConstructionSequencingPanel />)
    // Should have some date, task, or phase reference
    expect(html).toMatch(/task|phase|date|trade|start|finish/i)
  })

  it('renders without crashing with elementIds prop', () => {
    expect(() =>
      renderToStaticMarkup(<ConstructionSequencingPanel elementIds={['w1', 'w2', 'c1']} />)
    ).not.toThrow()
  })
})

// ---------------------------------------------------------------------------
// 2. CostEstimationPanel
// ---------------------------------------------------------------------------

describe('CostEstimationPanel', () => {
  it('renders without crashing (no props)', () => {
    expect(() => renderToStaticMarkup(<CostEstimationPanel />)).not.toThrow()
  })

  it('renders a root element', () => {
    const html = renderToStaticMarkup(<CostEstimationPanel />)
    expect(html.length).toBeGreaterThan(0)
  })

  it('shows cost or estimation label', () => {
    const html = renderToStaticMarkup(<CostEstimationPanel />)
    const lower = html.toLowerCase()
    expect(
      lower.includes('cost') || lower.includes('estimate') || lower.includes('budget') ||
      lower.includes('quantity') || lower.includes('5d')
    ).toBe(true)
  })

  it('contains Summary or By Phase or By Trade tab', () => {
    const html = renderToStaticMarkup(<CostEstimationPanel />)
    expect(html).toMatch(/Summary|Phase|Trade|Category|Element/i)
  })

  it('renders currency or numeric UI', () => {
    const html = renderToStaticMarkup(<CostEstimationPanel />)
    // Should reference cost, total, or $ somehow
    expect(html).toMatch(/total|cost|\$|USD|currency|unit/i)
  })

  it('renders without crashing with elements prop', () => {
    const elements = [
      { id: 'w1', category: 'Wall', area: 20.0, trade: 'structural' },
      { id: 'd1', category: 'Door', trade: 'architectural' },
    ]
    expect(() =>
      renderToStaticMarkup(<CostEstimationPanel elements={elements} />)
    ).not.toThrow()
  })
})

// ---------------------------------------------------------------------------
// 3. ParametricFamilyEditorPanel
// ---------------------------------------------------------------------------

describe('ParametricFamilyEditorPanel', () => {
  it('renders without crashing (no props)', () => {
    expect(() => renderToStaticMarkup(<ParametricFamilyEditorPanel />)).not.toThrow()
  })

  it('renders a root element', () => {
    const html = renderToStaticMarkup(<ParametricFamilyEditorPanel />)
    expect(html.length).toBeGreaterThan(0)
  })

  it('shows family or parametric label', () => {
    const html = renderToStaticMarkup(<ParametricFamilyEditorPanel />)
    const lower = html.toLowerCase()
    expect(
      lower.includes('family') || lower.includes('parametric') || lower.includes('parameter') ||
      lower.includes('type') || lower.includes('nested')
    ).toBe(true)
  })

  it('contains Parameters or Nested or Catalogue tab', () => {
    const html = renderToStaticMarkup(<ParametricFamilyEditorPanel />)
    expect(html).toMatch(/Parameters|Nested|Catalogue|Formula|Type/i)
  })

  it('renders without crashing with initial family prop', () => {
    const family = {
      name: 'Test Door', category: 'door',
      parameters: [{ name: 'width', type: 'number', default: 900.0 }],
    }
    expect(() =>
      renderToStaticMarkup(<ParametricFamilyEditorPanel initialFamily={family} />)
    ).not.toThrow()
  })

  it('renders formula or expression references', () => {
    const html = renderToStaticMarkup(<ParametricFamilyEditorPanel />)
    expect(html).toMatch(/formula|expression|parameter|default/i)
  })
})

// ---------------------------------------------------------------------------
// 4. GDLLibraryPanel
// ---------------------------------------------------------------------------

describe('GDLLibraryPanel', () => {
  it('renders without crashing (no props)', () => {
    expect(() => renderToStaticMarkup(<GDLLibraryPanel />)).not.toThrow()
  })

  it('renders a root element', () => {
    const html = renderToStaticMarkup(<GDLLibraryPanel />)
    expect(html.length).toBeGreaterThan(0)
  })

  it('shows GDL or library label', () => {
    const html = renderToStaticMarkup(<GDLLibraryPanel />)
    const lower = html.toLowerCase()
    expect(
      lower.includes('gdl') || lower.includes('library') || lower.includes('object') ||
      lower.includes('archicad') || lower.includes('parametric')
    ).toBe(true)
  })

  it('contains Browse or Editor tab', () => {
    const html = renderToStaticMarkup(<GDLLibraryPanel />)
    expect(html).toMatch(/Browse|Editor|Library|Script/i)
  })

  it('renders at least one built-in object card', () => {
    const html = renderToStaticMarkup(<GDLLibraryPanel />)
    // Should reference Door, Window, Column, etc.
    expect(html).toMatch(/Door|Window|Column|Beam|Desk|Light|Pendant/i)
  })

  it('renders subtype filter UI', () => {
    const html = renderToStaticMarkup(<GDLLibraryPanel />)
    expect(html).toMatch(/All|Door|Window|Column|Furniture/i)
  })

  it('renders without crashing with selectedObjectId prop', () => {
    expect(() =>
      renderToStaticMarkup(<GDLLibraryPanel selectedObjectId="DOOR_SINGLE_00001" />)
    ).not.toThrow()
  })
})

// ---------------------------------------------------------------------------
// 5. SiteTerrainPanel
// ---------------------------------------------------------------------------

describe('SiteTerrainPanel', () => {
  it('renders without crashing (no props)', () => {
    expect(() => renderToStaticMarkup(<SiteTerrainPanel />)).not.toThrow()
  })

  it('renders a root element', () => {
    const html = renderToStaticMarkup(<SiteTerrainPanel />)
    expect(html.length).toBeGreaterThan(0)
  })

  it('shows terrain or site label', () => {
    const html = renderToStaticMarkup(<SiteTerrainPanel />)
    const lower = html.toLowerCase()
    expect(
      lower.includes('terrain') || lower.includes('site') || lower.includes('mesh') ||
      lower.includes('tin') || lower.includes('slope')
    ).toBe(true)
  })

  it('contains Terrain or Slope or Contour tab', () => {
    const html = renderToStaticMarkup(<SiteTerrainPanel />)
    expect(html).toMatch(/Terrain|Slope|Contour|Cut|Fill|Points/i)
  })

  it('renders XYZ point editor elements', () => {
    const html = renderToStaticMarkup(<SiteTerrainPanel />)
    // Should reference X, Y, Z or coordinates
    expect(html).toMatch(/x|y|z|elevation|survey|point/i)
  })

  it('renders without crashing with initialPoints prop', () => {
    const pts = [
      [0, 0, 100], [10, 0, 102], [20, 0, 105],
      [0, 10, 101], [10, 10, 103], [20, 10, 106],
    ]
    expect(() =>
      renderToStaticMarkup(<SiteTerrainPanel initialPoints={pts} />)
    ).not.toThrow()
  })

  it('renders cut/fill or earthwork references', () => {
    const html = renderToStaticMarkup(<SiteTerrainPanel />)
    expect(html).toMatch(/cut|fill|earthwork|volume|datum/i)
  })
})
