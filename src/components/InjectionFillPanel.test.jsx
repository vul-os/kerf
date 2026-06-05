/**
 * InjectionFillPanel.test.jsx
 *
 * Tests for pure helpers + basic rendering of the injection fill panel.
 * Uses renderToStaticMarkup (no @testing-library/react).
 */
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import InjectionFillPanel, {
  parseFillResult,
  riskColor,
  fmtNum,
  shortShotLabel,
} from './InjectionFillPanel.jsx'

// ---------------------------------------------------------------------------
// parseFillResult
// ---------------------------------------------------------------------------

describe('parseFillResult', () => {
  it('returns empty for blank content', () => {
    expect(parseFillResult('').kind).toBe('empty')
  })

  it('returns empty for whitespace', () => {
    expect(parseFillResult('   ').kind).toBe('empty')
  })

  it('returns invalid for malformed JSON', () => {
    expect(parseFillResult('not json').kind).toBe('invalid')
  })

  it('returns invalid when ok is false', () => {
    const r = parseFillResult(JSON.stringify({ ok: false, reason: 'fill failed' }))
    expect(r.kind).toBe('invalid')
    expect(r.error).toContain('fill failed')
  })

  it('returns invalid when fill_time_s is absent', () => {
    const r = parseFillResult(JSON.stringify({ polymer: 'ABS' }))
    expect(r.kind).toBe('invalid')
  })

  it('parses a minimal valid fill result', () => {
    const doc = { fill_time_s: 1.5, max_pressure_drop_mpa: 42.3, short_shot_risk_pct: 0 }
    const r = parseFillResult(JSON.stringify(doc))
    expect(r.kind).toBe('ok')
    expect(r.data.fill_time_s).toBe(1.5)
    expect(r.data.max_pressure_drop_mpa).toBe(42.3)
  })

  it('unwraps { result: {...} } wrapper format', () => {
    const doc = {
      tool: 'mold_injection_fill_simulate',
      result: { fill_time_s: 2.0, max_pressure_drop_mpa: 80.0, short_shot_risk_pct: 5 },
    }
    const r = parseFillResult(JSON.stringify(doc))
    expect(r.kind).toBe('ok')
    expect(r.data.fill_time_s).toBe(2.0)
  })

  it('parses full result with weld lines and air traps', () => {
    const doc = {
      fill_time_s: 1.2,
      max_pressure_drop_mpa: 55.0,
      weld_line_count: 2,
      weld_lines: [[{ x: 50, y: 30 }], [{ x: 70, y: 40 }]],
      air_trap_count: 1,
      air_traps: [{ x: 90, y: 85 }],
      short_shot_risk_pct: 0.0,
      polymer: 'ABS_Cycolac_T',
      honest_caveat: 'SIMPLIFIED 1.5D model',
    }
    const r = parseFillResult(JSON.stringify(doc))
    expect(r.kind).toBe('ok')
    expect(r.data.weld_line_count).toBe(2)
    expect(r.data.air_trap_count).toBe(1)
    expect(r.data.polymer).toBe('ABS_Cycolac_T')
  })
})

// ---------------------------------------------------------------------------
// riskColor
// ---------------------------------------------------------------------------

describe('riskColor', () => {
  it('returns green for 0 %', () => {
    expect(riskColor(0)).toBe('#34d399')
  })

  it('returns green for 5 %', () => {
    expect(riskColor(5)).toBe('#34d399')
  })

  it('returns amber for 10 %', () => {
    expect(riskColor(10)).toBe('#fbbf24')
  })

  it('returns orange for 30 %', () => {
    expect(riskColor(30)).toBe('#f97316')
  })

  it('returns red for 80 %', () => {
    expect(riskColor(80)).toBe('#f87171')
  })

  it('returns grey for null', () => {
    expect(riskColor(null)).toBe('#9ca3af')
  })

  it('returns grey for NaN', () => {
    expect(riskColor(NaN)).toBe('#9ca3af')
  })
})

// ---------------------------------------------------------------------------
// fmtNum
// ---------------------------------------------------------------------------

describe('fmtNum', () => {
  it('formats to 3 decimal places by default', () => {
    expect(fmtNum(1.5)).toBe('1.500')
  })

  it('respects digits parameter', () => {
    expect(fmtNum(42.3, 2)).toBe('42.30')
  })

  it('returns — for null', () => {
    expect(fmtNum(null)).toBe('—')
  })

  it('returns — for undefined', () => {
    expect(fmtNum(undefined)).toBe('—')
  })

  it('returns — for Infinity', () => {
    expect(fmtNum(Infinity)).toBe('—')
  })

  it('formats zero correctly', () => {
    expect(fmtNum(0, 1)).toBe('0.0')
  })
})

