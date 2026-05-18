// Slice 2: the billing page derives a per-model + storage/compute
// breakdown client-side when the backend response predates the
// `summary` field. Mirrors kerf-billing _summarize_usage.

import { describe, it, expect } from 'vitest'
import { deriveSummary } from '../cloud/BillingPanel.jsx'

describe('deriveSummary', () => {
  it('returns a zeroed summary for empty/nullish input', () => {
    const s = deriveSummary([])
    expect(s.by_model).toEqual([])
    expect(s.by_category).toEqual({ compute_usd: 0, storage_usd: 0, other_usd: 0, total_usd: 0 })
    expect(deriveSummary(null).by_category.total_usd).toBe(0)
  })

  it('groups by model and sorts by cost desc', () => {
    const s = deriveSummary([
      { model: 'claude-opus-4-7', input_tokens: 100, output_tokens: 10, usd_cost: 0.5 },
      { model: 'gpt-4o', input_tokens: 200, output_tokens: 20, usd_cost: 2.0 },
      { model: 'claude-opus-4-7', input_tokens: 50, output_tokens: 5, usd_cost: 0.25 },
    ])
    expect(s.by_model.map((m) => m.model)).toEqual(['gpt-4o', 'claude-opus-4-7'])
    const opus = s.by_model.find((m) => m.model === 'claude-opus-4-7')
    expect(opus.input_tokens).toBe(150)
    expect(opus.usd_cost).toBeCloseTo(0.75)
    expect(opus.count).toBe(2)
  })

  it('splits compute vs storage vs other', () => {
    const s = deriveSummary([
      { model: 'claude-opus-4-7', input_tokens: 10, usd_cost: 1.0, kind: 'chat' },
      { kind: 'storage', bytes_delta: 1024, usd_cost: 0.3 },
      { kind: 'render', bytes_delta: 0, usd_cost: 0.4 },
    ])
    expect(s.by_category.compute_usd).toBeCloseTo(1.0)
    expect(s.by_category.storage_usd).toBeCloseTo(0.3)
    expect(s.by_category.other_usd).toBeCloseTo(0.4)
    expect(s.by_category.total_usd).toBeCloseTo(1.7)
  })

  it('treats non-zero bytes as storage regardless of kind, and tolerates cost_usd alias', () => {
    const s = deriveSummary([{ kind: 'misc', bytes_delta: 512, cost_usd: 0.1 }])
    expect(s.by_category.storage_usd).toBeCloseTo(0.1)
    expect(s.by_category.compute_usd).toBe(0)
  })
})
