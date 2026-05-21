// docsSidebarDrawer.test.js — T-H2: docs sidebar responsive mobile drawer
//
// Pure source-analysis tests (no DOM / React rendering needed).
// All assertions confirm the wiring described in the T-H2 spec:
//
//   1. Toggle button (hamburger) is only visible at narrow widths (< lg),
//      has aria-label="Open navigation", and aria-expanded bound to
//      drawerOpen state.
//   2. The Sidebar renders a desktop column (hidden below lg) and a mobile
//      drawer panel (only visible below lg).
//   3. Clicking the toggle button opens the drawer; clicking the Close
//      button inside the drawer calls onDrawerClose.
//   4. The drawer has role="dialog" + aria-modal for screen-readers.
//   5. Esc key closes the drawer when it is open.
//   6. A focus trap is active while the drawer is open.
//   7. Body scroll is locked while the drawer is open.
//   8. Route-change auto-close: the drawer closes on location.pathname change.
//   9. Both Docs routes (DocsHome + ArticleShell) manage drawerOpen state
//      and pass it down to Sidebar.

import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'
import { describe, it, expect } from 'vitest'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const sidebarSrc = readFileSync(
  path.resolve(__dirname, '../routes/Docs/Sidebar.jsx'),
  'utf8',
)
const indexSrc = readFileSync(
  path.resolve(__dirname, '../routes/Docs/index.jsx'),
  'utf8',
)
const articleSrc = readFileSync(
  path.resolve(__dirname, '../routes/Docs/Article.jsx'),
  'utf8',
)

// ---------------------------------------------------------------------------
// 1. Toggle button (hamburger) visible at narrow widths
// ---------------------------------------------------------------------------

describe('T-H2: hamburger toggle button — narrow width only', () => {
  it('toggle button has aria-label="Open navigation"', () => {
    // Present in both DocsHome and ArticleShell
    expect(indexSrc).toContain('aria-label="Open navigation"')
    expect(articleSrc).toContain('aria-label="Open navigation"')
  })

  it('toggle button has aria-expanded bound to drawerOpen', () => {
    expect(indexSrc).toContain('aria-expanded={drawerOpen}')
    expect(articleSrc).toContain('aria-expanded={drawerOpen}')
  })

  it('toggle button is hidden on large screens (lg:hidden)', () => {
    // The mobile header bar wrapping the hamburger uses lg:hidden
    expect(indexSrc).toContain('lg:hidden')
    expect(articleSrc).toContain('lg:hidden')
  })

  it('clicking toggle button sets drawerOpen to true', () => {
    // Both pages wire: onClick={() => setDrawerOpen(true)}
    expect(indexSrc).toContain('setDrawerOpen(true)')
    expect(articleSrc).toContain('setDrawerOpen(true)')
  })
})

// ---------------------------------------------------------------------------
// 2. Desktop sidebar vs mobile drawer separation
// ---------------------------------------------------------------------------

describe('T-H2: desktop sidebar column vs mobile drawer', () => {
  it('desktop aside uses hidden lg:flex (invisible below lg)', () => {
    expect(sidebarSrc).toContain('hidden lg:flex')
  })

  it('mobile drawer panel uses lg:hidden (invisible at lg+)', () => {
    // The drawer aside and backdrop both carry lg:hidden
    const drawerHiddenCount = (sidebarSrc.match(/lg:hidden/g) || []).length
    expect(drawerHiddenCount).toBeGreaterThanOrEqual(2)
  })

  it('drawer panel slides in from the left (translate-x transitions)', () => {
    expect(sidebarSrc).toContain('translate-x-0')
    expect(sidebarSrc).toContain('-translate-x-full')
  })

  it('backdrop is rendered for mobile drawer', () => {
    expect(sidebarSrc).toContain('pointer-events-auto')
    expect(sidebarSrc).toContain('pointer-events-none')
  })
})

// ---------------------------------------------------------------------------
// 3. Drawer open / close wiring
// ---------------------------------------------------------------------------

describe('T-H2: drawer open and close wiring', () => {
  it('Sidebar accepts drawerOpen and onDrawerClose props', () => {
    expect(sidebarSrc).toContain('drawerOpen')
    expect(sidebarSrc).toContain('onDrawerClose')
  })

  it('Close button inside drawer calls onDrawerClose', () => {
    expect(sidebarSrc).toContain('aria-label="Close navigation"')
    expect(sidebarSrc).toContain('onClick={onDrawerClose}')
  })

  it('backdrop click also triggers onDrawerClose', () => {
    // The backdrop div has onClick={onDrawerClose}
    // There are two occurrences: button + backdrop
    const closeCount = (sidebarSrc.match(/onClick={onDrawerClose}/g) || []).length
    expect(closeCount).toBeGreaterThanOrEqual(2)
  })

  it('DocsHome passes onDrawerClose={() => setDrawerOpen(false)} to Sidebar', () => {
    expect(indexSrc).toContain('setDrawerOpen(false)')
  })

  it('ArticleShell passes onDrawerClose={() => setDrawerOpen(false)} to Sidebar', () => {
    expect(articleSrc).toContain('setDrawerOpen(false)')
  })
})

