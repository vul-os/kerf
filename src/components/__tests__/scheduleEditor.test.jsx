// scheduleEditor.test.jsx — Pure data-layer tests for ScheduleEditor helpers.

import { describe, it, expect } from 'vitest'
import {
  defaultSchedule,
  validateSchedule,
  runSchedule,
} from '../../lib/schedule.js'

// Minimal BIM doc fixture.
function makeBim() {
  return {
    elements: [
      { id: 'w1', category: 'Wall', type: 'Wall', thickness: 200, level: 'L1' },
      { id: 'w2', category: 'Wall', type: 'Wall', thickness: 100, level: 'L1' },
      { id: 'w3', category: 'Wall', type: 'Wall', thickness: 300, level: 'L2' },
    ],
  }
}

// ── 1. defaultSchedule ────────────────────────────────────────────────────────

describe('defaultSchedule', () => {
  it('returns a valid schedule', () => {
    const { ok } = validateSchedule(defaultSchedule())
    expect(ok).toBe(true)
  })

  it('has empty filters and columns', () => {
    const s = defaultSchedule()
    expect(s.filters).toHaveLength(0)
    expect(s.columns).toHaveLength(0)
  })
})

// ── 2. validateSchedule ───────────────────────────────────────────────────────

describe('validateSchedule', () => {
  it('rejects null', () => {
    const { ok } = validateSchedule(null)
    expect(ok).toBe(false)
  })

  it('rejects invalid target_category', () => {
    const s = { ...defaultSchedule(), target_category: 'Spaceship' }
    const { ok } = validateSchedule(s)
    expect(ok).toBe(false)
  })

  it('rejects missing name', () => {
    const s = { ...defaultSchedule(), name: '' }
    const { ok, errors } = validateSchedule(s)
    expect(ok).toBe(false)
    expect(errors.some((e) => /name/.test(e))).toBe(true)
  })
})

// ── 3. runSchedule ────────────────────────────────────────────────────────────

describe('runSchedule', () => {
  it('returns empty result when either arg is null', () => {
    const r = runSchedule(null, null)
    expect(r.columns).toHaveLength(0)
    expect(r.rows).toHaveLength(0)
  })

  it('returns all matching elements when no filter', () => {
    const s = {
      ...defaultSchedule(),
      target_category: 'Wall',
      columns: [{ field: 'id' }],
    }
    const r = runSchedule(s, makeBim())
    expect(r.rows.flat()).toHaveLength(3)
  })

  it('filters by field eq', () => {
    const s = {
      ...defaultSchedule(),
      target_category: 'Wall',
      filters: [{ field: 'level', op: 'eq', value: 'L2' }],
      columns: [{ field: 'id' }],
    }
    const r = runSchedule(s, makeBim())
    expect(r.rows.flat()).toHaveLength(1)
    expect(r.rows.flat()[0].id).toBe('w3')
  })

  it('filters by numeric gt', () => {
    const s = {
      ...defaultSchedule(),
      target_category: 'Wall',
      filters: [{ field: 'thickness', op: 'gt', value: 150 }],
      columns: [{ field: 'id' }],
    }
    const r = runSchedule(s, makeBim())
    // thickness > 150 → w1 (200) and w3 (300)
    expect(r.rows.flat()).toHaveLength(2)
  })

  it('exposes columns with label fallback to field', () => {
    const s = {
      ...defaultSchedule(),
      target_category: 'Wall',
      columns: [{ field: 'thickness', label: 'Thickness' }],
    }
    const r = runSchedule(s, makeBim())
    expect(r.columns[0].label).toBe('Thickness')
  })
})
