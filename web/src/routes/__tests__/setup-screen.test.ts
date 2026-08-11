/**
 * setup-screen.test.ts — the first-run and sign-in screen, structurally.
 *
 * Replaces auth-a11y.test.ts and session-expired.test.ts, which covered the
 * same properties on Login/Signup/AuthCallback. Those pages are gone — a node
 * has one password, set on first load — but the properties are not: an error
 * has to be announced, and someone bounced by an expired session has to be
 * told that is what happened rather than being handed an unexplained password
 * box.
 *
 * Source-level checks, following the pattern the files it replaces used: these
 * are structural contracts, and a jsdom render buys nothing for them.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const SETUP_SRC = readFileSync(resolve(__dirname, '../Setup.tsx'), 'utf8')
const PROTECTED_SRC = readFileSync(resolve(__dirname, '../ProtectedRoute.tsx'), 'utf8')

describe('the setup screen', () => {
  it('announces errors rather than only colouring them', () => {
    expect(SETUP_SRC).toMatch(/role="alert"/)
  })

  it('marks the busy state so it is not a silent frame', () => {
    expect(SETUP_SRC).toMatch(/aria-live=/)
  })

  it('offers the CLI when the browser is not allowed to claim the node', () => {
    // A node bound to something other than loopback refuses to be claimed
    // through a browser, and the only way forward is on the machine itself.
    // A screen that refuses without saying that is a dead end.
    expect(SETUP_SRC).toContain('kerf admin set-password')
  })

  it('says nothing about resetting by email', () => {
    // There is no mail transport. Offering a reset link would be a promise
    // nothing can keep — that is exactly how /auth/forgot-password came to
    // return 501.
    expect(SETUP_SRC).not.toMatch(/forgot.?password/i)
    expect(SETUP_SRC).not.toMatch(/reset link/i)
  })
})

describe('a session that ran out', () => {
  it('is reported as such, not as an unexplained password prompt', () => {
    expect(PROTECTED_SRC).toContain('sessionExpired: true')
    expect(SETUP_SRC).toContain('sessionExpired')
    expect(SETUP_SRC).toMatch(/session expired/i)
  })

  it('bounces to a route that exists', () => {
    // It used to bounce to /login, which is now a 404 — and a 404 is a worse
    // answer to an expired session than the sign-in screen it was meant to
    // reach. The root renders that screen whenever there is no session.
    expect(PROTECTED_SRC).not.toContain('"/login"')
    expect(PROTECTED_SRC).toMatch(/to="\/"/)
  })
})
