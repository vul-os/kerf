import { describe, it, expect } from 'vitest'
import {
  addSubSheet,
  removeSubSheet,
  addGlobalLabel,
  addHierLabel,
  resolveSheetPin,
  flattenHierarchy,
  validateHierarchy,
} from './hierSchematic.js'

// ── Fixtures ──────────────────────────────────────────────────────────────────

function makeBoard(overrides = {}) {
  return { type: 'pcb_board', width: 100, height: 100, ...overrides }
}

// Build a minimal child board with hierarchical labels already bound.
function makeChildBoard(sheet_id, labels = []) {
  const board = makeBoard()
  board.hierarchical_labels = labels.map(({ name, net_id }) => ({
    name, net_id, sheet_id,
  }))
  return board
}

// ── addSubSheet ───────────────────────────────────────────────────────────────

describe('addSubSheet', () => {
  it('adds a sub_sheet with a generated id', () => {
    const c = addSubSheet(makeBoard(), { name: 'Power', file_id: 'fid-1', position: [10, 20] })
    expect(c.sub_sheets).toHaveLength(1)
    expect(c.sub_sheets[0].name).toBe('Power')
    expect(c.sub_sheets[0].file_id).toBe('fid-1')
    expect(typeof c.sub_sheets[0].id).toBe('string')
    expect(c.sub_sheets[0].id).toMatch(/^[0-9a-f-]{36}$/)
  })

  it('stores pins on the sub_sheet', () => {
    const pins = [{ name: 'VIN', type: 'input', net_id: 'net-vin' }]
    const c = addSubSheet(makeBoard(), { name: 'PSU', file_id: 'fid-2', pins })
    expect(c.sub_sheets[0].pins).toEqual(pins)
  })

  it('does not mutate the original circuit', () => {
    const orig = makeBoard()
    addSubSheet(orig, { name: 'X', file_id: 'f' })
    expect(orig.sub_sheets).toBeUndefined()
  })

  it('throws when name is missing', () => {
    expect(() => addSubSheet(makeBoard(), { file_id: 'f' })).toThrow('name is required')
  })

  it('throws when file_id is missing', () => {
    expect(() => addSubSheet(makeBoard(), { name: 'X' })).toThrow('file_id is required')
  })

  it('accumulates multiple sub_sheets', () => {
    let c = addSubSheet(makeBoard(), { name: 'A', file_id: 'fa' })
    c = addSubSheet(c, { name: 'B', file_id: 'fb' })
    expect(c.sub_sheets).toHaveLength(2)
  })
})

// ── removeSubSheet ────────────────────────────────────────────────────────────

describe('removeSubSheet', () => {
  it('removes the specified sub_sheet', () => {
    let c = addSubSheet(makeBoard(), { name: 'A', file_id: 'fa' })
    const sid = c.sub_sheets[0].id
    c = addSubSheet(c, { name: 'B', file_id: 'fb' })
    c = removeSubSheet(c, sid)
    expect(c.sub_sheets).toHaveLength(1)
    expect(c.sub_sheets[0].name).toBe('B')
  })

  it('also removes dangling hierarchical_labels for that sheet', () => {
    let c = addSubSheet(makeBoard(), { name: 'A', file_id: 'fa' })
    const sid = c.sub_sheets[0].id
    c = addHierLabel(c, 'VOUT', 'net-1', sid)
    c = removeSubSheet(c, sid)
    expect(c.hierarchical_labels).toHaveLength(0)
  })

  it('does not affect hierarchical_labels for other sheets', () => {
    let c = addSubSheet(makeBoard(), { name: 'A', file_id: 'fa' })
    const sid1 = c.sub_sheets[0].id
    c = addSubSheet(c, { name: 'B', file_id: 'fb' })
    const sid2 = c.sub_sheets[1].id
    c = addHierLabel(c, 'SIG', 'net-sig', sid2)
    c = removeSubSheet(c, sid1)
    expect(c.hierarchical_labels).toHaveLength(1)
    expect(c.hierarchical_labels[0].sheet_id).toBe(sid2)
  })
})

// ── addGlobalLabel ────────────────────────────────────────────────────────────

