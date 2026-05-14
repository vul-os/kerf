// draft.test.js
import { describe, it, expect, beforeEach } from 'vitest'
import {
  defaultDraft, validateDraft, addEntity, removeEntity,
  moveEntity, offsetEntity, trimEntity, filletCorner,
  patternLinear, patternPolar, exportDXF
} from './draft.js'

describe('defaultDraft', () => {
  it('returns version 1 with empty entities', () => {
    const d = defaultDraft('Test')
    expect(d.version).toBe(1)
    expect(d.name).toBe('Test')
    expect(d.scale).toBe(1.0)
    expect(d.entities).toEqual([])
  })
})

describe('validateDraft', () => {
  it('accepts a valid draft', () => {
    const d = defaultDraft('Test')
    addEntity(d, { id: 'l1', kind: 'line', x1: 0, y1: 0, x2: 10, y2: 0 })
    expect(validateDraft(d).ok).toBe(true)
  })

  it('rejects non-object', () => {
    expect(validateDraft(null).ok).toBe(false)
    expect(validateDraft('x').ok).toBe(false)
  })

  it('rejects wrong version', () => {
    const d = defaultDraft(); d.version = 2
    expect(validateDraft(d).ok).toBe(false)
  })

  it('rejects invalid scale', () => {
    const d = defaultDraft(); d.scale = -1
    expect(validateDraft(d).ok).toBe(false)
  })

  it('rejects duplicate entity ids', () => {
    const d = { version: 1, name: 'Test', scale: 1.0, entities: [
      { id: 'l1', kind: 'line', x1: 0, y1: 0, x2: 1, y2: 1 },
      { id: 'l1', kind: 'line', x1: 2, y1: 2, x2: 3, y2: 3 },
    ]}
    expect(validateDraft(d).ok).toBe(false)
  })

  it('rejects unknown kind', () => {
    const d = { version: 1, name: 'Test', scale: 1.0, entities: [
      { id: 'x', kind: 'unknown' }
    ]}
    expect(validateDraft(d).ok).toBe(false)
  })

  it('rejects missing id', () => {
    const d = { version: 1, name: 'Test', scale: 1.0, entities: [
      { kind: 'line', x1: 0, y1: 0, x2: 1, y2: 1 }
    ]}
    expect(validateDraft(d).ok).toBe(false)
  })
})

describe('addEntity / removeEntity', () => {
  it('adds entity with auto-id', () => {
    const d = defaultDraft()
    const e = addEntity(d, { kind: 'line', x1: 0, y1: 0, x2: 1, y2: 1 })
    expect(e.id).toBeDefined()
    expect(d.entities.length).toBe(1)
  })

  it('adds entity with provided id', () => {
    const d = defaultDraft()
    addEntity(d, { id: 'myline', kind: 'line', x1: 0, y1: 0, x2: 1, y2: 1 })
    expect(d.entities[0].id).toBe('myline')
  })

  it('rejects invalid entity', () => {
    const d = defaultDraft()
    expect(() => addEntity(d, { id: 'x', kind: 'line' })).toThrow()
  })

  it('removes entity by id', () => {
    const d = defaultDraft()
    const e = addEntity(d, { kind: 'line', x1: 0, y1: 0, x2: 1, y2: 1 })
    removeEntity(d, e.id)
    expect(d.entities).toEqual([])
  })

  it('throws on missing id for remove', () => {
    const d = defaultDraft()
    expect(() => removeEntity(d, 'nope')).toThrow()
  })
})

describe('moveEntity', () => {
  it('moves a line', () => {
    const d = defaultDraft()
    addEntity(d, { id: 'l1', kind: 'line', x1: 0, y1: 0, x2: 10, y2: 0 })
    moveEntity(d, 'l1', 5, 3)
    const l = d.entities[0]
    expect(l.x1).toBe(5); expect(l.y1).toBe(3)
    expect(l.x2).toBe(15); expect(l.y2).toBe(3)
  })

  it('moves a circle', () => {
    const d = defaultDraft()
    addEntity(d, { id: 'c1', kind: 'circle', cx: 10, cy: 20, r: 5 })
    moveEntity(d, 'c1', -3, 4)
    expect(d.entities[0].cx).toBe(7); expect(d.entities[0].cy).toBe(24)
  })

  it('throws on unknown id', () => {
    const d = defaultDraft()
    expect(() => moveEntity(d, 'nope', 1, 1)).toThrow()
  })
})

describe('offsetEntity', () => {
  it('offsets a horizontal line by 1 unit in perpendicular direction', () => {
    const d = defaultDraft()
    addEntity(d, { id: 'l1', kind: 'line', x1: 0, y1: 0, x2: 10, y2: 0 })
    const result = offsetEntity(d, 'l1', 1)
    expect(result.kind).toBe('line')
    expect(result.x1).toBeCloseTo(0); expect(result.y1).toBeCloseTo(1)
    expect(result.x2).toBeCloseTo(10); expect(result.y2).toBeCloseTo(1)
  })

  it('offsets a vertical line by 2 units in perpendicular direction', () => {
    const d = defaultDraft()
    addEntity(d, { id: 'l1', kind: 'line', x1: 0, y1: 0, x2: 0, y2: 10 })
    const result = offsetEntity(d, 'l1', 2)
    expect(result.kind).toBe('line')
    expect(result.x1).toBeCloseTo(-2); expect(result.y1).toBeCloseTo(0)
    expect(result.x2).toBeCloseTo(-2); expect(result.y2).toBeCloseTo(10)
  })

  it('returns null for non-line/polyline', () => {
    const d = defaultDraft()
    addEntity(d, { id: 'c1', kind: 'circle', cx: 0, cy: 0, r: 5 })
    expect(offsetEntity(d, 'c1', 1)).toBeNull()
  })

  it('offsets a polyline', () => {
    const d = defaultDraft()
    addEntity(d, { id: 'p1', kind: 'polyline', points: [[0, 0], [10, 0], [10, 10]] })
    const result = offsetEntity(d, 'p1', 1)
    expect(result.kind).toBe('polyline')
    expect(result.points.length).toBe(3)
  })
})

