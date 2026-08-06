/**
 * session-expired.test.js — T-A2: Session-expired feedback on protected bounce
 *
 * Verifies that:
 *   - ProtectedRoute.jsx passes `sessionExpired: true` in navigate state.
 *   - Login.jsx renders a session-expired banner when `location.state.sessionExpired` is true.
 *   - The banner uses role="status" and aria-live="polite".
 *   - The banner text matches the spec copy.
 *   - The banner is NOT shown when sessionExpired is absent/false.
 *   - An existing error query-param banner still uses role="alert".
 *
 * Uses source-level checks (readFileSync) following the established pattern
 * in this codebase — no jsdom or heavy mocking required for structural contract assertions.
 */

import { describe, it, expect } from 'vitest'
// @ts-expect-error - no @types/node in this toolchain
import { readFileSync, existsSync } from 'fs'
// @ts-expect-error - no @types/node in this toolchain
import { resolve, dirname } from 'path'
// @ts-expect-error - no @types/node in this toolchain
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))

// Source-text inspection reads the module off disk by literal path, so a
// .jsx -> .tsx migration silently breaks it (typecheck cannot catch this;
// only running the suite does). Rather than re-pinning to .tsx and breaking
// again on the next slice, resolve whichever extension is present.
function readFirstExisting(base: string, exts: string[]) {
  for (const ext of exts) {
    const path = resolve(__dirname, `${base}.${ext}`)
    if (existsSync(path)) return readFileSync(path, 'utf8')
  }
  throw new Error(`No source found for ${base}`)
}

const PROTECTED_SRC = readFirstExisting('../ProtectedRoute', ['tsx', 'jsx'])
const LOGIN_SRC = readFirstExisting('../Login', ['tsx', 'jsx'])

// ---------------------------------------------------------------------------
// ProtectedRoute.jsx — passes sessionExpired reason in navigate state
// ---------------------------------------------------------------------------

describe('ProtectedRoute.jsx — passes sessionExpired in navigate state', () => {
  it('passes sessionExpired: true in the Navigate state', () => {
    expect(PROTECTED_SRC).toContain('sessionExpired: true')
  })

  it('still passes from: loc.pathname in the Navigate state', () => {
    expect(PROTECTED_SRC).toContain('from: loc.pathname')
  })

  it('navigates to /login on unauthenticated access', () => {
    expect(PROTECTED_SRC).toContain('to="/login"')
  })
})

// ---------------------------------------------------------------------------
// Login.jsx — session-expired banner
// ---------------------------------------------------------------------------

describe('Login.jsx — session-expired banner', () => {
  it('reads sessionExpired from location.state', () => {
    expect(LOGIN_SRC).toContain('location.state?.sessionExpired')
  })

  it('renders a banner with the spec copy', () => {
    expect(LOGIN_SRC).toContain('Your session expired — sign in again.')
  })

  it('session-expired banner has role="status" (informational, not an error)', () => {
    // Find the block containing the session-expired text and verify role
    const lines = LOGIN_SRC.split('\n')
    const bannerLine = lines.findIndex((l) => l.includes('sessionExpired') && l.includes('!error'))
    expect(bannerLine).toBeGreaterThanOrEqual(0)
    const window = lines.slice(bannerLine, bannerLine + 8).join('\n')
    expect(window).toContain('role="status"')
  })

  it('session-expired banner has aria-live="polite"', () => {
    const lines = LOGIN_SRC.split('\n')
    const bannerLine = lines.findIndex((l) => l.includes('sessionExpired') && l.includes('!error'))
    expect(bannerLine).toBeGreaterThanOrEqual(0)
    const window = lines.slice(bannerLine, bannerLine + 8).join('\n')
    expect(window).toContain('aria-live="polite"')
  })

  it('session-expired banner has a data-testid for easy querying', () => {
    expect(LOGIN_SRC).toContain('data-testid="session-expired-banner"')
  })

  it('session-expired banner only shows when there is no error (error takes precedence)', () => {
    // The condition should include !error so the red error banner wins
    expect(LOGIN_SRC).toContain('sessionExpired && !error')
  })

  it('error banner still has role="alert" (separate from session-expired banner)', () => {
    expect(LOGIN_SRC).toContain('role="alert"')
  })

  it('error banner still has aria-live="assertive"', () => {
    expect(LOGIN_SRC).toContain('aria-live="assertive"')
  })
})
