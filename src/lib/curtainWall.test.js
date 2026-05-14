import { describe, it, expect } from 'vitest'
import {
  defaultCurtainWall,
  validateCurtainWall,
  computeGrid,
  generatePanels,
  generateMullions,
  setDivisionScheme,
  setPanelType,
} from './curtainWall.js'

describe('defaultCurtainWall', () => {
  it('returns version 1', () => {
    const cw = defaultCurtainWall('curve-123')
    expect(cw.version).toBe(1)
  })

  it('stores base_curve_or_wall_id', () => {
    const cw = defaultCurtainWall('curve-abc')
    expect(cw.base_curve_or_wall_id).toBe('curve-abc')
  })

  it('defaults height_mm to 3000', () => {
    const cw = defaultCurtainWall('curve-123')
    expect(cw.height_mm).toBe(3000)
  })

  it('has u_divisions and v_divisions arrays', () => {
    const cw = defaultCurtainWall('curve-123')
    expect(Array.isArray(cw.u_divisions)).toBe(true)
    expect(Array.isArray(cw.v_divisions)).toBe(true)
  })

  it('has panel_type with kind glass', () => {
    const cw = defaultCurtainWall('curve-123')
    expect(cw.panel_type.kind).toBe('glass')
  })

  it('has mullion_type with square profile', () => {
    const cw = defaultCurtainWall('curve-123')
    expect(cw.mullion_type.profile).toBe('square')
    expect(cw.mullion_type.size_mm).toBe(50)
  })
})

describe('validateCurtainWall', () => {
  it('returns ok for valid curtain wall', () => {
    const cw = defaultCurtainWall('curve-123')
    const result = validateCurtainWall(cw)
    expect(result.ok).toBe(true)
    expect(result.errors).toHaveLength(0)
  })

  it('flags missing version', () => {
    const cw = { ...defaultCurtainWall('curve-123'), version: 2 }
    const result = validateCurtainWall(cw)
    expect(result.ok).toBe(false)
    expect(result.errors.some(e => e.includes('version'))).toBe(true)
  })

  it('flags invalid height_mm', () => {
    const cw = { ...defaultCurtainWall('curve-123'), height_mm: -100 }
    const result = validateCurtainWall(cw)
    expect(result.ok).toBe(false)
    expect(result.errors.some(e => e.includes('height_mm'))).toBe(true)
  })

  it('flags invalid panel_type.kind', () => {
    const cw = { ...defaultCurtainWall('curve-123'), panel_type: { kind: 'invalid' } }
    const result = validateCurtainWall(cw)
    expect(result.ok).toBe(false)
    expect(result.errors.some(e => e.includes('panel_type.kind'))).toBe(true)
  })

  it('flags invalid mullion_type.profile', () => {
    const cw = { ...defaultCurtainWall('curve-123'), mullion_type: { profile: 'hex', size_mm: 50 } }
    const result = validateCurtainWall(cw)
    expect(result.ok).toBe(false)
    expect(result.errors.some(e => e.includes('mullion_type.profile'))).toBe(true)
  })
})

describe('computeGrid', () => {
  it('count division produces N+1 lines', () => {
    const cw = defaultCurtainWall('curve-123')
    cw.u_divisions = [{ type: 'count', value: 4 }]
    cw.v_divisions = [{ type: 'count', value: 6 }]
    const { u_lines, v_lines } = computeGrid(cw, 4000, 3000)
    expect(u_lines).toHaveLength(5)
    expect(v_lines).toHaveLength(7)
  })

  it('spacing division produces ceil(length/spacing)+1 lines', () => {
    const cw = defaultCurtainWall('curve-123')
    cw.u_divisions = [{ type: 'spacing', value: 1000 }]
    cw.v_divisions = [{ type: 'spacing', value: 750 }]
    const { u_lines, v_lines } = computeGrid(cw, 4000, 3000)
    expect(u_lines).toHaveLength(Math.ceil(4000 / 1000) + 1)
    expect(v_lines).toHaveLength(Math.ceil(3000 / 750) + 1)
  })

  it('returns u_lines and v_lines as normalized [0,1]', () => {
    const cw = defaultCurtainWall('curve-123')
    cw.u_divisions = [{ type: 'count', value: 2 }]
    cw.v_divisions = [{ type: 'count', value: 2 }]
    const { u_lines, v_lines } = computeGrid(cw, 5000, 2000)
    expect(u_lines[0]).toBe(0)
    expect(u_lines[u_lines.length - 1]).toBe(1)
    expect(v_lines[0]).toBe(0)
    expect(v_lines[v_lines.length - 1]).toBe(1)
  })
})