describe('trimEntity', () => {
  it('trims a line at intersection with boundary', () => {
    const d = defaultDraft()
    addEntity(d, { id: 'target', kind: 'line', x1: 0, y1: 5, x2: 20, y2: 5 })
    addEntity(d, { id: 'boundary', kind: 'line', x1: 10, y1: 0, x2: 10, y2: 20 })
    const result = trimEntity(d, 'target', 'boundary')
    expect(result.x2).toBeCloseTo(10)
    expect(result.y2).toBeCloseTo(5)
  })
})

describe('filletCorner', () => {
  it('produces a tangent arc between two lines', () => {
    const d = defaultDraft()
    addEntity(d, { id: 'l1', kind: 'line', x1: 0, y1: 0, x2: 10, y2: 0 })
    addEntity(d, { id: 'l2', kind: 'line', x1: 0, y1: 0, x2: 0, y2: 10 })
    const arc = filletCorner(d, 'l1', 'l2', 2)
    expect(arc.kind).toBe('arc')
    expect(arc.rx).toBe(2); expect(arc.ry).toBe(2)
    expect(typeof arc.cx).toBe('number')
    expect(typeof arc.cy).toBe('number')
    expect(arc.start_angle).toBeGreaterThanOrEqual(0)
    expect(arc.end_angle).toBeGreaterThanOrEqual(0)
  })

  it('returns null for parallel lines', () => {
    const d = defaultDraft()
    addEntity(d, { id: 'l1', kind: 'line', x1: 0, y1: 0, x2: 10, y2: 0 })
    addEntity(d, { id: 'l2', kind: 'line', x1: 0, y1: 1, x2: 10, y2: 1 })
    const arc = filletCorner(d, 'l1', 'l2', 2)
    expect(arc).toBeNull()
  })
})

describe('patternLinear', () => {
  it('creates count copies', () => {
    const d = defaultDraft()
    addEntity(d, { id: 'l1', kind: 'line', x1: 0, y1: 0, x2: 1, y2: 0 })
    const copies = patternLinear(d, 'l1', 3, 10, 0)
    expect(copies.length).toBe(2)
    expect(d.entities.length).toBe(3)
    expect(copies[0].x1).toBeCloseTo(10)
    expect(copies[1].x1).toBeCloseTo(20)
  })

  it('returns empty for count < 2', () => {
    const d = defaultDraft()
    addEntity(d, { id: 'l1', kind: 'line', x1: 0, y1: 0, x2: 1, y2: 0 })
    expect(patternLinear(d, 'l1', 1, 10, 0)).toEqual([])
  })
})

describe('patternPolar', () => {
  it('creates count copies around center', () => {
    const d = defaultDraft()
    addEntity(d, { id: 'l1', kind: 'line', x1: 0, y1: 0, x2: 1, y2: 0 })
    const copies = patternPolar(d, 'l1', 4, [0, 0], 360)
    expect(copies.length).toBe(3)
  })
})

describe('exportDXF', () => {
  it('produces R12 with HEADER/ENTITIES/EOF', () => {
    const d = defaultDraft()
    addEntity(d, { id: 'l1', kind: 'line', x1: 0, y1: 0, x2: 10, y2: 0 })
    const txt = exportDXF(d)
    expect(txt).toContain('SECTION')
    expect(txt).toContain('HEADER')
    expect(txt).toContain('ENTITIES')
    expect(txt).toContain('EOF')
    expect(txt).toContain('LINE')
  })

  it('emits CIRCLE entity', () => {
    const d = defaultDraft()
    addEntity(d, { id: 'c1', kind: 'circle', cx: 5, cy: 5, r: 2 })
    const txt = exportDXF(d)
    expect(txt).toContain('CIRCLE')
    expect(txt).toContain('5')
    expect(txt).toContain('2')
  })

  it('emits ARC entity', () => {
    const d = defaultDraft()
    addEntity(d, { id: 'a1', kind: 'arc', cx: 0, cy: 0, rx: 5, ry: 5, start_angle: 0, end_angle: 90 })
    const txt = exportDXF(d)
    expect(txt).toContain('ARC')
  })

  it('emits POLYLINE entity', () => {
    const d = defaultDraft()
    addEntity(d, { id: 'p1', kind: 'polyline', points: [[0, 0], [10, 0], [10, 10]] })
    const txt = exportDXF(d)
    expect(txt).toContain('POLYLINE')
    expect(txt).toContain('VERTEX')
    expect(txt).toContain('SEQEND')
  })

  it('emits TEXT entity', () => {
    const d = defaultDraft()
    addEntity(d, { id: 't1', kind: 'text', x: 0, y: 0, value: 'Hello' })
    const txt = exportDXF(d)
    expect(txt).toContain('TEXT')
    expect(txt).toContain('Hello')
  })
})
