/**
 * eTextilesPanel.test.jsx
 *
 * Source-level + pure-helper tests for ETextilesPanel.
 */

import { describe, it, expect } from 'vitest'
// @ts-expect-error - no @types/node in this toolchain
import { existsSync, readFileSync } from 'fs'
// @ts-expect-error - no @types/node in this toolchain
import { fileURLToPath } from 'url'
// @ts-expect-error - no @types/node in this toolchain
import { resolve, dirname } from 'path'

import {
  parseETextilesResult,
  fmtWatts,
  fmtOhms,
  fmtMilliamps,
} from '../ETextilesPanel.jsx'

const __dirname = dirname(fileURLToPath(import.meta.url))

// Extension-agnostic source read: components migrate from .jsx to .tsx one
// at a time (T-513..T-517), so a literal `.jsx` path here would break the
// moment its target is renamed. Try .tsx first, then fall back to .jsx.
const ETEXTILES_TSX = resolve(__dirname, '../ETextilesPanel.tsx')
const ETEXTILES_JSX = (existsSync(resolve(__dirname, '../ETextilesPanel.tsx')) ? resolve(__dirname, '../ETextilesPanel.tsx') : resolve(__dirname, '../ETextilesPanel.jsx'))
const SRC = readFileSync(
  existsSync(ETEXTILES_TSX) ? ETEXTILES_TSX : ETEXTILES_JSX,
  'utf8',
)

// ---------------------------------------------------------------------------
// Source structure
// ---------------------------------------------------------------------------

describe('ETextilesPanel — source structure', () => {
  it('exports default function ETextilesPanel', () => {
    expect(SRC).toMatch(/export default function ETextilesPanel/)
  })

  it('has data-testid for empty state', () => {
    expect(SRC).toMatch(/data-testid="etextiles-panel-empty"/)
  })

  it('has data-testid for error state', () => {
    expect(SRC).toMatch(/data-testid="etextiles-panel-error"/)
  })

  it('has data-testid for main panel', () => {
    expect(SRC).toMatch(/data-testid="etextiles-panel"/)
  })

  it('has data-testid for heater view', () => {
    expect(SRC).toMatch(/data-testid="etextiles-heater-view"/)
  })

  it('has data-testid for LED layout view', () => {
    expect(SRC).toMatch(/data-testid="etextiles-led-layout-view"/)
  })

  it('has data-testid for stat grid', () => {
    expect(SRC).toMatch(/data-testid="etextiles-stat-grid"/)
  })

  it('has data-testid for mode label', () => {
    expect(SRC).toMatch(/data-testid="etextiles-mode-label"/)
  })

  it('exports parse and format helpers', () => {
    expect(SRC).toMatch(/export function parseETextilesResult/)
    expect(SRC).toMatch(/export function fmtWatts/)
    expect(SRC).toMatch(/export function fmtOhms/)
    expect(SRC).toMatch(/export function fmtMilliamps/)
  })
})

// ---------------------------------------------------------------------------
// parseETextilesResult
// ---------------------------------------------------------------------------

describe('parseETextilesResult', () => {
  it('returns empty for null', () => {
    expect(parseETextilesResult(null).kind).toBe('empty')
  })

  it('returns invalid for ok:false', () => {
    const r = parseETextilesResult({ ok: false, error: 'missing mode' })
    expect(r.kind).toBe('invalid')
  })

  it('returns invalid for explicit error key', () => {
    const r = parseETextilesResult({ error: 'bad mode' })
    expect(r.kind).toBe('invalid')
  })

  it('returns invalid when mode is missing', () => {
    const r = parseETextilesResult({ ok: true, resistance_ohm: 10 })
    expect(r.kind).toBe('invalid')
  })

  it('parses heater result', () => {
    // `r` is a discriminated union; `expect().toBe()` doesn't narrow it for TS,
    // so we probe at runtime via `any` here rather than the compiler.
    const r: any = parseETextilesResult({
      ok: true,
      mode: 'heater',
      resistance_ohm: 10.0,
      power_w: 2.5,
      voltage_drop_v: 5.0,
      length_m: 1.0,
    })
    expect(r.kind).toBe('ok')
    expect(r.mode).toBe('heater')
    expect(r.data.resistance_ohm).toBe(10.0)
  })

  it('parses LED layout result', () => {
    // See note above: probing a discriminated union via runtime assertions.
    const r: any = parseETextilesResult({
      ok: true,
      mode: 'led_layout',
      n_branches: 3,
      total_leds: 3,
      total_current_a: 0.06,
      total_power_w: 0.3,
      branch_currents_a: [0.02, 0.02, 0.02],
    })
    expect(r.kind).toBe('ok')
    expect(r.mode).toBe('led_layout')
    expect(r.data.n_branches).toBe(3)
  })

  it('accepts JSON string input', () => {
    const raw = JSON.stringify({ ok: true, mode: 'heater', resistance_ohm: 5.0 })
    // See note above: probing a discriminated union via runtime assertions.
    const r: any = parseETextilesResult(raw)
    expect(r.kind).toBe('ok')
    expect(r.mode).toBe('heater')
  })
})

// ---------------------------------------------------------------------------
// fmtWatts
// ---------------------------------------------------------------------------

describe('fmtWatts', () => {
  it('formats 2.5 W to 3dp', () => {
    expect(fmtWatts(2.5)).toBe('2.500 W')
  })

  it('returns — for null', () => {
    expect(fmtWatts(null)).toBe('—')
  })

  it('returns — for NaN', () => {
    expect(fmtWatts(NaN)).toBe('—')
  })
})

// ---------------------------------------------------------------------------
// fmtOhms
// ---------------------------------------------------------------------------

describe('fmtOhms', () => {
  it('formats 10.0 Ω to 3dp', () => {
    expect(fmtOhms(10.0)).toBe('10.000 Ω')
  })

  it('returns — for null', () => {
    expect(fmtOhms(null)).toBe('—')
  })
})

// ---------------------------------------------------------------------------
// fmtMilliamps
// ---------------------------------------------------------------------------

describe('fmtMilliamps', () => {
  it('converts 0.02 A to 20.0 mA', () => {
    expect(fmtMilliamps(0.02)).toBe('20.0 mA')
  })

  it('converts 0.5 A to 500.0 mA', () => {
    expect(fmtMilliamps(0.5)).toBe('500.0 mA')
  })

  it('returns — for null', () => {
    expect(fmtMilliamps(null)).toBe('—')
  })
})
