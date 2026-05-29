/**
 * ClassAToggle.test.jsx — G-5 Class-A frontend wiring tests.
 *
 * Strategy: source-level structural checks via readFileSync (same pattern
 * as CurvatureCombOverlay.test.jsx) so we can run headless without
 * @testing-library/react.
 *
 * Tests:
 *   1. The "Class-A" label is present in the Render dropdown items array.
 *   2. classAOn state is declared.
 *   3. classAReport state is declared (stores per-edge audit data).
 *   4. ClassAPanel component is defined in Renderer.jsx.
 *   5. ClassAPanel has role="region" and data-testid for test hooks.
 *   6. ClassAPanel close button has aria-label for accessibility.
 *   7. The continuity_grade per-edge display is rendered in the panel.
 *   8. ClassAPanel shows a loading indicator text.
 */

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const src = readFileSync(
  path.resolve(__dirname, './Renderer.jsx'),
  'utf8',
)

// Locate the ClassAPanel function definition
const panelStart = src.indexOf('function ClassAPanel(')
const panelSrc = panelStart >= 0 ? src.slice(panelStart) : ''

describe('Class-A viewport toggle — Renderer.jsx (G-5)', () => {
  it('declares classAOn state', () => {
    expect(src).toContain('classAOn')
    expect(src).toContain('setClassAOn')
  })

  it('declares classAReport state for per-edge audit data', () => {
    expect(src).toContain('classAReport')
    expect(src).toContain('setClassAReport')
  })

  it('declares classALoading state for async audit request', () => {
    expect(src).toContain('classALoading')
    expect(src).toContain('setClassALoading')
  })

  it('includes "Class-A" label in the Render dropdown items', () => {
    expect(src).toContain("label: 'Class-A'")
  })

  it('includes a hint referencing G2/G3 continuity audit', () => {
    expect(src).toContain('G2/G3')
  })

  it('defines the ClassAPanel component', () => {
    expect(panelStart).toBeGreaterThan(-1)
    expect(panelSrc.length).toBeGreaterThan(100)
  })

  it('ClassAPanel has role="region" for accessibility', () => {
    expect(panelSrc).toContain('role="region"')
  })

  it('ClassAPanel has aria-label="Class-A continuity audit"', () => {
    expect(panelSrc).toContain('aria-label="Class-A continuity audit"')
  })

  it('ClassAPanel has data-testid="class-a-panel"', () => {
    expect(panelSrc).toContain('data-testid="class-a-panel"')
  })

  it('ClassAPanel close button has aria-label', () => {
    expect(panelSrc).toContain('aria-label="Close Class-A panel"')
  })

  it('ClassAPanel renders continuity_grade per-edge data', () => {
    expect(panelSrc).toContain('continuity_grade')
  })

  it('ClassAPanel renders G2_rms and G3_rms residual columns', () => {
    expect(panelSrc).toContain('G2_rms')
    expect(panelSrc).toContain('G3_rms')
  })

  it('ClassAPanel shows Analysing… loading text', () => {
    expect(panelSrc).toContain('Analysing')
  })

  it('classAOn effect calls runFeatures with global_continuity_audit op', () => {
    // The class-A effect dispatches via occtRunner.js runFeatures with
    // the global_continuity_audit operation.
    expect(src).toContain('global_continuity_audit')
    expect(src).toContain("'classA-audit'")
  })
})
