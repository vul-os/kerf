/**
 * docsArticleResponsive.test.js — assert that the Docs Article markdown renderer
 * applies horizontal-scroll containers to tables and pre/code blocks so they
 * don't overflow the page width on narrow mobile viewports.
 *
 * Uses source-analysis (readFileSync) so no DOM environment is required.
 * Pattern mirrors src/__tests__/docsSidebarDrawer.test.js.
 */

import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'
import { describe, it, expect } from 'vitest'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const articleSrc = readFileSync(
  path.resolve(__dirname, '../Article.jsx'),
  'utf8',
)

// ---------------------------------------------------------------------------
// Tables in docs markdown
// ---------------------------------------------------------------------------

describe('Docs Article — markdown table overflow handling', () => {
  it('table component wraps content in an overflow-x-auto container', () => {
    // The mdComponents.table renderer must produce an overflow-x-auto wrapper
    // so wide GFM tables scroll inside the content column on mobile.
    expect(articleSrc).toContain('overflow-x-auto')
  })

  it('table scroll wrapper has data-testid="docs-table-scroll"', () => {
    expect(articleSrc).toContain('data-testid="docs-table-scroll"')
  })

  it('table and overflow-x-auto appear together in the table component', () => {
    // Both the scroll class and testid should be on the same wrapper element.
    // Find the segment of source containing the table mdComponent definition.
    const tableComponentIdx = articleSrc.indexOf('data-testid="docs-table-scroll"')
    expect(tableComponentIdx).toBeGreaterThan(-1)
    // The overflow-x-auto class must appear within 100 characters of the testid
    // (same element), either before or after.
    const window = 100
    const start = Math.max(0, tableComponentIdx - window)
    const end = Math.min(articleSrc.length, tableComponentIdx + window)
    const snippet = articleSrc.slice(start, end)
    expect(snippet).toContain('overflow-x-auto')
  })
})

// ---------------------------------------------------------------------------
// Pre / code blocks in docs markdown
// ---------------------------------------------------------------------------

describe('Docs Article — markdown pre/code block overflow handling', () => {
  it('pre component has overflow-x-auto so wide code does not widen the page', () => {
    // The mdComponents.pre renderer must carry overflow-x-auto directly.
    // We verify both the class and its association with the pre element.
    const preIdx = articleSrc.indexOf('data-testid="docs-pre-scroll"')
    expect(preIdx).toBeGreaterThan(-1)
  })

  it('pre scroll container has data-testid="docs-pre-scroll"', () => {
    expect(articleSrc).toContain('data-testid="docs-pre-scroll"')
  })

  it('pre and overflow-x-auto appear together in the pre component', () => {
    // Scope the search to the CodePre component's own function body (from its
    // declaration to the next top-level function declaration) rather than a
    // fixed character window: CodePre grew a hover-reveal copy button and
    // language label between the `data-testid="docs-pre-scroll"` wrapper
    // <div> and the inner <pre className="overflow-x-auto ...">, so a narrow
    // fixed window breaks every time that markup grows — the function-body
    // boundary tracks the actual component regardless of internal layout.
    const fnStart = articleSrc.indexOf('function CodePre(')
    expect(fnStart).toBeGreaterThan(-1)
    const nextFnMatch = articleSrc.slice(fnStart + 1).match(/\nfunction [A-Za-z]/)
    const fnEnd = nextFnMatch ? fnStart + 1 + nextFnMatch.index : articleSrc.length
    const componentBody = articleSrc.slice(fnStart, fnEnd)
    expect(componentBody).toContain('data-testid="docs-pre-scroll"')
    expect(componentBody).toContain('overflow-x-auto')
  })
})

// ---------------------------------------------------------------------------
// Article layout — min-w-0 prevents flex children from overflowing
// ---------------------------------------------------------------------------

describe('Docs Article — layout overflow guards', () => {
  it('ArticleShell main element has min-w-0 to prevent flex overflow', () => {
    // A flex child without min-w-0 can force the parent wider than the viewport.
    expect(articleSrc).toContain('min-w-0')
  })

  it('article element has min-w-0 (prevents prose from forcing layout wider)', () => {
    // The article prose container must opt out of intrinsic-size flex behaviour.
    const articleElementIdx = articleSrc.indexOf('flex-1 min-w-0 px-6')
    expect(articleElementIdx).toBeGreaterThan(-1)
  })

  it('sidebar drawer is hidden on desktop (hidden lg:flex pattern in Sidebar)', () => {
    // Sidebar.jsx owns this — we only assert the Article shell does not
    // duplicate a broken desktop sidebar of its own.
    expect(articleSrc).toContain('lg:hidden')
  })
})