// ---------------------------------------------------------------------------
// shortShotLabel
// ---------------------------------------------------------------------------

describe('shortShotLabel', () => {
  it('returns Low for 0 %', () => {
    expect(shortShotLabel(0)).toBe('Low')
  })

  it('returns Low for 5 %', () => {
    expect(shortShotLabel(5)).toBe('Low')
  })

  it('returns Moderate for 15 %', () => {
    expect(shortShotLabel(15)).toBe('Moderate')
  })

  it('returns High for 35 %', () => {
    expect(shortShotLabel(35)).toBe('High')
  })

  it('returns Critical for 75 %', () => {
    expect(shortShotLabel(75)).toBe('Critical')
  })

  it('returns Unknown for null', () => {
    expect(shortShotLabel(null)).toBe('Unknown')
  })
})

// ---------------------------------------------------------------------------
// Component rendering
// ---------------------------------------------------------------------------

describe('InjectionFillPanel rendering', () => {
  it('renders empty state when content is blank', () => {
    const html = renderToStaticMarkup(InjectionFillPanel({ parsedContent: '' }))
    expect(html).toContain('No fill simulation result')
  })

  it('renders error state when JSON is invalid', () => {
    const html = renderToStaticMarkup(InjectionFillPanel({ parsedContent: 'bad json' }))
    expect(html).toContain('Could not parse')
  })

  it('renders fill time from valid result', () => {
    const doc = {
      fill_time_s: 1.5,
      max_pressure_drop_mpa: 42.3,
      weld_line_count: 0,
      air_trap_count: 0,
      short_shot_risk_pct: 0,
      polymer: 'ABS_Cycolac_T',
    }
    const html = renderToStaticMarkup(
      InjectionFillPanel({ parsedContent: JSON.stringify(doc) })
    )
    expect(html).toContain('1.500')
    expect(html).toContain('42.30')
    expect(html).toContain('Injection Fill')
  })

  it('renders polymer name when present', () => {
    const doc = { fill_time_s: 1.0, max_pressure_drop_mpa: 30.0, polymer: 'PC_Makrolon_2407', short_shot_risk_pct: 0 }
    const html = renderToStaticMarkup(
      InjectionFillPanel({ parsedContent: JSON.stringify(doc) })
    )
    expect(html).toContain('PC_Makrolon_2407')
  })

  it('renders weld line section when weld_lines present', () => {
    const doc = {
      fill_time_s: 1.2,
      max_pressure_drop_mpa: 50.0,
      weld_line_count: 1,
      weld_lines: [[{ x: 50, y: 60 }]],
      air_trap_count: 0,
      short_shot_risk_pct: 0,
    }
    const html = renderToStaticMarkup(
      InjectionFillPanel({ parsedContent: JSON.stringify(doc) })
    )
    expect(html).toContain('Weld Lines')
    expect(html).toContain('Line 1')
  })

  it('renders air trap section when air_traps present', () => {
    const doc = {
      fill_time_s: 1.0,
      max_pressure_drop_mpa: 40.0,
      weld_line_count: 0,
      air_trap_count: 1,
      air_traps: [{ x: 90, y: 85 }],
      short_shot_risk_pct: 5,
    }
    const html = renderToStaticMarkup(
      InjectionFillPanel({ parsedContent: JSON.stringify(doc) })
    )
    expect(html).toContain('Air Trap')
  })

  it('renders honest caveat when present', () => {
    const doc = {
      fill_time_s: 1.0,
      max_pressure_drop_mpa: 40.0,
      short_shot_risk_pct: 0,
      honest_caveat: 'SIMPLIFIED 1.5D model (Hieber-Shen 1980 basis)',
    }
    const html = renderToStaticMarkup(
      InjectionFillPanel({ parsedContent: JSON.stringify(doc) })
    )
    expect(html).toContain('SIMPLIFIED')
    expect(html).toContain('Hieber-Shen')
  })

  it('renders short-shot risk gauge', () => {
    const doc = { fill_time_s: 0.8, max_pressure_drop_mpa: 20.0, short_shot_risk_pct: 12.5 }
    const html = renderToStaticMarkup(
      InjectionFillPanel({ parsedContent: JSON.stringify(doc) })
    )
    expect(html).toContain('12.5')
    expect(html).toContain('Moderate')
  })

  it('accepts object prop directly', () => {
    const doc = { fill_time_s: 1.0, max_pressure_drop_mpa: 30.0, short_shot_risk_pct: 0 }
    const html = renderToStaticMarkup(
      InjectionFillPanel({ parsedContent: doc })
    )
    expect(html).toContain('Injection Fill')
  })
})
