/**
 * Settings.test.tsx — the account settings screen.
 *
 * Rendered with renderToStaticMarkup (the project's pattern; no
 * @testing-library). That renders initial state only, which is exactly right
 * for what matters here: what a provider row says about a key before anyone
 * interacts with it, and that a saved key never reaches the markup.
 */
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import type { ReactElement } from 'react'
import { KindBreakdown, ProviderRow, UsageChart } from './Settings.jsx'
import {
  formatTokens,
  formatUsd,
  formatBytes,
  providerLabel,
} from '../lib/usageFormat.js'
import type { UsageReport } from '../types/api.js'

const render = (ui: ReactElement) => renderToStaticMarkup(ui)

const noop = () => {}

describe('provider key rows', () => {
  it('shows the mask, never anything resembling a key', () => {
    const html = render(
      <ProviderRow
        provider="anthropic"
        saved={{ provider: 'anthropic', masked_key: '••••a91f', base_url: null, readable: true }}
        operatorConfigured={false}
        onSaved={noop}
      />,
    )
    expect(html).toContain('••••a91f')
    // The API contract is that a plaintext key never leaves the server. If a
    // future refactor starts echoing one into props, this is where it shows up.
    expect(html).not.toMatch(/sk-[a-zA-Z0-9]/)
  })

  it('renders the key field as a password input that browsers will not autofill', () => {
    const html = render(
      <ProviderRow provider="openai" operatorConfigured={false} onSaved={noop} />,
    )
    expect(html).toMatch(/type="password"/)
    expect(html).toMatch(/autoComplete="off"|autocomplete="off"/)
  })

  it('says the server key is in use when the user has none of their own', () => {
    const html = render(
      <ProviderRow provider="openai" operatorConfigured onSaved={noop} />,
    )
    expect(html).toContain('Using the server')
    expect(html).not.toContain('Not configured')
  })

  it('says not configured when neither the user nor the server has a key', () => {
    const html = render(
      <ProviderRow provider="gemini" operatorConfigured={false} onSaved={noop} />,
    )
    expect(html).toContain('Not configured')
  })

  it('tells the user to re-enter a key that no longer decrypts', () => {
    // Reachable by rotating jwt_secret, which operators are told to do. The
    // row must explain itself rather than looking like data loss.
    const html = render(
      <ProviderRow
        provider="anthropic"
        saved={{ provider: 'anthropic', masked_key: '', base_url: null, readable: false }}
        operatorConfigured={false}
        onSaved={noop}
      />,
    )
    expect(html).toContain('re-enter it')
    expect(html).toContain('different server secret')
  })

  it('offers Remove only for a key the user actually saved', () => {
    const withKey = render(
      <ProviderRow
        provider="anthropic"
        saved={{ provider: 'anthropic', masked_key: '••••a91f', base_url: null, readable: true }}
        operatorConfigured={false}
        onSaved={noop}
      />,
    )
    const without = render(
      <ProviderRow provider="anthropic" operatorConfigured onSaved={noop} />,
    )
    expect(withKey).toContain('Remove')
    expect(without).not.toContain('Remove')
  })

  it('pre-fills a saved base URL so it can be edited rather than retyped', () => {
    const html = render(
      <ProviderRow
        provider="openai"
        saved={{
          provider: 'openai',
          masked_key: '••••beef',
          base_url: 'https://gateway.internal/v1',
          readable: true,
        }}
        operatorConfigured={false}
        onSaved={noop}
      />,
    )
    expect(html).toContain('https://gateway.internal/v1')
  })

  it('labels each row for screen readers', () => {
    const html = render(
      <ProviderRow provider="moonshot" operatorConfigured={false} onSaved={noop} />,
    )
    expect(html).toMatch(/aria-label="Moonshot API key"/)
  })
})