// ---------------------------------------------------------------------------
// 4. role="dialog" + aria-modal for screen-readers
// ---------------------------------------------------------------------------

describe('T-H2: mobile drawer has dialog role', () => {
  it('drawer aside has role="dialog"', () => {
    expect(sidebarSrc).toContain('role="dialog"')
  })

  it('drawer aside has aria-modal="true"', () => {
    expect(sidebarSrc).toContain('aria-modal="true"')
  })

  it('drawer aside has an accessible label', () => {
    expect(sidebarSrc).toContain('aria-label="Docs navigation"')
  })
})

// ---------------------------------------------------------------------------
// 5. Esc key closes the drawer
// ---------------------------------------------------------------------------

describe('T-H2: Esc key closes the drawer', () => {
  it("keydown handler checks e.key === 'Escape'", () => {
    expect(sidebarSrc).toContain("e.key === 'Escape'")
  })

  it('when drawerOpen is true, Esc calls onDrawerClose', () => {
    // Pattern: if (drawerOpen) { onDrawerClose?.() }
    expect(sidebarSrc).toContain('if (drawerOpen)')
    expect(sidebarSrc).toContain('onDrawerClose?.()')
  })

  it('global keydown listener is registered via window.addEventListener', () => {
    expect(sidebarSrc).toContain("window.addEventListener('keydown'")
  })

  it('keydown listener is removed on cleanup', () => {
    expect(sidebarSrc).toContain("window.removeEventListener('keydown'")
  })
})

// ---------------------------------------------------------------------------
// 6. Focus trap while drawer is open
// ---------------------------------------------------------------------------

describe('T-H2: focus trap inside the drawer', () => {
  it('focus trap uses querySelectorAll on the drawer ref', () => {
    expect(sidebarSrc).toContain('drawerRef.current.querySelectorAll(FOCUSABLE)')
  })

  it('focus trap is activated only when drawerOpen is true', () => {
    expect(sidebarSrc).toContain('if (!drawerOpen || !drawerRef.current) return')
  })

  it('focus trap handles Tab and Shift+Tab (wrapping)', () => {
    expect(sidebarSrc).toContain("e.key !== 'Tab'")
    expect(sidebarSrc).toContain('e.shiftKey')
  })

  it('focus trap listener is registered via document.addEventListener', () => {
    expect(sidebarSrc).toContain("document.addEventListener('keydown', trapFocus)")
  })

  it('focus trap listener is cleaned up', () => {
    expect(sidebarSrc).toContain("document.removeEventListener('keydown', trapFocus)")
  })
})

// ---------------------------------------------------------------------------
// 7. Body scroll lock while drawer is open
// ---------------------------------------------------------------------------

describe('T-H2: body scroll lock when drawer is open', () => {
  it('sets document.body.style.overflow = "hidden" when drawerOpen', () => {
    expect(sidebarSrc).toContain("document.body.style.overflow = 'hidden'")
  })

  it('restores document.body.style.overflow to empty string when drawer closes', () => {
    expect(sidebarSrc).toContain("document.body.style.overflow = ''")
  })
})

// ---------------------------------------------------------------------------
// 8. Route-change auto-close
// ---------------------------------------------------------------------------

describe('T-H2: drawer auto-closes on route change', () => {
  it('useEffect depends on location.pathname and calls onDrawerClose', () => {
    expect(sidebarSrc).toContain('location.pathname')
    expect(sidebarSrc).toContain('onDrawerClose?.()')
  })

  it('uses react-router useLocation to detect navigation', () => {
    expect(sidebarSrc).toContain('useLocation')
  })
})

// ---------------------------------------------------------------------------
// 9. Both page-level components manage drawerOpen state
// ---------------------------------------------------------------------------

describe('T-H2: page-level drawerOpen state in both docs routes', () => {
  it('DocsHome manages drawerOpen via useState', () => {
    expect(indexSrc).toContain('drawerOpen')
    expect(indexSrc).toContain('setDrawerOpen')
  })

  it('ArticleShell manages drawerOpen via useState', () => {
    expect(articleSrc).toContain('drawerOpen')
    expect(articleSrc).toContain('setDrawerOpen')
  })

  it('both routes render <Sidebar drawerOpen={drawerOpen}', () => {
    expect(indexSrc).toContain('drawerOpen={drawerOpen}')
    expect(articleSrc).toContain('drawerOpen={drawerOpen}')
  })
})
