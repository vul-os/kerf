import { describe, it, expect } from 'vitest'
import {
  defaultSchedule,
  runSchedule,
  validateSchedule,
} from './schedule.js'

describe('defaultSchedule', () => {
  it('returns version 1 schedule with defaults', () => {
    const s = defaultSchedule()
    expect(s.version).toBe(1)
    expect(s.name).toBe("Untitled Schedule")
    expect(s.target_category).toBe("Wall")
    expect(s.filters).toEqual([])
    expect(s.columns).toEqual([])
    expect(s.group_by).toBeNull()
    expect(s.sort_by).toBeNull()
  })
})

describe('validateSchedule', () => {
  it('passes a valid schedule', () => {
    const s = {
      version: 1,
      name: "Test",
      target_category: "Wall",
      filters: [],
      columns: [{ field: "height" }],
    }
    const { ok, errors } = validateSchedule(s)
    expect(ok).toBe(true)
    expect(errors).toHaveLength(0)
  })

  it('fails for null schedule', () => {
    const { ok, errors } = validateSchedule(null)
    expect(ok).toBe(false)
    expect(errors.length).toBeGreaterThan(0)
  })

  it('fails for wrong version', () => {
    const s = { version: 2, name: "Test", target_category: "Wall", filters: [], columns: [] }
    const { ok, errors } = validateSchedule(s)
    expect(ok).toBe(false)
    expect(errors.some(e => e.includes("version"))).toBe(true)
  })

  it('fails for missing name', () => {
    const s = { version: 1, name: "", target_category: "Wall", filters: [], columns: [] }
    const { ok, errors } = validateSchedule(s)
    expect(ok).toBe(false)
    expect(errors.some(e => e.includes("name"))).toBe(true)
  })

  it('fails for invalid target_category', () => {
    const s = { version: 1, name: "Test", target_category: "Invalid", filters: [], columns: [] }
    const { ok, errors } = validateSchedule(s)
    expect(ok).toBe(false)
    expect(errors.some(e => e.includes("target_category"))).toBe(true)
  })

  it('fails for invalid filter op', () => {
    const s = {
      version: 1, name: "Test", target_category: "Wall",
      filters: [{ field: "height", op: "invalid", value: 100 }],
      columns: [],
    }
    const { ok, errors } = validateSchedule(s)
    expect(ok).toBe(false)
    expect(errors.some(e => e.includes("op"))).toBe(true)
  })

  it('fails for columns without field', () => {
    const s = {
      version: 1, name: "Test", target_category: "Wall",
      filters: [],
      columns: [{ label: "Height" }],
    }
    const { ok, errors } = validateSchedule(s)
    expect(ok).toBe(false)
    expect(errors.some(e => e.includes("field"))).toBe(true)
  })

  it('accepts all valid filter operators', () => {
    const ops = ["eq", "ne", "gt", "lt", "gte", "lte", "in", "contains"]
    for (const op of ops) {
      const s = {
        version: 1, name: "Test", target_category: "Wall",
        filters: [{ field: "height", op, value: 100 }],
        columns: [{ field: "height" }],
      }
      const { ok } = validateSchedule(s)
      expect(ok).toBe(true)
    }
  })
})

