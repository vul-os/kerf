// mech.test.jsx — Registry + mount tests for FEM / Mechanical panel fragment.
//
// Run: npx vitest run src/lib/panels/__tests__/mech.test.jsx
//
// Two test groups:
//   1. resolvePanelEntry — each entry in mech.js resolves by kind and ext.
//   2. Mount smoke tests — ≥2 panels render with sample content prop.
//
// Strategy:
//   • Import mech.js directly (avoids import.meta.glob in panelRegistry.js).
//   • Replicate the registry resolver inline — it is a two-liner and avoids
//     mocking the entire panelRegistry module.
//   • Use renderToStaticMarkup (react-dom/server) — no jsdom required.

import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import MECH_ENTRIES from '../mech.js'

// ---------------------------------------------------------------------------
// 1. Registry resolution — kind + ext matching
// ---------------------------------------------------------------------------

/**
 * Minimal replica of panelRegistry resolvePanelEntry logic.
 * @param {Array} entries  — mech.js default export
 * @param {{ kind?: string, name?: string }} file
 */
function resolveEntry(entries, file) {
  if (!file) return null
  const kind = String(file.kind || '').toLowerCase()
  const name = String(file.name || '').toLowerCase()
  for (const e of entries) {
    const kindHit = kind && (e.kinds || []).some((k) => String(k).toLowerCase() === kind)
    const extHit = (e.exts || []).some((x) => name.endsWith(String(x).toLowerCase()))
    if (kindHit || extHit) return e
  }
  return null
}

// Map of expected id → kind used for wiring
const EXPECTED = [
  { id: 'struct_member',        kind: 'struct_member',        ext: '.member' },
  { id: 'seismic_rsa',          kind: 'seismic_rsa',          ext: '.seismic' },
  { id: 'bearing_life',         kind: 'bearing_life',         ext: '.bearing' },
  { id: 'gear_rating',          kind: 'gear_rating',          ext: '.gear' },
  { id: 'shaft_stress',         kind: 'shaft_stress',         ext: '.shaft' },
  { id: 'iso286_fits',          kind: 'iso286_fits',          ext: '.fits' },
  { id: 'weldment_frame',       kind: 'weldment_frame',       ext: '.weldment' },
  { id: 'mechanism_synthesis',  kind: 'mechanism_synthesis',  ext: '.mechanism' },
  { id: 'nurbs_surfacing',      kind: 'nurbs_surfacing',      ext: '.surf' },
  { id: 'mesh_repair',          kind: 'mesh_repair',          ext: '.meshfix' },
  { id: 'sheet_metal',          kind: 'sheet_metal',          ext: '.sheetmetal' },
]

describe('mech.js — structure', () => {
  it('exports a non-empty array', () => {
    expect(Array.isArray(MECH_ENTRIES)).toBe(true)
    expect(MECH_ENTRIES.length).toBeGreaterThanOrEqual(11)
  })

  it('every entry has id, kinds, exts, load, label', () => {
    for (const e of MECH_ENTRIES) {
      expect(typeof e.id).toBe('string')
      expect(Array.isArray(e.kinds)).toBe(true)
      expect(Array.isArray(e.exts)).toBe(true)
      expect(typeof e.load).toBe('function')
      expect(typeof e.label).toBe('string')
    }
  })
})

describe('resolvePanelEntry — kind matching', () => {
  for (const { id, kind } of EXPECTED) {
    it(`resolves "${id}" by kind "${kind}"`, () => {
      const e = resolveEntry(MECH_ENTRIES, { kind })
      expect(e).not.toBeNull()
      expect(e.id).toBe(id)
    })
  }
})

describe('resolvePanelEntry — ext matching', () => {
  for (const { id, ext } of EXPECTED) {
    it(`resolves "${id}" by filename ext "${ext}"`, () => {
      const e = resolveEntry(MECH_ENTRIES, { name: `design${ext}` })
      expect(e).not.toBeNull()
      expect(e.id).toBe(id)
    })
  }
})

