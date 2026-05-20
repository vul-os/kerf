/**
 * f2-settings-aria-live.test.js — T-F2: aria-live on Settings status messages
 *
 * Verifies that:
 *   - Settings.jsx Inline component uses role="alert" + aria-live="assertive" for errors
 *   - Settings.jsx Inline component uses role="status" + aria-live="polite" for ok/info
 *   - WorkspaceSettings.jsx error banner has role="alert" + aria-live="assertive"
 *   - WorkspaceSettings.jsx success/info msg has role="status" + aria-live="polite"
 *   - WorkspaceMembers.jsx error banner has role="alert" + aria-live="assertive"
 *
 * Workspace routes scan findings (logged per spec):
 *   WorkspaceSettings.jsx — fixed-width: none problematic; slug prefix span uses px-3
 *     which is fine. Label gaps: all inputs have labels (text-[11px] uppercase).
 *     aria-live: added role="alert" to err banner, role="status" to msg line.
 *   WorkspaceMembers.jsx — fixed-width: member avatar uses inline style (dynamic,
 *     appropriate). Role select is w-auto. No truncation issues. Label gaps: role
 *     select has no explicit <label> but is within a list item where the member name
 *     provides context; acceptable for this iteration.
 *     aria-live: added role="alert" to err banner.
 *
 * Uses source-level checks (readFileSync) following the established pattern
 * in this codebase — no jsdom or heavy mocking required for structural ARIA
 * contract assertions.
 */

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'

const SETTINGS_SRC = readFileSync(resolve(__dirname, '../Settings.jsx'), 'utf8')
const WS_SETTINGS_SRC = readFileSync(resolve(__dirname, '../WorkspaceSettings.jsx'), 'utf8')
const WS_MEMBERS_SRC = readFileSync(resolve(__dirname, '../WorkspaceMembers.jsx'), 'utf8')

// ---------------------------------------------------------------------------
// Settings.jsx — Inline component live regions
// ---------------------------------------------------------------------------

describe('Settings.jsx Inline — error kind uses assertive live region', () => {
  it('has role="alert" for errors', () => {
    expect(SETTINGS_SRC).toContain('role="alert"')
  })

  it('has aria-live="assertive" for errors', () => {
    expect(SETTINGS_SRC).toContain('aria-live="assertive"')
  })

  it('role="alert" and aria-live="assertive" appear close together in the err branch', () => {
    const lines = SETTINGS_SRC.split('\n')
    const alertLine = lines.findIndex((l) => l.includes('role="alert"'))
    expect(alertLine).toBeGreaterThanOrEqual(0)
    const window = lines.slice(Math.max(0, alertLine - 1), alertLine + 4).join('\n')
    expect(window).toContain('aria-live="assertive"')
  })
})

describe('Settings.jsx Inline — ok/info kind uses polite live region', () => {
  it('has role="status" for ok/info messages', () => {
    expect(SETTINGS_SRC).toContain('role="status"')
  })

  it('has aria-live="polite" for ok/info messages', () => {
    expect(SETTINGS_SRC).toContain('aria-live="polite"')
  })

  it('role="status" and aria-live="polite" appear close together in the status branch', () => {
    const lines = SETTINGS_SRC.split('\n')
    const statusLine = lines.findIndex((l) => l.includes('role="status"'))
    expect(statusLine).toBeGreaterThanOrEqual(0)
    const window = lines.slice(Math.max(0, statusLine - 1), statusLine + 4).join('\n')
    expect(window).toContain('aria-live="polite"')
  })
})

// ---------------------------------------------------------------------------
// WorkspaceSettings.jsx — error banner + save status
// ---------------------------------------------------------------------------

describe('WorkspaceSettings.jsx — error banner a11y', () => {
  it('error banner has role="alert"', () => {
    expect(WS_SETTINGS_SRC).toContain('role="alert"')
  })

  it('error banner has aria-live="assertive"', () => {
    expect(WS_SETTINGS_SRC).toContain('aria-live="assertive"')
  })

  it('role="alert" and aria-live="assertive" appear close together on the error banner', () => {
    const lines = WS_SETTINGS_SRC.split('\n')
    const alertLine = lines.findIndex((l) => l.includes('role="alert"'))
    expect(alertLine).toBeGreaterThanOrEqual(0)
    const window = lines.slice(Math.max(0, alertLine - 1), alertLine + 4).join('\n')
    expect(window).toContain('aria-live="assertive"')
  })

  it('error icon has aria-hidden (decorative)', () => {
    expect(WS_SETTINGS_SRC).toContain('aria-hidden')
  })
})

describe('WorkspaceSettings.jsx — save status msg a11y', () => {
  it('save status msg has role="status"', () => {
    expect(WS_SETTINGS_SRC).toContain('role="status"')
  })

  it('save status msg has aria-live="polite"', () => {
    expect(WS_SETTINGS_SRC).toContain('aria-live="polite"')
  })

  it('role="status" and aria-live="polite" appear close together on the msg element', () => {
    const lines = WS_SETTINGS_SRC.split('\n')
    const statusLine = lines.findIndex((l) => l.includes('role="status"'))
    expect(statusLine).toBeGreaterThanOrEqual(0)
    const window = lines.slice(Math.max(0, statusLine - 1), statusLine + 4).join('\n')
    expect(window).toContain('aria-live="polite"')
  })
})

// ---------------------------------------------------------------------------
// WorkspaceMembers.jsx — error banner
// ---------------------------------------------------------------------------

describe('WorkspaceMembers.jsx — error banner a11y', () => {
  it('error banner has role="alert"', () => {
    expect(WS_MEMBERS_SRC).toContain('role="alert"')
  })

  it('error banner has aria-live="assertive"', () => {
    expect(WS_MEMBERS_SRC).toContain('aria-live="assertive"')
  })

  it('role="alert" and aria-live="assertive" appear close together on the error banner', () => {
    const lines = WS_MEMBERS_SRC.split('\n')
    const alertLine = lines.findIndex((l) => l.includes('role="alert"'))
    expect(alertLine).toBeGreaterThanOrEqual(0)
    const window = lines.slice(Math.max(0, alertLine - 1), alertLine + 4).join('\n')
    expect(window).toContain('aria-live="assertive"')
  })

  it('error icon has aria-hidden (decorative)', () => {
    expect(WS_MEMBERS_SRC).toContain('aria-hidden')
  })
})