describe('runSchedule', () => {
  const bimDoc = {
    elements: [
      { type: "Wall", name: "W1", height: 3000, thickness: 200, material: "Concrete" },
      { type: "Wall", name: "W2", height: 3000, thickness: 150, material: "Brick" },
      { type: "Wall", name: "W3", height: 4000, thickness: 200, material: "Concrete" },
      { type: "Door", name: "D1", width: 900, height: 2100 },
      { type: "Door", name: "D2", width: 800, height: 2100 },
    ],
  }

  it('returns empty for null inputs', () => {
    const r = runSchedule(null, null)
    expect(r.columns).toEqual([])
    expect(r.rows).toEqual([])
  })

  it('filters walls by material', () => {
    const sched = {
      version: 1,
      name: "Concrete Walls",
      target_category: "Wall",
      filters: [{ field: "material", op: "eq", value: "Concrete" }],
      columns: [{ field: "name" }, { field: "height" }, { field: "material" }],
    }
    const r = runSchedule(sched, bimDoc)
    expect(r.rows).toHaveLength(2)
    expect(r.rows[0][0].name).toBe("W1")
    expect(r.rows[0][0].material).toBe("Concrete")
    expect(r.rows[1][0].name).toBe("W3")
  })

  it('filters with gt operator', () => {
    const sched = {
      version: 1, name: "Tall Walls", target_category: "Wall",
      filters: [{ field: "height", op: "gt", value: 3000 }],
      columns: [{ field: "name" }, { field: "height" }],
    }
    const r = runSchedule(sched, bimDoc)
    expect(r.rows).toHaveLength(1)
    expect(r.rows[0][0].height).toBe(4000)
  })

  it('filters with in operator', () => {
    const sched = {
      version: 1, name: "Some Walls", target_category: "Wall",
      filters: [{ field: "thickness", op: "in", value: [150, 200] }],
      columns: [{ field: "name" }],
    }
    const r = runSchedule(sched, bimDoc)
    expect(r.rows).toHaveLength(3)
  })

  it('sorts ascending by field', () => {
    const sched = {
      version: 1, name: "Sorted", target_category: "Wall",
      filters: [],
      columns: [{ field: "name" }, { field: "thickness" }],
      sort_by: "thickness",
    }
    const r = runSchedule(sched, bimDoc)
    const thicknesses = r.rows.map(row => row[0].thickness)
    expect(thicknesses).toEqual([150, 200, 200])
  })

  it('sorts descending with direction', () => {
    const sched = {
      version: 1, name: "Sorted", target_category: "Wall",
      filters: [],
      columns: [{ field: "name" }, { field: "thickness" }],
      sort_by: "thickness:desc",
    }
    const r = runSchedule(sched, bimDoc)
    const thicknesses = r.rows.map(row => row[0].thickness)
    expect(thicknesses).toEqual([200, 200, 150])
  })

  it('groups by field', () => {
    const sched = {
      version: 1, name: "Grouped", target_category: "Wall",
      filters: [],
      columns: [{ field: "name" }, { field: "material" }],
      group_by: "material",
    }
    const r = runSchedule(sched, bimDoc)
    expect(r.rows).toHaveLength(2)
  })

  it('tolerates missing fields with null', () => {
    const bim = {
      elements: [{ type: "Wall", name: "W1" }],
    }
    const sched = {
      version: 1, name: "Test", target_category: "Wall",
      filters: [],
      columns: [{ field: "height" }],
    }
    const r = runSchedule(sched, bim)
    expect(r.rows[0][0].height).toBeNull()
  })

  it('uses column label when provided', () => {
    const sched = {
      version: 1, name: "Test", target_category: "Wall",
      filters: [],
      columns: [{ field: "name", label: "Wall Name" }],
    }
    const r = runSchedule(sched, bimDoc)
    expect(r.columns[0].label).toBe("Wall Name")
  })

  it('defaults missing label to field name', () => {
    const sched = {
      version: 1, name: "Test", target_category: "Wall",
      filters: [],
      columns: [{ field: "name" }],
    }
    const r = runSchedule(sched, bimDoc)
    expect(r.columns[0].label).toBe("name")
  })

  it('filters with contains operator on string', () => {
    const sched = {
      version: 1, name: "Test", target_category: "Wall",
      filters: [{ field: "material", op: "contains", value: "Brick" }],
      columns: [{ field: "name" }],
    }
    const r = runSchedule(sched, bimDoc)
    expect(r.rows).toHaveLength(1)
    expect(r.rows[0][0].name).toBe("W2")
  })

  it('handles nested field paths', () => {
    const bim = {
      elements: [
        { type: "Wall", name: "W1", geometry: { area: 15 } },
      ],
    }
    const sched = {
      version: 1, name: "Test", target_category: "Wall",
      filters: [],
      columns: [{ field: "geometry.area" }],
    }
    const r = runSchedule(sched, bim)
    expect(r.rows[0][0]["geometry.area"]).toBe(15)
  })
})