describe('resolvePanelEntry — no false positives', () => {
  it('returns null for an unknown kind', () => {
    expect(resolveEntry(MECH_ENTRIES, { kind: 'unknown_xyz' })).toBeNull()
  })

  it('returns null for an unknown ext', () => {
    expect(resolveEntry(MECH_ENTRIES, { name: 'file.unknown' })).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// 2. Mount smoke tests — panels accept content prop and render without error
// ---------------------------------------------------------------------------

// StructuralMemberPanel
import StructuralMemberPanel from '../../../components/structural/StructuralMemberPanel.jsx'
// SeismicRSAPanel
import SeismicRSAPanel from '../../../components/structural/SeismicRSAPanel.jsx'
// MeshRepairPanel
import MeshRepairPanel from '../../../components/MeshRepairPanel.jsx'
// SheetMetalPanel
import SheetMetalPanel from '../../../components/SheetMetalPanel.jsx'
// SurfacingPanel
import SurfacingPanel from '../../../components/SurfacingPanel.jsx'
// MechanismSynthesisPanel
import MechanismSynthesisPanel from '../../../components/MechanismSynthesisPanel.jsx'

// Lucide-react icons are used by all panels — mock them globally.
// vi.mock is hoisted so the factory must be self-contained (no outer vars).
import { vi } from 'vitest'

vi.mock('lucide-react', () => {
  const i = () => null
  return {
    Activity: i, AlertTriangle: i, BarChart2: i, Box: i,
    Calculator: i, CheckCircle: i, ChevronDown: i, ChevronRight: i,
    ChevronUp: i, Circle: i, Cog: i, Cpu: i,
    FileDown: i, Frame: i, GitBranch: i, Grid3X3: i,
    Info: i, Layers: i, Loader2: i, Play: i,
    Ruler: i, Scan: i, Scissors: i, Settings: i,
    Sliders: i, Square: i, Triangle: i, TrendingDown: i,
    Wrench: i, Zap: i,
  }
})

// api.js is imported by BearingLifePanel / GearRatingPanel / etc.
vi.mock('../../../lib/api.js', () => ({ api: vi.fn() }))

describe('mount — StructuralMemberPanel accepts content prop', () => {
  it('renders with no content prop', () => {
    expect(() => renderToStaticMarkup(<StructuralMemberPanel />)).not.toThrow()
  })

  it('renders with valid JSON content (tab: rc)', () => {
    const content = JSON.stringify({ tab: 'rc' })
    expect(() => renderToStaticMarkup(<StructuralMemberPanel content={content} />)).not.toThrow()
  })

  it('renders with invalid JSON content (fallback to defaults)', () => {
    expect(() => renderToStaticMarkup(<StructuralMemberPanel content="not-json{{{" />)).not.toThrow()
  })

  it('contains Structural Member Design text', () => {
    const html = renderToStaticMarkup(<StructuralMemberPanel />)
    expect(html).toContain('Structural Member Design')
  })
})

describe('mount — SeismicRSAPanel accepts content prop', () => {
  it('renders with no content prop', () => {
    expect(() => renderToStaticMarkup(<SeismicRSAPanel />)).not.toThrow()
  })

  it('renders with valid JSON content (tab: sdof)', () => {
    const content = JSON.stringify({ tab: 'sdof' })
    expect(() => renderToStaticMarkup(<SeismicRSAPanel content={content} />)).not.toThrow()
  })

  it('renders with invalid JSON content (fallback to defaults)', () => {
    expect(() => renderToStaticMarkup(<SeismicRSAPanel content="bad json" />)).not.toThrow()
  })

  it('contains Seismic RSA text', () => {
    const html = renderToStaticMarkup(<SeismicRSAPanel />)
    expect(html).toContain('Seismic RSA')
  })
})

describe('mount — MeshRepairPanel accepts content prop', () => {
  it('renders with no content prop', () => {
    expect(() => renderToStaticMarkup(<MeshRepairPanel />)).not.toThrow()
  })

  it('renders with valid JSON content (tab: ShrinkWrap)', () => {
    const content = JSON.stringify({ tab: 'ShrinkWrap' })
    expect(() => renderToStaticMarkup(<MeshRepairPanel content={content} />)).not.toThrow()
  })

  it('contains Mesh Repair heading', () => {
    const html = renderToStaticMarkup(<MeshRepairPanel />)
    expect(html).toContain('Mesh Repair')
  })
})

describe('mount — SheetMetalPanel accepts content prop', () => {
  it('renders with no content prop', () => {
    expect(() => renderToStaticMarkup(<SheetMetalPanel />)).not.toThrow()
  })

  it('renders with valid JSON content (tab: Corner Relief)', () => {
    const content = JSON.stringify({ tab: 'Corner Relief' })
    expect(() => renderToStaticMarkup(<SheetMetalPanel content={content} />)).not.toThrow()
  })

  it('contains Sheet Metal heading', () => {
    const html = renderToStaticMarkup(<SheetMetalPanel />)
    expect(html).toContain('Sheet Metal')
  })
})

describe('mount — SurfacingPanel accepts content prop', () => {
  it('renders with no content prop', () => {
    expect(() => renderToStaticMarkup(<SurfacingPanel />)).not.toThrow()
  })

  it('renders with valid JSON content (tab: Skinning)', () => {
    const content = JSON.stringify({ tab: 'Skinning' })
    expect(() => renderToStaticMarkup(<SurfacingPanel content={content} />)).not.toThrow()
  })

  it('contains NURBS Surfacing heading', () => {
    const html = renderToStaticMarkup(<SurfacingPanel />)
    expect(html).toContain('NURBS Surfacing')
  })
})

describe('mount — MechanismSynthesisPanel accepts content prop', () => {
  it('renders with no content prop', () => {
    expect(() => renderToStaticMarkup(<MechanismSynthesisPanel />)).not.toThrow()
  })

  it('renders with valid JSON content (tab: cam)', () => {
    const content = JSON.stringify({ tab: 'cam' })
    expect(() => renderToStaticMarkup(<MechanismSynthesisPanel content={content} />)).not.toThrow()
  })

  it('contains Mechanism Synthesis text', () => {
    const html = renderToStaticMarkup(<MechanismSynthesisPanel />)
    expect(html).toContain('Mechanism Synthesis')
  })
})

// ---------------------------------------------------------------------------
// 3. load() functions return thenable promises (dynamic import contract)
// ---------------------------------------------------------------------------

describe('mech.js — load() returns a Promise', () => {
  for (const { id } of EXPECTED) {
    it(`entry "${id}" load() returns a thenable`, () => {
      const e = MECH_ENTRIES.find((x) => x.id === id)
      const result = e.load()
      expect(typeof result.then).toBe('function')
    })
  }
})