describe('generatePanels', () => {
  it('yields u_count * v_count panels', () => {
    const cw = defaultCurtainWall('curve-123')
    cw.u_divisions = [{ type: 'count', value: 4 }]
    cw.v_divisions = [{ type: 'count', value: 6 }]
    const panels = generatePanels(cw)
    expect(panels).toHaveLength(4 * 6)
  })

  it('panel bounds are [[u0,v0],[u1,v1]]', () => {
    const cw = defaultCurtainWall('curve-123')
    cw.u_divisions = [{ type: 'count', value: 2 }]
    cw.v_divisions = [{ type: 'count', value: 2 }]
    const panels = generatePanels(cw)
    for (const p of panels) {
      expect(p.bounds).toHaveLength(2)
      expect(p.bounds[0]).toHaveLength(2)
      expect(p.bounds[1]).toHaveLength(2)
      expect(p.bounds[0][0]).toBeLessThan(p.bounds[1][0])
      expect(p.bounds[0][1]).toBeLessThan(p.bounds[1][1])
    }
  })

  it('panel type matches panel_type.kind', () => {
    const cw = defaultCurtainWall('curve-123')
    cw.panel_type.kind = 'solid'
    const panels = generatePanels(cw)
    expect(panels.every(p => p.type === 'solid')).toBe(true)
  })
})

describe('generateMullions', () => {
  it('mullions border every panel edge', () => {
    const cw = defaultCurtainWall('curve-123')
    cw.u_divisions = [{ type: 'count', value: 3 }]
    cw.v_divisions = [{ type: 'count', value: 2 }]
    const mullions = generateMullions(cw)
    const uMullions = mullions.filter(m => m.start[0] !== m.end[0])
    const vMullions = mullions.filter(m => m.start[2] !== m.end[2])
    expect(uMullions).toHaveLength(3)
    expect(vMullions).toHaveLength(4)
  })

  it('mullions have start and end arrays', () => {
    const cw = defaultCurtainWall('curve-123')
    const mullions = generateMullions(cw)
    for (const m of mullions) {
      expect(Array.isArray(m.start)).toBe(true)
      expect(Array.isArray(m.end)).toBe(true)
      expect(m.start).toHaveLength(3)
      expect(m.end).toHaveLength(3)
    }
  })

  it('mullions have profile and size_mm', () => {
    const cw = defaultCurtainWall('curve-123')
    cw.mullion_type.profile = 'round'
    cw.mullion_type.size_mm = 75
    const mullions = generateMullions(cw)
    for (const m of mullions) {
      expect(m.profile).toBe('round')
      expect(m.size_mm).toBe(75)
    }
  })
})

describe('setDivisionScheme', () => {
  it('returns new curtain wall (immutable)', () => {
    const cw = defaultCurtainWall('curve-123')
    const divs = [{ type: 'count', value: 5 }]
    const result = setDivisionScheme(cw, 'u', divs)
    expect(result).not.toBe(cw)
    expect(cw.u_divisions).not.toBe(divs)
  })

  it('updates u_divisions when axis is u', () => {
    const cw = defaultCurtainWall('curve-123')
    const divs = [{ type: 'count', value: 8 }]
    const result = setDivisionScheme(cw, 'u', divs)
    expect(result.u_divisions).toBe(divs)
  })

  it('updates v_divisions when axis is v', () => {
    const cw = defaultCurtainWall('curve-123')
    const divs = [{ type: 'spacing', value: 500 }]
    const result = setDivisionScheme(cw, 'v', divs)
    expect(result.v_divisions).toBe(divs)
  })

  it('throws for invalid axis', () => {
    const cw = defaultCurtainWall('curve-123')
    expect(() => setDivisionScheme(cw, 'x', [])).toThrow()
  })
})

describe('setPanelType', () => {
  it('returns new curtain wall (immutable)', () => {
    const cw = defaultCurtainWall('curve-123')
    const result = setPanelType(cw, { kind: 'solid' })
    expect(result).not.toBe(cw)
  })

  it('updates panel_type', () => {
    const cw = defaultCurtainWall('curve-123')
    const result = setPanelType(cw, { kind: 'opening', color: '#FF0000' })
    expect(result.panel_type.kind).toBe('opening')
    expect(result.panel_type.color).toBe('#FF0000')
  })

  it('preserves existing panel_type fields', () => {
    const cw = defaultCurtainWall('curve-123')
    cw.panel_type.material_id = 'mat-1'
    const result = setPanelType(cw, { color: '#00FF00' })
    expect(result.panel_type.material_id).toBe('mat-1')
    expect(result.panel_type.color).toBe('#00FF00')
  })
})
