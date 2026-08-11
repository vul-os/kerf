/**
 * Setup.test.tsx — the three states a node can be in on first load.
 *
 * Rendered with renderToStaticMarkup (the project's pattern), which gives
 * initial state only — exactly what matters here, since each of these screens
 * is a decision about what to show before anyone has interacted.
 *
 * The screen this file cares most about is the middle one. An unconfigured
 * node belongs to whoever reaches it first, so claiming one over a network is
 * a race with a stranger. The server refuses it; the UI has to explain that
 * rather than render a form that would 403.
 */
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import type { ReactElement } from 'react'
import Setup, {
  SetupBlocked,
  SetupClaim,
  SignIn,
  MIN_PASSWORD_LENGTH,
  type SetupState,
} from './Setup.jsx'

const render = (ui: ReactElement) => renderToStaticMarkup(ui)
const noop = () => {}

const UNCLAIMED: SetupState = { configured: false, can_configure_here: true, reason: '' }
const REMOTE: SetupState = {
  configured: false,
  can_configure_here: false,
  reason: 'This server is bound to 0.0.0.0, not loopback, so whoever reached it first could claim it.',
}
const CLAIMED: SetupState = { configured: true, can_configure_here: true, reason: '' }

describe('which screen a node gets', () => {
  it('offers to set a password when the node is unclaimed and reachable', () => {
    const html = render(<Setup state={UNCLAIMED} onReady={noop} />)
    expect(html).toContain('Set a password')
    expect(html).not.toContain('Unlock this Kerf')
  })

  it('asks for the password when the node is already claimed', () => {
    const html = render(<Setup state={CLAIMED} onReady={noop} />)
    expect(html).toContain('Unlock this Kerf')
    expect(html).not.toContain('Set a password')
  })

  it('refuses to offer a claim form over a network bind', () => {
    // Rendering the form here would produce a 403 on submit and leave the user
    // guessing. The reason names the machine as the place to do it instead.
    const html = render(<Setup state={REMOTE} onReady={noop} />)
    expect(html).not.toContain('Set a password')
    expect(html).toContain('kerf admin set-password')
  })
})

describe('claiming', () => {
  it('starts with the submit disabled — an empty password is not a password', () => {
    const html = render(<SetupClaim onClaimed={noop} />)
    expect(html).toMatch(/<button[^>]*disabled/)
  })

  it('says the password cannot be recovered, before it is chosen', () => {
    // After the fact is too late: there is no reset email, so a forgotten
    // password means physical access to the machine.
    const html = render(<SetupClaim onClaimed={noop} />)
    expect(html).toContain('no reset email')
    expect(html).toContain('kerf admin set-password')
  })

  it('states what the password protects', () => {
    const html = render(<SetupClaim onClaimed={noop} />)
    expect(html).toContain('only credential')
  })

  it('asks for the password twice', () => {
    const html = render(<SetupClaim onClaimed={noop} />)
    const passwordFields = html.match(/type="password"/g) || []
    expect(passwordFields.length).toBe(2)
  })

  it('tells the user the minimum length up front', () => {
    const html = render(<SetupClaim onClaimed={noop} />)
    expect(html).toContain(String(MIN_PASSWORD_LENGTH))
  })

  it('does not autofill from a saved password', () => {
    // new-password, not current-password: this is a fresh credential and a
    // manager offering the last one would be wrong.
    const html = render(<SetupClaim onClaimed={noop} />)
    expect(html).toMatch(/autoComplete="new-password"|autocomplete="new-password"/)
  })
})

describe('signing in', () => {
  it('starts disabled and takes one password', () => {
    const html = render(<SignIn onSignedIn={noop} />)
    expect(html).toMatch(/<button[^>]*disabled/)
    expect((html.match(/type="password"/g) || []).length).toBe(1)
  })

  it('offers the recovery path rather than a dead end', () => {
    const html = render(<SignIn onSignedIn={noop} />)
    expect(html).toContain('kerf admin')
  })

  it('invites the password manager to fill the existing password', () => {
    const html = render(<SignIn onSignedIn={noop} />)
    expect(html).toMatch(/autoComplete="current-password"|autocomplete="current-password"/)
  })
})

describe('the blocked screen', () => {
  it('shows the server’s own reason verbatim', () => {
    // The server knows what it is bound to; restating it in the client would
    // be a second copy of the truth that can drift.
    const html = render(<SetupBlocked reason={REMOTE.reason} />)
    expect(html).toContain('0.0.0.0')
  })

  it('gives the exact command to run', () => {
    const html = render(<SetupBlocked reason={REMOTE.reason} />)
    expect(html).toContain('kerf admin set-password')
  })

  it('offers no password field at all', () => {
    expect(render(<SetupBlocked reason={REMOTE.reason} />)).not.toContain('type="password"')
  })
})