describe('addGlobalLabel', () => {
  it('adds a global label', () => {
    const c = addGlobalLabel(makeBoard(), 'GND', 'net-gnd')
    expect(c.global_labels).toEqual([{ name: 'GND', net_id: 'net-gnd' }])
  })

  it('updates an existing global label with same name', () => {
    let c = addGlobalLabel(makeBoard(), 'VCC', 'net-vcc-old')
    c = addGlobalLabel(c, 'VCC', 'net-vcc-new')
    expect(c.global_labels).toHaveLength(1)
    expect(c.global_labels[0].net_id).toBe('net-vcc-new')
  })

  it('propagates across three sheets sharing a name', () => {
    // Simulate three independent boards, each with a GND global label
    const b1 = addGlobalLabel(makeBoard(), 'GND', 'net-gnd-1')
    const b2 = addGlobalLabel(makeBoard(), 'GND', 'net-gnd-2')
    const b3 = addGlobalLabel(makeBoard(), 'GND', 'net-gnd-3')

    // Flatten: all three GND labels should land in the same group
    let top = addSubSheet(makeBoard(), { name: 'B2', file_id: 'f2' })
    top = addGlobalLabel(top, 'GND', 'net-gnd-top')
    const sid = top.sub_sheets[0].id

    // Child has GND too
    const child = addGlobalLabel(makeBoard(), 'GND', 'net-gnd-child')

    const { net_groups } = flattenHierarchy(top, { f2: child })
    // Both GND nets should be in the same group (via the __global__::GND node)
    const gndGroup = net_groups.find(g =>
      g.some(k => k.includes('net-gnd-top')) && g.some(k => k.includes('net-gnd-child'))
    )
    expect(gndGroup).toBeDefined()
    void b1, b2, b3 // suppress unused warnings
  })
})

// ── addHierLabel ──────────────────────────────────────────────────────────────

describe('addHierLabel', () => {
  it('adds a hierarchical label', () => {
    const c = addHierLabel(makeBoard(), 'VOUT', 'net-vout', 'sh1')
    expect(c.hierarchical_labels).toEqual([{ name: 'VOUT', net_id: 'net-vout', sheet_id: 'sh1' }])
  })

  it('updates an existing hier label with same name+sheet_id', () => {
    let c = addHierLabel(makeBoard(), 'VOUT', 'net-old', 'sh1')
    c = addHierLabel(c, 'VOUT', 'net-new', 'sh1')
    expect(c.hierarchical_labels).toHaveLength(1)
    expect(c.hierarchical_labels[0].net_id).toBe('net-new')
  })

  it('does NOT propagate to sheets that do not match sheet_id', () => {
    let c = addHierLabel(makeBoard(), 'VOUT', 'net-vout', 'sh-power')
    c = addHierLabel(c, 'VOUT', 'net-vout-other', 'sh-motor')
    // Both labels coexist — they are for different sheet instances
    expect(c.hierarchical_labels).toHaveLength(2)
    expect(c.hierarchical_labels.find(l => l.sheet_id === 'sh-power').net_id).toBe('net-vout')
    expect(c.hierarchical_labels.find(l => l.sheet_id === 'sh-motor').net_id).toBe('net-vout-other')
  })
})

// ── resolveSheetPin ───────────────────────────────────────────────────────────

describe('resolveSheetPin', () => {
  it('resolves matching pin → hierarchical label pair', () => {
    let parent = addSubSheet(makeBoard(), {
      name: 'PSU',
      file_id: 'f-psu',
      pins: [{ name: 'VOUT', type: 'output', net_id: 'net-vout-parent' }],
    })
    const sid = parent.sub_sheets[0].id
    const child = makeChildBoard(sid, [{ name: 'VOUT', net_id: 'net-vout-child' }])

    const res = resolveSheetPin(parent, sid, 'VOUT', child)
    expect(res).toEqual({ parent_net_id: 'net-vout-parent', child_net_id: 'net-vout-child' })
  })

  it('returns null when pin does not exist', () => {
    let parent = addSubSheet(makeBoard(), { name: 'PSU', file_id: 'f-psu', pins: [] })
    const sid = parent.sub_sheets[0].id
    const child = makeBoard()
    expect(resolveSheetPin(parent, sid, 'MISSING', child)).toBeNull()
  })

  it('returns null when sub_sheet_id does not exist', () => {
    const parent = makeBoard()
    const child = makeBoard()
    expect(resolveSheetPin(parent, 'nonexistent', 'ANY', child)).toBeNull()
  })
})

