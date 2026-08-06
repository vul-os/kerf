/**
 * auth-a11y.test.js — T-A1: Announce auth errors to screen readers
 *
 * Verifies that:
 *   - Login.jsx error banner has role="alert" + aria-live="assertive"
 *   - Signup.jsx error banner has role="alert" + aria-live="assertive"
 *   - AuthCallback.jsx spinner wrapper has role="status" (busy state)
 *   - AuthCallback.jsx spinner wrapper has aria-live (to announce state)
 *   - AuthCallback.jsx SVG spinner has aria-hidden (decorative)
 *
 * Uses source-level checks (readFileSync) following the established pattern
 * in this codebase — no jsdom or heavy mocking required for structural ARIA
 * contract assertions.
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

const LOGIN_SRC = readFirstExisting('../Login', ['tsx', 'jsx'])
const SIGNUP_SRC = readFirstExisting('../Signup', ['tsx', 'jsx'])
const CALLBACK_SRC = readFirstExisting('../AuthCallback', ['tsx', 'jsx'])

// ---------------------------------------------------------------------------
// Login.jsx — error banner
// ---------------------------------------------------------------------------

describe('Login.jsx — error banner a11y', () => {
  it('error banner has role="alert"', () => {
    expect(LOGIN_SRC).toContain('role="alert"')
  })

  it('error banner has aria-live="assertive" so VoiceOver/NVDA announces immediately', () => {
    expect(LOGIN_SRC).toContain('aria-live="assertive"')
  })

  it('does NOT use aria-live="polite" for the error (would delay announcement)', () => {
    // polite is insufficient for errors — assertive is required.
    // Scope the check to the role="alert" element only — polite is acceptable
    // on other elements such as the role="status" session-expired banner.
    const alertIdx = LOGIN_SRC.indexOf('role="alert"')
    expect(alertIdx).toBeGreaterThan(-1)
    const window = LOGIN_SRC.slice(Math.max(0, alertIdx - 200), alertIdx + 200)
    expect(window).not.toContain('aria-live="polite"')
  })

  it('role="alert" and aria-live="assertive" appear on the same element', () => {
    // Find the line(s) that contain role="alert" and check aria-live="assertive" is nearby
    const lines = LOGIN_SRC.split('\n')
    const alertLine = lines.findIndex((l) => l.includes('role="alert"'))
    expect(alertLine).toBeGreaterThanOrEqual(0)
    // Check within a small window (same div spread across a few lines)
    const window = lines.slice(Math.max(0, alertLine - 1), alertLine + 4).join('\n')
    expect(window).toContain('aria-live="assertive"')
  })
})

// ---------------------------------------------------------------------------
// Signup.jsx — error banner
// ---------------------------------------------------------------------------

describe('Signup.jsx — error banner a11y', () => {
  it('error banner has role="alert"', () => {
    expect(SIGNUP_SRC).toContain('role="alert"')
  })

  it('error banner has aria-live="assertive" so VoiceOver/NVDA announces immediately', () => {
    expect(SIGNUP_SRC).toContain('aria-live="assertive"')
  })

  it('does NOT use aria-live="polite" for the error (would delay announcement)', () => {
    expect(SIGNUP_SRC).not.toContain('aria-live="polite"')
  })

  it('role="alert" and aria-live="assertive" appear on the same element', () => {
    const lines = SIGNUP_SRC.split('\n')
    const alertLine = lines.findIndex((l) => l.includes('role="alert"'))
    expect(alertLine).toBeGreaterThanOrEqual(0)
    const window = lines.slice(Math.max(0, alertLine - 1), alertLine + 4).join('\n')
    expect(window).toContain('aria-live="assertive"')
  })
})

// ---------------------------------------------------------------------------
// AuthCallback.jsx — spinner busy state
// ---------------------------------------------------------------------------

describe('AuthCallback.jsx — spinner busy state a11y', () => {
  it('has role="status" on the loading container', () => {
    expect(CALLBACK_SRC).toContain('role="status"')
  })

  it('has aria-live on the loading container (not a silent frame)', () => {
    expect(CALLBACK_SRC).toMatch(/aria-live=/)
  })

  it('spinner SVG has aria-hidden (decorative, not announced separately)', () => {
    // The SVG is decorative — aria-hidden prevents double-announcement
    expect(CALLBACK_SRC).toContain('aria-hidden')
  })

  it('loading container includes descriptive text for screen readers', () => {
    // The visible text inside the status region narrates what is happening
    expect(CALLBACK_SRC).toMatch(/Signing you in/)
  })
})