describe('formatting', () => {
  it('abbreviates token counts without losing the small ones', () => {
    expect(formatTokens(0)).toBe('0')
    expect(formatTokens(999)).toBe('999')
    expect(formatTokens(1_500)).toBe('1.5k')
    expect(formatTokens(15_000)).toBe('15k')
    expect(formatTokens(1_500_000)).toBe('1.5M')
  })

  it('does not round a sub-cent estimate down to nothing', () => {
    // A handful of short turns genuinely costs less than a cent; showing
    // "$0.00" next to real usage reads as a broken meter.
    expect(formatUsd(0)).toBe('$0.00')
    expect(formatUsd(0.0004)).toBe('$0.0004')
    expect(formatUsd(1.239)).toBe('$1.24')
  })

  it('formats byte deltas in both directions', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2048)).toBe('2.0 KB')
    // Deleting files produces a negative delta; the unit must still scale.
    expect(formatBytes(-5 * 1024 * 1024)).toBe('-5.0 MB')
  })

  it('falls back to a capitalised id for a provider it has no label for', () => {
    expect(providerLabel('anthropic')).toBe('Anthropic')
    expect(providerLabel('groq')).toBe('Groq')
  })
})

describe('usage chart', () => {
  const report = (daily: UsageReport['daily']): UsageReport => ({
    days: 30,
    project_id: null,
    totals: { events: 1, input_tokens: 0, output_tokens: 0, bytes_delta: 0, usd_cost: 0 },
    by_model: [],
    by_kind: [],
    daily,
    recent: [],
  })

  it('renders nothing when there are no days to plot', () => {
    expect(render(<UsageChart report={report([])} />)).toBe('')
  })

  it('gives a zero-token day a visible hairline instead of a gap', () => {
    const html = render(
      <UsageChart
        report={report([
          { day: '2026-08-01', input_tokens: 0, output_tokens: 0, usd_cost: 0 },
          { day: '2026-08-02', input_tokens: 900, output_tokens: 100, usd_cost: 0.05 },
        ])}
      />,
    )
    expect(html).toContain('height:2%')
    expect(html).toContain('height:100%')
  })

  it('describes itself for screen readers', () => {
    const html = render(
      <UsageChart
        report={report([{ day: '2026-08-02', input_tokens: 10, output_tokens: 1, usd_cost: 0 }])}
      />,
    )
    expect(html).toMatch(/role="img"/)
    expect(html).toMatch(/aria-label="Daily token use over the last 30 days"/)
  })
})

describe('usage by kind', () => {
  const report = (by_kind: UsageReport['by_kind']): UsageReport => ({
    days: 30,
    project_id: null,
    totals: { events: 1, input_tokens: 0, output_tokens: 0, bytes_delta: 0, usd_cost: 0 },
    by_model: [],
    by_kind,
    daily: [],
    recent: [],
  })

  it('renders nothing when there is no usage', () => {
    expect(render(<KindBreakdown report={report([])} />)).toBe('')
  })

  it('shows storage as bytes and chat as tokens', () => {
    // The two kinds are not comparable — reporting a file upload in "tokens"
    // is what the by-model table alone would have implied.
    const html = render(<KindBreakdown report={report([
      { kind: 'storage', events: 2, input_tokens: 0, output_tokens: 0, bytes_delta: 2048, usd_cost: 0 },
      { kind: 'token', events: 3, input_tokens: 900, output_tokens: 100, bytes_delta: 0, usd_cost: 0.05 },
    ])} />)

    expect(html).toContain('2.0 KB')
    expect(html).toContain('1.0k tokens')
    expect(html).toContain('$0.05')
  })

  it('names the kinds in the user’s terms, and passes unknown ones through', () => {
    const html = render(<KindBreakdown report={report([
      { kind: 'gpu', events: 1, input_tokens: 0, output_tokens: 0, bytes_delta: 0, usd_cost: 0 },
      { kind: 'something_new', events: 1, input_tokens: 0, output_tokens: 0, bytes_delta: 0, usd_cost: 0 },
    ])} />)

    expect(html).toContain('Compute')
    expect(html).toContain('something_new')
  })

  it('pluralises the event count', () => {
    const one = render(<KindBreakdown report={report([
      { kind: 'gpu', events: 1, input_tokens: 0, output_tokens: 0, bytes_delta: 0, usd_cost: 0 },
    ])} />)
    expect(one).toContain('1 event')
    expect(one).not.toContain('1 events')
  })
})