// ── flattenHierarchy ──────────────────────────────────────────────────────────

describe('flattenHierarchy', () => {
  it('merges parent pin net with child hier label net', () => {
    let top = addSubSheet(makeBoard(), {
      name: 'PSU',
      file_id: 'f-psu',
      pins: [{ name: 'VOUT', type: 'output', net_id: 'net-parent-vout' }],
    })
    const sid = top.sub_sheets[0].id
    const child = makeChildBoard(sid, [{ name: 'VOUT', net_id: 'net-child-vout' }])

    const { net_groups } = flattenHierarchy(top, { 'f-psu': child })
    const group = net_groups.find(g =>
      g.some(k => k.includes('net-parent-vout')) &&
      g.some(k => k.includes('net-child-vout'))
    )
    expect(group).toBeDefined()
  })

  it('global labels from parent and child end up in same group', () => {
    let top = addGlobalLabel(makeBoard(), 'GND', 'top-gnd')
    top = addSubSheet(top, { name: 'Sub', file_id: 'fsub' })
    const child = addGlobalLabel(makeBoard(), 'GND', 'child-gnd')

    const { net_groups } = flattenHierarchy(top, { fsub: child })
    const gndGroup = net_groups.find(g =>
      g.some(k => k.includes('top-gnd')) && g.some(k => k.includes('child-gnd'))
    )
    expect(gndGroup).toBeDefined()
  })

  it('different global label names do NOT merge', () => {
    let top = addGlobalLabel(makeBoard(), 'GND', 'top-gnd')
    top = addGlobalLabel(top, 'VCC', 'top-vcc')

    const { net_groups } = flattenHierarchy(top, {})
    const gndGroup = net_groups.find(g => g.some(k => k.includes('top-gnd')))
    const vccGroup = net_groups.find(g => g.some(k => k.includes('top-vcc')))
    // GND and VCC must not be in the same group
    expect(gndGroup).toBeDefined()
    expect(vccGroup).toBeDefined()
    expect(gndGroup).not.toBe(vccGroup)
  })

  it('handles missing child gracefully (skips that sheet)', () => {
    let top = addSubSheet(makeBoard(), { name: 'Missing', file_id: 'f-missing' })
    expect(() => flattenHierarchy(top, {})).not.toThrow()
  })

  it('three-tier hierarchy: top → mid → leaf all merged', () => {
    // top has GND, mid sub-sheet (file_id: f-mid) also has GND, leaf (file_id: f-leaf) also GND
    let top = addGlobalLabel(makeBoard(), 'GND', 'gnd-top')
    top = addSubSheet(top, { name: 'Mid', file_id: 'f-mid' })

    let mid = addGlobalLabel(makeBoard(), 'GND', 'gnd-mid')
    mid = addSubSheet(mid, { name: 'Leaf', file_id: 'f-leaf' })

    const leaf = addGlobalLabel(makeBoard(), 'GND', 'gnd-leaf')

    const { net_groups } = flattenHierarchy(top, { 'f-mid': mid, 'f-leaf': leaf })

    const bigGroup = net_groups.find(g =>
      g.some(k => k.includes('gnd-top')) &&
      g.some(k => k.includes('gnd-mid')) &&
      g.some(k => k.includes('gnd-leaf'))
    )
    expect(bigGroup).toBeDefined()
  })

  it('hier label only propagates through the matching sheet_id, not another', () => {
    let top = makeBoard()
    top = addSubSheet(top, { name: 'A', file_id: 'fa', pins: [{ name: 'SIG', type: 'output', net_id: 'net-sig-a' }] })
    top = addSubSheet(top, { name: 'B', file_id: 'fb', pins: [{ name: 'SIG', type: 'input', net_id: 'net-sig-b' }] })

    const sidA = top.sub_sheets[0].id
    const sidB = top.sub_sheets[1].id

    const childA = makeChildBoard(sidA, [{ name: 'SIG', net_id: 'child-a-sig' }])
    const childB = makeChildBoard(sidB, [{ name: 'SIG', net_id: 'child-b-sig' }])

    const { net_groups } = flattenHierarchy(top, { fa: childA, fb: childB })

    // net-sig-a must be with child-a-sig but NOT with child-b-sig
    const groupA = net_groups.find(g => g.some(k => k.includes('net-sig-a')))
    expect(groupA.some(k => k.includes('child-a-sig'))).toBe(true)
    expect(groupA.some(k => k.includes('child-b-sig'))).toBe(false)
  })
})

