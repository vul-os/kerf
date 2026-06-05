// GeometryImportPanel.test.jsx — vitest, renderToStaticMarkup (no jsdom needed)
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import {
  detectGeometryFormat,
  isGeometryFile,
  GeometryImportReport,
  GeometryImportProgress,
} from './GeometryImportPanel.jsx'

// ---------------------------------------------------------------------------
// detectGeometryFormat — pure function, no render
// ---------------------------------------------------------------------------

describe('detectGeometryFormat', () => {
  it('detects .step by filename string', () => {
    const fmt = detectGeometryFormat('part.step')
    expect(fmt).toBeTruthy()
    expect(fmt.label).toBe('STEP')
  })

  it('detects .stp extension', () => {
    expect(detectGeometryFormat('assembly.stp').label).toBe('STEP')
  })

  it('detects .iges extension', () => {
    expect(detectGeometryFormat('model.iges').label).toBe('IGES 5.3')
  })

  it('detects .igs extension', () => {
    expect(detectGeometryFormat('model.igs').label).toBe('IGES 5.3')
  })

  it('detects .3dm (Rhino)', () => {
    expect(detectGeometryFormat('surface.3dm').label).toBe('Rhino 3dm')
  })

  it('detects .dxf', () => {
    expect(detectGeometryFormat('drawing.dxf').label).toBe('DXF')
  })

  it('detects .FCStd (FreeCAD)', () => {
    expect(detectGeometryFormat('project.FCStd').label).toBe('FreeCAD')
  })

  it('detects .fcstd (lowercase)', () => {
    expect(detectGeometryFormat('project.fcstd').label).toBe('FreeCAD')
  })

  it('returns null for .png', () => {
    expect(detectGeometryFormat('image.png')).toBeNull()
  })

  it('returns null for .pdf', () => {
    expect(detectGeometryFormat('drawing.pdf')).toBeNull()
  })

  it('returns null for .xlsx', () => {
    expect(detectGeometryFormat('data.xlsx')).toBeNull()
  })

  it('is case-insensitive (.STEP)', () => {
    expect(detectGeometryFormat('PART.STEP').label).toBe('STEP')
  })

  it('is case-insensitive (.STP)', () => {
    expect(detectGeometryFormat('PART.STP').label).toBe('STEP')
  })

  it('works with File-like object', () => {
    const f = { name: 'assembly.step' }
    expect(detectGeometryFormat(f).label).toBe('STEP')
  })

  it('returns null for empty string', () => {
    expect(detectGeometryFormat('')).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// isGeometryFile — pure function
// ---------------------------------------------------------------------------

describe('isGeometryFile', () => {
  it('returns true for .step', () => {
    expect(isGeometryFile('part.step')).toBe(true)
  })

  it('returns true for .stp', () => {
    expect(isGeometryFile('part.stp')).toBe(true)
  })

  it('returns true for .iges', () => {
    expect(isGeometryFile('part.iges')).toBe(true)
  })

  it('returns true for .igs', () => {
    expect(isGeometryFile('part.igs')).toBe(true)
  })

  it('returns true for .3dm', () => {
    expect(isGeometryFile('model.3dm')).toBe(true)
  })

  it('returns true for .dxf', () => {
    expect(isGeometryFile('drawing.dxf')).toBe(true)
  })

  it('returns true for .FCStd', () => {
    expect(isGeometryFile('project.FCStd')).toBe(true)
  })

  it('returns false for .jpg', () => {
    expect(isGeometryFile('photo.jpg')).toBe(false)
  })

  it('returns false for .xlsx', () => {
    expect(isGeometryFile('data.xlsx')).toBe(false)
  })

  it('returns false for .pdf', () => {
    expect(isGeometryFile('drawing.pdf')).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// GeometryImportReport — SSR rendering
// ---------------------------------------------------------------------------

const IGES_DATA = {
  ok: true,
  units: 'MM',
  product_id: 'BRACKET',
  source_system: 'SolidWorks',
  total_entities: 42,
  entity_counts: { Line: 12, NURBSCurve: 8, NURBSSurface: 4, Point: 18 },
  nurbs_curves: 8,
  nurbs_surfaces: 4,
  brep_bodies: 2,
  warnings: [],
}

describe('GeometryImportReport', () => {
  it('renders without crashing', () => {
    expect(() =>
      renderToStaticMarkup(<GeometryImportReport format="IGES 5.3" data={IGES_DATA} />)
    ).not.toThrow()
  })

  it('renders success text', () => {
    const html = renderToStaticMarkup(<GeometryImportReport format="IGES 5.3" data={IGES_DATA} />)
    expect(html).toMatch(/IGES 5\.3 import complete/i)
  })

  it('shows total entity count', () => {
    const html = renderToStaticMarkup(<GeometryImportReport format="IGES 5.3" data={IGES_DATA} />)
    expect(html).toMatch(/42 entities/i)
  })

  it('shows product_id', () => {
    const html = renderToStaticMarkup(<GeometryImportReport format="IGES 5.3" data={IGES_DATA} />)
    expect(html).toContain('BRACKET')
  })

  it('shows source_system', () => {
    const html = renderToStaticMarkup(<GeometryImportReport format="IGES 5.3" data={IGES_DATA} />)
    expect(html).toContain('SolidWorks')
  })

  it('shows units', () => {
    const html = renderToStaticMarkup(<GeometryImportReport format="IGES 5.3" data={IGES_DATA} />)
    expect(html).toContain('MM')
  })

  it('shows entity type counts', () => {
    const html = renderToStaticMarkup(<GeometryImportReport format="IGES 5.3" data={IGES_DATA} />)
    expect(html).toMatch(/NURBSCurve|NURBS/i)
  })

  it('renders nothing when data is null', () => {
    const html = renderToStaticMarkup(<GeometryImportReport format="IGES 5.3" data={null} />)
    expect(html).toBe('')
  })

  it('shows warning count when warnings present', () => {
    const data = { ...IGES_DATA, warnings: ['Unknown entity 9999', 'Skipped empty DE'] }
    const html = renderToStaticMarkup(<GeometryImportReport format="IGES 5.3" data={data} />)
    expect(html).toMatch(/2 warning/i)
  })

  it('renders STEP bodies/surfaces/curves layout', () => {
    const stepData = { bodies: 3, surfaces: 18, curves: 24, warnings: [] }
    const html = renderToStaticMarkup(<GeometryImportReport format="STEP" data={stepData} />)
    expect(html).toMatch(/Bodies/i)
    expect(html).toContain('3')
  })

  it('renders Rhino 3dm count_by_kind', () => {
    const rData = {
      stats: { count_by_kind: { Curve: 5, Surface: 3, BRep: 1 } },
      warnings: [],
    }
    const html = renderToStaticMarkup(<GeometryImportReport format="Rhino 3dm" data={rData} />)
    expect(html).toMatch(/Curve|Surface|BRep/)
  })

  it('shows NURBS surfaces count', () => {
    const html = renderToStaticMarkup(<GeometryImportReport format="IGES 5.3" data={IGES_DATA} />)
    expect(html).toContain('4')
  })

  it('shows NURBS curves count', () => {
    const html = renderToStaticMarkup(<GeometryImportReport format="IGES 5.3" data={IGES_DATA} />)
    expect(html).toContain('8')
  })
})

// ---------------------------------------------------------------------------
// GeometryImportProgress — SSR rendering
// ---------------------------------------------------------------------------

describe('GeometryImportProgress', () => {
  it('renders without crashing in uploading state', () => {
    expect(() =>
      renderToStaticMarkup(
        <GeometryImportProgress
          filename="part.iges"
          format="IGES 5.3"
          status="uploading"
          progress={45}
        />
      )
    ).not.toThrow()
  })

  it('shows filename', () => {
    const html = renderToStaticMarkup(
      <GeometryImportProgress filename="part.iges" format="IGES 5.3" status="uploading" progress={45} />
    )
    expect(html).toContain('part.iges')
  })

  it('shows upload progress percentage', () => {
    const html = renderToStaticMarkup(
      <GeometryImportProgress filename="part.iges" format="IGES 5.3" status="uploading" progress={45} />
    )
    expect(html).toContain('45%')
  })

  it('shows uploading message in upload state', () => {
    const html = renderToStaticMarkup(
      <GeometryImportProgress filename="part.iges" format="IGES 5.3" status="uploading" progress={20} />
    )
    expect(html).toMatch(/Uploading/i)
  })

  it('shows importing/parsing message in import state', () => {
    const html = renderToStaticMarkup(
      <GeometryImportProgress filename="assembly.step" format="STEP" status="importing" progress={100} />
    )
    expect(html).toMatch(/Parsing STEP/i)
  })

  it('shows error message in error state', () => {
    const html = renderToStaticMarkup(
      <GeometryImportProgress
        filename="bad.iges"
        format="IGES 5.3"
        status="error"
        error="Parse error: invalid DE section"
      />
    )
    expect(html).toContain('Parse error')
  })

  it('shows completed report in done state', () => {
    const html = renderToStaticMarkup(
      <GeometryImportProgress
        filename="part.iges"
        format="IGES 5.3"
        status="done"
        data={IGES_DATA}
      />
    )
    expect(html).toMatch(/IGES 5\.3 import complete/i)
  })

  it('renders progress bar track in uploading state', () => {
    const html = renderToStaticMarkup(
      <GeometryImportProgress filename="part.iges" format="IGES 5.3" status="uploading" progress={60} />
    )
    // width style should appear for the filled bar
    expect(html).toMatch(/width.*60%/)
  })
})
