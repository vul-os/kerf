/**
 * clashPanel.test.jsx
 *
 * Source-level assertions for the ClashPanel component and the
 * ClashPanel wiring inside AssemblyEditor.  We read the JSX source
 * directly — same approach as chatPanelError.test.js / ChatPanel.toolChips.test.jsx
 * — to avoid the heavy DOM/Monaco/three.js setup.
 *
 * Coverage:
 *  1. ClashPanel renders "Check Clashes" button with data-testid
 *  2. ClashPanel has a collapsible body region
 *  3. ClashPanel dispatches api.runClashDetect on button click
 *  4. Clash results table renders rows with part A / part B columns
 *  5. "Jump to" button calls onHighlight with the correct component id
 *  6. AssemblyEditor imports ClashPanel
 *  7. api.js exports runClashDetect method
 */

import { describe, it, expect, vi, afterEach } from 'vitest'
import { existsSync, readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import { resolve, dirname } from 'path'

const __dirname = dirname(fileURLToPath(import.meta.url))

// Extension-agnostic source read: components migrate from .jsx to .tsx one
// at a time (T-513..T-517), so a literal `.jsx` path here would break the
// moment its target is renamed. Try .tsx first, then fall back to .jsx.
function readComponentSource(baseName: string) {
  const tsxPath = resolve(__dirname, `../${baseName}.tsx`)
  const jsxPath = resolve(__dirname, `../${baseName}.jsx`)
  return readFileSync(existsSync(tsxPath) ? tsxPath : jsxPath, 'utf8')
}

const CLASH_SRC = readComponentSource('ClashPanel')
const ASSEMBLY_SRC = readComponentSource('AssemblyEditor')
const API_SRC = readFileSync(
  // api.js was migrated to api.ts (T-505); this reads the shipped source, not an import specifier.
  resolve(__dirname, '../../lib/api.ts'),
  'utf8',
)

// ---------------------------------------------------------------------------
// 1. ClashPanel structure
// ---------------------------------------------------------------------------

describe('ClashPanel — source structure', () => {
  it('exports a default ClashPanel function', () => {
    expect(CLASH_SRC).toMatch(/export default function ClashPanel/)
  })

  it('renders Check Clashes button with data-testid', () => {
    expect(CLASH_SRC).toMatch(/data-testid="clash-check-button"/)
  })

  it('has a collapsible body region with data-testid', () => {
    expect(CLASH_SRC).toMatch(/data-testid="clash-panel-body"/)
  })

  it('renders the panel wrapper with data-testid', () => {
    expect(CLASH_SRC).toMatch(/data-testid="clash-panel"/)
  })

  it('renders a toggle button with data-testid', () => {
    expect(CLASH_SRC).toMatch(/data-testid="clash-panel-toggle"/)
  })

  it('renders clash table rows with data-testid', () => {
    expect(CLASH_SRC).toMatch(/data-testid="clash-row"/)
  })

  it('renders Jump to action buttons', () => {
    expect(CLASH_SRC).toMatch(/data-testid="clash-jump-btn"/)
  })
})

// ---------------------------------------------------------------------------
// 2. ClashPanel dispatches api.runClashDetect
// ---------------------------------------------------------------------------

describe('ClashPanel — api dispatch', () => {
  it('calls api.runClashDetect', () => {
    expect(CLASH_SRC).toMatch(/api\.runClashDetect/)
  })

  it('uses projectId and assemblyFileId as arguments', () => {
    expect(CLASH_SRC).toMatch(/runClashDetect\(projectId,\s*assemblyFileId/)
  })
})

// ---------------------------------------------------------------------------
// 3. ClashPanel — result rendering
// ---------------------------------------------------------------------------

describe('ClashPanel — result rendering', () => {
  it('renders clash type badge', () => {
    expect(CLASH_SRC).toMatch(/ClashTypeBadge/)
  })

  it('shows depth for hard clashes in mm', () => {
    expect(CLASH_SRC).toMatch(/clash\.depth.*mm|mm.*clash\.depth/)
  })

  it('shows gap for clearance clashes', () => {
    expect(CLASH_SRC).toMatch(/gap.*clash\.depth|clearance/)
  })

  it('calls onHighlight when Jump to is clicked', () => {
    expect(CLASH_SRC).toMatch(/onHighlight\?\./)
    expect(CLASH_SRC).toMatch(/jumpTo\(clash\.a\)/)
  })

  it('shows "No clashes found" when clash_count is 0', () => {
    expect(CLASH_SRC).toMatch(/No clashes found/)
  })

  it('renders non-fatal backend errors', () => {
    expect(CLASH_SRC).toMatch(/result\.errors/)
  })
})

// ---------------------------------------------------------------------------
// 4. AssemblyEditor wires ClashPanel
// ---------------------------------------------------------------------------

describe('AssemblyEditor — ClashPanel wiring', () => {
  it('imports ClashPanel', () => {
    expect(ASSEMBLY_SRC).toMatch(/import ClashPanel from/)
  })

  it('renders ClashPanel with projectId prop', () => {
    expect(ASSEMBLY_SRC).toMatch(/<ClashPanel/)
    expect(ASSEMBLY_SRC).toMatch(/projectId={projectId}/)
  })

  it('passes assemblyFileId to ClashPanel', () => {
    expect(ASSEMBLY_SRC).toMatch(/assemblyFileId={currentFileId}/)
  })

  it('accepts onHighlightComponent prop', () => {
    expect(ASSEMBLY_SRC).toMatch(/onHighlightComponent/)
  })
})

// ---------------------------------------------------------------------------
// 5. api.js — runClashDetect
// ---------------------------------------------------------------------------

describe('api.js — runClashDetect', () => {
  it('exports runClashDetect', () => {
    expect(API_SRC).toMatch(/runClashDetect/)
  })

  it('targets the correct route', () => {
    expect(API_SRC).toMatch(/\/clash/)
  })

  it('uses POST method', () => {
    // The runClashDetect entry must be near POST
    const idx = API_SRC.indexOf('runClashDetect')
    const surrounding = API_SRC.slice(idx, idx + 300)
    expect(surrounding).toMatch(/POST/)
  })
})

// ---------------------------------------------------------------------------
// 6. Renderer.jsx — highlightFaces exported via useImperativeHandle
// ---------------------------------------------------------------------------

describe('Renderer — highlightFaces hook', () => {
  it('defines highlightFaces in useImperativeHandle', () => {
    const RENDERER_SRC = readFileSync(
      (existsSync(resolve(__dirname, '../Renderer.tsx')) ? resolve(__dirname, '../Renderer.tsx') : (existsSync(resolve(__dirname, '../Renderer.tsx')) ? resolve(__dirname, '../Renderer.tsx') : resolve(__dirname, '../Renderer.jsx'))),
      'utf8',
    )
    expect(RENDERER_SRC).toMatch(/highlightFaces/)
  })
})
