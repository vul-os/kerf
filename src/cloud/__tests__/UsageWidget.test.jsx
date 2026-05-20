// UsageWidget.test.jsx — Vitest tests for T-L5 "Fix /usage dead link".
//
// Strategy: renderToStaticMarkup + top-level vi.mock (hoisted) for all deps.
// The Layout user menu tests (cloudEnabled visibility) live in a separate
// file (UsageRoute.layout.test.jsx) to avoid mock-hoisting conflicts with
// the Layout.jsx stub used by UsagePage below.
//
// What we test here:
//   1. UsagePage renders a heading and wraps in a Layout element.
//   2. UsageWidget renders balance label and "Top up" link to /billing.
//   3. App.jsx source wires a /usage route (static text assertion).

import { describe, it, expect, vi, beforeAll } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import React from 'react'

// ---------------------------------------------------------------------------
// Module-level mocks (hoisted by Vitest before imports)
// ---------------------------------------------------------------------------
vi.mock('react-router-dom', () => ({
  Link: ({ to, children, ...rest }) => React.createElement('a', { href: to, ...rest }, children),
  useNavigate: () => () => {},
}))

vi.mock('lucide-react', () => {
  const stub = (name) => () => React.createElement('span', { 'data-icon': name })
  return {
    Wallet: stub('Wallet'),
    Plus: stub('Plus'),
    Loader2: stub('Loader2'),
  }
})

vi.mock('../api.js', () => ({
  getBillingMe: () => Promise.resolve({ credits_usd: '5.00', recent_usage: [] }),
}))

// Stub Layout so UsagePage can render without a full app context
vi.mock('../../components/Layout.jsx', () => ({
  default: ({ children }) =>
    React.createElement('div', { 'data-testid': 'layout' }, children),
}))

// ---------------------------------------------------------------------------
// 1. UsagePage renders correctly
// ---------------------------------------------------------------------------

describe('UsagePage', () => {
  let html

  beforeAll(async () => {
    const { UsagePage } = await import('../UsageWidget.jsx')
    html = renderToStaticMarkup(React.createElement(UsagePage))
  })

  it('renders a Usage heading', () => {
    expect(html).toMatch(/Usage/)
  })

  it('wraps content in a Layout element', () => {
    expect(html).toMatch(/data-testid="layout"/)
  })
})

// ---------------------------------------------------------------------------
// 2. UsageWidget tile
// ---------------------------------------------------------------------------

describe('UsageWidget tile', () => {
  let html

  beforeAll(async () => {
    const { UsageWidget } = await import('../UsageWidget.jsx')
    html = renderToStaticMarkup(React.createElement(UsageWidget, { to: '/billing' }))
  })

  it('renders the Balance label', () => {
    expect(html).toMatch(/Balance/)
  })

  it('renders a "Top up" link pointing to /billing', () => {
    expect(html).toMatch(/href="\/billing"/)
    expect(html).toMatch(/Top up/)
  })
})

// ---------------------------------------------------------------------------
// 3. App.jsx wires the /usage route (static source check)
// ---------------------------------------------------------------------------

describe('App.jsx route registration', () => {
  it('contains a /usage route definition', async () => {
    const src = await import('../../App.jsx?raw')
    const text = src.default
    expect(text).toMatch(/path="\/usage"/)
    expect(text).toMatch(/UsagePage/)
  })
})