// ── validateHierarchy ─────────────────────────────────────────────────────────

describe('validateHierarchy', () => {
  it('returns ok:true for a valid hierarchy', () => {
    let top = addSubSheet(makeBoard(), {
      name: 'PSU',
      file_id: 'f-psu',
      pins: [{ name: 'VOUT', type: 'output', net_id: 'net-vout' }],
    })
    const sid = top.sub_sheets[0].id
    const child = makeChildBoard(sid, [{ name: 'VOUT', net_id: 'net-vout-child' }])

    const result = validateHierarchy(top, { 'f-psu': child })
    expect(result.ok).toBe(true)
    expect(result.errors).toHaveLength(0)
  })

  it('reports missing child (file_id not in map)', () => {
    const top = addSubSheet(makeBoard(), { name: 'Ghost', file_id: 'f-ghost' })
    const result = validateHierarchy(top, {})
    expect(result.ok).toBe(false)
    expect(result.errors.some(e => e.includes('f-ghost'))).toBe(true)
  })

  it('reports orphaned hierarchical_label (label with no matching pin)', () => {
    let top = addSubSheet(makeBoard(), { name: 'PSU', file_id: 'f-psu', pins: [] })
    const sid = top.sub_sheets[0].id
    // Child has a hier label for this sheet but parent has no matching pin
    const child = makeChildBoard(sid, [{ name: 'ORPHAN', net_id: 'net-orphan' }])

    const result = validateHierarchy(top, { 'f-psu': child })
    expect(result.ok).toBe(false)
    expect(result.errors.some(e => e.includes('ORPHAN'))).toBe(true)
  })

  it('reports pin with no matching hierarchical_label in child', () => {
    let top = addSubSheet(makeBoard(), {
      name: 'PSU',
      file_id: 'f-psu',
      pins: [{ name: 'ENABLE', type: 'input', net_id: 'net-en' }],
    })
    const sid = top.sub_sheets[0].id
    // Child has NO hier labels
    const child = makeBoard()

    const result = validateHierarchy(top, { 'f-psu': child })
    expect(result.ok).toBe(false)
    expect(result.errors.some(e => e.includes('ENABLE'))).toBe(true)
  })

  it('reports global label name collision on same sheet', () => {
    let board = addGlobalLabel(makeBoard(), 'GND', 'net-gnd-a')
    // Manually insert a second GND entry with different net_id
    board.global_labels.push({ name: 'GND', net_id: 'net-gnd-b' })

    const result = validateHierarchy(board, {})
    expect(result.ok).toBe(false)
    expect(result.errors.some(e => e.includes('GND') && e.includes('conflict'))).toBe(true)
  })

  it('passes a three-tier hierarchy with no errors', () => {
    let top = addGlobalLabel(makeBoard(), 'GND', 'gnd-top')
    top = addSubSheet(top, { name: 'Mid', file_id: 'f-mid', pins: [{ name: 'PWR', type: 'output', net_id: 'mid-pwr' }] })
    const topSid = top.sub_sheets[0].id

    let mid = addGlobalLabel(makeBoard(), 'GND', 'gnd-mid')
    mid = makeChildBoard(topSid, [{ name: 'PWR', net_id: 'mid-pwr-local' }])
    mid = { ...mid, ...addGlobalLabel(mid, 'GND', 'gnd-mid-net') }

    const result = validateHierarchy(top, { 'f-mid': mid })
    expect(result.ok).toBe(true)
  })
})
