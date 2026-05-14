// hierSheetPicker.test.jsx — Vitest assertions for HierSheetPicker helpers.
//
// Pure data-layer tests: verifies getSubSheets and getSubSheetDisplay logic
// without React render overhead.

import { describe, it, expect } from 'vitest'
import { getSubSheets, getSubSheetDisplay } from '../HierSheetPicker.jsx'

// ── getSubSheets ──────────────────────────────────────────────────────────────

describe('getSubSheets', () => {
  it('returns empty array when circuitJson is undefined', () => {
    expect(getSubSheets(undefined)).toHaveLength(0)
  })

  it('returns empty array when circuitJson is null', () => {
    expect(getSubSheets(null)).toHaveLength(0)
  })

  it('returns empty array when board is missing', () => {
    expect(getSubSheets({})).toHaveLength(0)
  })

  it('returns empty array when board.sub_sheets is missing', () => {
    expect(getSubSheets({ board: {} })).toHaveLength(0)
  })

  it('returns the sub_sheets array when present', () => {
    const sheets = [{ name: 'psu', file_id: 'fid1' }]
    expect(getSubSheets({ board: { sub_sheets: sheets } })).toBe(sheets)
  })
})

// ── getSubSheetDisplay ─────────────────────────────────────────────────────────

describe('getSubSheetDisplay', () => {
  it('handles empty sub-sheet gracefully', () => {
    const display = getSubSheetDisplay({})
    expect(display.name).toBe('Unnamed')
    expect(display.sheetId).toBe('')
    expect(display.pinCount).toBe(0)
    expect(display.fileId).toBe('')
  })

  it('extracts name, sheet_id, and file_id', () => {
    const display = getSubSheetDisplay({
      name: 'Power Supply',
      sheet_id: 'sheet-42',
      file_id: 'fid-abc',
    })
    expect(display.name).toBe('Power Supply')
    expect(display.sheetId).toBe('sheet-42')
    expect(display.fileId).toBe('fid-abc')
  })

  it('falls back to id when sheet_id is absent', () => {
    const display = getSubSheetDisplay({ id: 'id-only' })
    expect(display.sheetId).toBe('id-only')
  })

  it('counts pins correctly when pins array exists', () => {
    const display = getSubSheetDisplay({
      pins: ['p1', 'p2', 'p3', 'p4', 'p5'],
    })
    expect(display.pinCount).toBe(5)
  })

  it('returns zero pin count when pins is not an array', () => {
    const display = getSubSheetDisplay({ pins: null })
    expect(display.pinCount).toBe(0)
  })

  it('returns zero pin count when pins is missing', () => {
    const display = getSubSheetDisplay({})
    expect(display.pinCount).toBe(0)
  })
})