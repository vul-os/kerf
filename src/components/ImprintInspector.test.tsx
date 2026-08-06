/**
 * ImprintInspector.test.jsx — G-5 Imprint toolpath inspector wiring tests.
 *
 * Strategy: source-level structural checks (same pattern as other tests here).
 * Verifies that the imprint_curve operation is registered in FEATURE_KINDS,
 * has the correct fields, and appears in the Analysis ops group.
 *
 * Tests:
 *   1. 'imprint_curve' op is in the FEATURE_KINDS catalog.
 *   2. The label 'ImprintCurve' is present in the catalog.
 *   3. Required fields: source_curve_ref, target_feature_ref, target_face_name.
 *   4. The 'imprint_curve' op is in the 'Analysis' ops group.
 *   5. The field label 'Source curve' is declared.
 *   6. The field label 'Target surface / body' is declared.
 *   7. The caption references Class-A toolpath.
 *   8. ImprintCurve uses 'sketch_picker' for the source curve field.
 *   9. ImprintCurve uses 'feature_picker' for the target surface field.
 *
 * Also tests that the FeatureView renders an imprint_curve chip via
 * renderToStaticMarkup (no browser/DOM required).
 */

import { describe, it, expect, vi } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const src = readFileSync(
  path.resolve(__dirname, './FeatureView.jsx'),
  'utf8',
)

// Extract the imprint_curve block — runs from "op: 'imprint_curve'" to the
// next top-level entry "  // " comment or "  {" start of the next op object.
// We use the blend_srf_g3 block boundary (the comment that follows imprint_curve
// in the source) as the end sentinel.
function extractImprintBlock(source) {
  const start = source.indexOf("op: 'imprint_curve'")
  if (start < 0) return ''
  // The block ends just before the next section comment (// blend_srf_g3)
  const end = source.indexOf('// blend_srf_g3', start)
  return end > start ? source.slice(start, end) : source.slice(start, start + 2000)
}
const imprintBlock = extractImprintBlock(src)

// ---------------------------------------------------------------------------
// Source-level tests (no DOM required)
// ---------------------------------------------------------------------------

describe('ImprintCurve inspector — FeatureView.jsx (G-5)', () => {
  it("registers 'imprint_curve' op in FEATURE_KINDS", () => {
    expect(src).toContain("op: 'imprint_curve'")
  })

  it("uses label 'ImprintCurve'", () => {
    expect(src).toContain("label: 'ImprintCurve'")
  })

  it("declares 'source_curve_ref' field", () => {
    expect(src).toContain("key: 'source_curve_ref'")
  })

  it("declares 'target_feature_ref' field in imprint_curve block", () => {
    expect(imprintBlock).toContain("key: 'target_feature_ref'")
  })

  it("declares 'target_face_name' field in imprint_curve block", () => {
    expect(imprintBlock).toContain("key: 'target_face_name'")
  })

  it("uses 'sketch_picker' kind for the source curve", () => {
    expect(imprintBlock).toContain("kind: 'sketch_picker'")
  })

  it("uses 'feature_picker' kind for the target surface", () => {
    expect(imprintBlock).toContain("kind: 'feature_picker'")
  })

  it("uses 'Activity' icon (from lucide-react)", () => {
    expect(imprintBlock).toContain('Activity')
  })

  it("caption references Class-A toolpath", () => {
    expect(imprintBlock).toContain('Class-A')
  })

  it("'imprint_curve' is in the Analysis ops group", () => {
    expect(src).toContain("'imprint_curve'")
    // The analysis ops array should contain imprint_curve
    const analysisMatch = src.match(
      /id:\s*'analysis'[\s\S]*?ops:\s*\[([\s\S]*?)\]/
    )
    expect(analysisMatch).not.toBeNull()
    const opsStr = analysisMatch?.[1] || ''
    expect(opsStr).toContain('imprint_curve')
  })

  it("label 'Source curve' appears in the fields", () => {
    expect(imprintBlock).toContain('Source curve')
  })

  it("label 'Target surface' appears in the fields", () => {
    expect(imprintBlock).toContain('Target surface')
  })
})

// ---------------------------------------------------------------------------
// Smoke-render test: FeatureView with imprint_curve node must not throw
// ---------------------------------------------------------------------------

vi.mock('lucide-react', async () => {
  const stub = (name) => () => React.createElement('span', { 'data-icon': name })
  // FeatureView.jsx's icon import list grows with every new feature kind.
  // A hand-maintained allowlist here goes stale every time a feature is
  // added and its icon isn't in the list ("No X export is defined on the
  // lucide-react mock"). Deriving the stub set from the real package's own
  // export list (vi.importActual) means it can never drift.
  const actual = await vi.importActual('lucide-react')
  return Object.fromEntries(Object.keys(actual).map((name) => [name, stub(name)]))
})

vi.mock('./FeatureRenderer.jsx', () => ({
  default: () => React.createElement('div', { 'data-testid': 'feature-renderer' }),
}))

vi.mock('../lib/occtRunner.js', () => ({
  runFeatures: vi.fn(() => Promise.resolve({ meshes: [], ms: 0 })),
  prewarmOcct: vi.fn(() => Promise.resolve()),
  newFeatureId: vi.fn((op) => `${op}-test-1`),
  requestFaceOutline: vi.fn(() => Promise.resolve(null)),
}))

const storeState = {
  featureSelection: { faceIds: new Set(), edgeIds: new Set() },
  featurePickMode: null,
  featurePickTarget: null,
  setFeatureSelection: vi.fn(),
  setFeaturePickMode: vi.fn(),
  clearFeatureSelection: vi.fn(),
  createSketchOnFace: vi.fn(),
  selectFile: vi.fn(),
  currentFile: null,
  currentFileId: null,
}

vi.mock('../store/workspace.js', () => ({
  useWorkspace: (selector) => selector(storeState),
}))

describe('FeatureView smoke render with imprint_curve node', () => {
  it('renders without throwing and emits ImprintCurve chip label', async () => {
    const { default: FeatureView } = await import('./FeatureView.jsx')
    const html = renderToStaticMarkup(
      React.createElement(FeatureView, {
        parsedFeature: {
          name: 'test.feature',
          features: [{
            id: 'imprint_curve-test-1',
            op: 'imprint_curve',
            source_curve_ref: '',
            target_feature_ref: '',
            target_face_name: 'face-1',
            tolerance: 1e-3,
            extend_curve: false,
          }],
        },
        files: [],
        onChangeTree: vi.fn(),
        loadSketchContent: vi.fn(() => Promise.resolve('')),
      }),
    )
    expect(html).toContain('ImprintCurve')
  })
})
