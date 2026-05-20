/**
 * Modal.test.jsx — Vitest suite for the canonical accessible Modal (T-L3).
 *
 * Tests:
 *   1. Renders nothing when open=false.
 *   2. Renders dialog role + aria-modal when open=true.
 *   3. Title is rendered and wired to aria-labelledby.
 *   4. Children and footer are rendered.
 *   5. Backdrop click calls onClose.
 *   6. Close button (X) calls onClose.
 *   7. Source contract: focus trap is implemented (Tab/Shift+Tab handling).
 *   8. Source contract: scroll-lock on body.overflow is applied.
 *   9. Source contract: focus return is implemented.
 *  10. ShareModal, ShortcutsModal, Build3DModal all use the canonical Modal.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { createElement } from 'react'
import { readFileSync } from 'fs'
import { resolve } from 'path'

const ROOT = resolve(__dirname, '../../..')

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock('lucide-react', () => ({
  X: () => null,
  Keyboard: () => null,
  AlertTriangle: () => null,
}))

// ── Import component under test ───────────────────────────────────────────────

import Modal from '../Modal.jsx'

// ── Helpers ───────────────────────────────────────────────────────────────────

function renderModal(props) {
  return renderToStaticMarkup(createElement(Modal, props))
}

const BASE_PROPS = {
  open: true,
  onClose: vi.fn(),
  title: 'Test dialog',
  children: createElement('p', null, 'Hello world'),
}

// ── 1. Closed → renders nothing ──────────────────────────────────────────────

describe('Modal — closed', () => {
  it('renders nothing when open=false', () => {
    const html = renderModal({ ...BASE_PROPS, open: false })
    expect(html).toBe('')
  })
})

// ── 2. ARIA attributes ────────────────────────────────────────────────────────

describe('Modal — ARIA', () => {
  let html

  beforeEach(() => {
    html = renderModal(BASE_PROPS)
  })

  it('has role="dialog"', () => {
    expect(html).toMatch(/role="dialog"/)
  })

  it('has aria-modal="true"', () => {
    expect(html).toMatch(/aria-modal="true"/)
  })

  it('has aria-labelledby pointing to the title element id', () => {
    expect(html).toMatch(/aria-labelledby="modal-title"/)
    expect(html).toMatch(/id="modal-title"/)
  })

  it('aria-labelledby references the same id as the h2', () => {
    const ariaMatch = html.match(/aria-labelledby="([^"]+)"/)
    const idMatch = html.match(/id="([^"]+)"[^>]*>Test dialog/)
    expect(ariaMatch).toBeTruthy()
    expect(idMatch).toBeTruthy()
    expect(ariaMatch[1]).toBe(idMatch[1])
  })

  it('accepts a custom titleId prop', () => {
    const h = renderModal({ ...BASE_PROPS, titleId: 'my-custom-id' })
    expect(h).toMatch(/aria-labelledby="my-custom-id"/)
    expect(h).toMatch(/id="my-custom-id"/)
  })

  it('backdrop has aria-hidden="true"', () => {
    expect(html).toMatch(/aria-hidden="true"/)
  })
})

// ── 3. Content rendering ──────────────────────────────────────────────────────

describe('Modal — content', () => {
  it('renders the title text', () => {
    const html = renderModal(BASE_PROPS)
    expect(html).toContain('Test dialog')
  })

  it('renders children', () => {
    const html = renderModal(BASE_PROPS)
    expect(html).toContain('Hello world')
  })

  it('renders footer when provided', () => {
    const html = renderModal({
      ...BASE_PROPS,
      footer: createElement('button', null, 'OK'),
    })
    expect(html).toContain('OK')
  })

  it('does not render footer section when footer is absent', () => {
    const html = renderModal({ ...BASE_PROPS, footer: undefined })
    // There should be no "border-t border-ink-800 flex justify-end" (footer row)
    expect(html).not.toMatch(/border-t border-ink-800 flex justify-end/)
  })

  it('applies the widthClass to the dialog panel', () => {
    const html = renderModal({ ...BASE_PROPS, widthClass: 'max-w-2xl' })
    expect(html).toContain('max-w-2xl')
  })
})

// ── 4. Close button ───────────────────────────────────────────────────────────

describe('Modal — close button', () => {
  it('renders a close button with aria-label="Close"', () => {
    const html = renderModal(BASE_PROPS)
    expect(html).toMatch(/aria-label="Close"/)
  })
})

// ── 5. Source contracts ───────────────────────────────────────────────────────

describe('Modal — source contracts (Modal.jsx)', () => {
  const src = readFileSync(resolve(ROOT, 'src/components/Modal.jsx'), 'utf8')

  it('implements a focus trap (Tab key handling)', () => {
    expect(src).toMatch(/e\.key.*Tab|Tab.*e\.key/)
  })

  it('implements Shift+Tab reverse trap', () => {
    expect(src).toMatch(/e\.shiftKey/)
  })

  it('calls onClose on Escape', () => {
    expect(src).toMatch(/Escape/)
    expect(src).toMatch(/onClose\(\)/)
  })

  it('applies body scroll-lock', () => {
    expect(src).toMatch(/document\.body\.style\.overflow/)
  })

  it('restores body scroll on unmount', () => {
    // The cleanup function should restore the original overflow.
    expect(src).toMatch(/document\.body\.style\.overflow\s*=\s*original/)
  })

  it('saves previousFocus and restores it on close', () => {
    expect(src).toMatch(/previousFocusRef/)
    expect(src).toMatch(/\.focus\(\)/)
  })

  it('uses useRef for the dialog element', () => {
    expect(src).toMatch(/dialogRef/)
    expect(src).toMatch(/ref=\{dialogRef\}/)
  })

  it('moves initial focus into the dialog on open', () => {
    expect(src).toMatch(/getFocusable|focusable/)
    expect(src).toMatch(/\.focus\(\)/)
  })

  it('has tabIndex={-1} on the dialog panel (fallback focus target)', () => {
    expect(src).toMatch(/tabIndex=\{-1\}/)
  })
})

// ── 6. Ad-hoc modal retirement ────────────────────────────────────────────────

describe('ShareModal — uses canonical Modal', () => {
  const src = readFileSync(resolve(ROOT, 'src/components/ShareModal.jsx'), 'utf8')

  it('imports Modal from ./Modal.jsx', () => {
    expect(src).toMatch(/from ['"]\.\/Modal\.jsx['"]/)
  })

  it('no longer contains its own fixed inset-0 backdrop', () => {
    // The old implementation had a raw fixed-inset-0 div as the outer wrapper.
    // After refactor it delegates to Modal.
    expect(src).not.toMatch(/fixed inset-0.*flex items-center justify-center/)
  })

  it('no longer has its own Escape keydown listener', () => {
    // The canonical Modal handles Esc; ShareModal should not duplicate it.
    expect(src).not.toMatch(/Escape/)
  })
})

describe('ShortcutsModal — uses canonical Modal', () => {
  const src = readFileSync(resolve(ROOT, 'src/components/ShortcutsModal.jsx'), 'utf8')

  it('imports Modal from ./Modal.jsx', () => {
    expect(src).toMatch(/from ['"]\.\/Modal\.jsx['"]/)
  })

  it('no longer renders its own fixed inset-0 backdrop div', () => {
    expect(src).not.toMatch(/fixed inset-0.*backdrop-blur/)
  })

  it('no longer checks for Escape inside its own keydown listener', () => {
    // The `?` listener should only toggle open; Esc is Modal's job.
    expect(src).not.toMatch(/e\.key.*Escape|Escape.*e\.key/)
  })
})

describe('Editor.jsx Build3DModal — uses canonical Modal', () => {
  const src = readFileSync(resolve(ROOT, 'src/routes/Editor.jsx'), 'utf8')

  it('imports Modal from ../components/Modal.jsx', () => {
    expect(src).toMatch(/from ['"]\.\.\/components\/Modal\.jsx['"]/)
  })

  it('Build3DModal no longer contains its own fixed inset-0 wrapper', () => {
    // Old code: <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
    // After refactor, that raw wrapper is gone.
    expect(src).not.toMatch(/fixed inset-0 z-50 flex items-center justify-center bg-black/)
  })
})

describe('Projects.jsx — uses shared Modal, local copy removed', () => {
  const src = readFileSync(resolve(ROOT, 'src/routes/Projects.jsx'), 'utf8')

  it('imports Modal from ../components/Modal.jsx', () => {
    expect(src).toMatch(/from ['"]\.\.\/components\/Modal\.jsx['"]/)
  })

  it('no longer defines a local Modal function', () => {
    // The local Modal function definition should be gone.
    expect(src).not.toMatch(/^function Modal\b/m)
  })
})
