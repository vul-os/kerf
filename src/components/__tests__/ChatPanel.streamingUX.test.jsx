/**
 * ChatPanel.streamingUX.test.jsx
 *
 * Source-level assertions for improved streaming/responding UX:
 *   - TypingIndicator component exists and is exported
 *   - TypingIndicator renders three dots with good contrast (bg-kerf-300)
 *   - TypingIndicator has role="status" and aria-label for a11y
 *   - TypingIndicator carries data-testid="typing-indicator"
 *   - Streaming placeholder (no content yet) uses TypingIndicator not a faint "…"
 *   - Streaming placeholder has data-testid="streaming-placeholder"
 *   - Streaming placeholder uses legible text color (not low-contrast ink-500)
 *   - The status bar uses data-testid="streaming-status-bar"
 *   - The status bar has higher-contrast text (text-ink-200) not text-ink-400
 *   - The status bar shows TypingIndicator component (not just Sparkles+pulse)
 *   - Thinking label has data-testid="thinking-label"
 *   - Streaming message bubble gets a highlighted border (border-kerf-300/40)
 *   - The bubble has data-streaming="true" attribute when _streaming is set
 *   - Reduced-motion: TypingIndicator omits animate-bounce when reduced=true
 *   - animate-bounce used for the dots animation
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'
import { renderToStaticMarkup } from 'react-dom/server'

const SRC = readFileSync(
  resolve(__dirname, '../ChatPanel.jsx'),
  'utf8',
)

// ---------------------------------------------------------------------------
// Mocks for renderToStaticMarkup tests
// ---------------------------------------------------------------------------
import { vi } from 'vitest'

vi.mock('../Chat/AtopilePreview.jsx', () => ({
  default: ({ source }) => (
    <div data-testid="atopile-preview" data-source-len={source?.length ?? 0} />
  ),
}))

vi.mock('../Chat/CircuitJsonPreview.jsx', () => ({
  default: ({ circuitJson }) => (
    <div data-testid="circuit-json-preview" data-count={circuitJson?.length ?? 0} />
  ),
}))

vi.mock('../../lib/api.js', () => ({
  api: {
    listModels: vi.fn().mockResolvedValue([]),
  },
}))

vi.mock('../../store/workspace.js', () => ({
  useWorkspace: (sel) => sel({
    projectId: null,
    setThreadModel: vi.fn(),
  }),
}))

vi.mock('../../lib/usePrefersReducedMotion.js', () => ({
  default: () => false,
}))

import { TypingIndicator } from '../ChatPanel.jsx'

// ---------------------------------------------------------------------------
// TypingIndicator component — source checks
// ---------------------------------------------------------------------------

describe('TypingIndicator — source checks', () => {
  it('exports TypingIndicator function', () => {
    expect(SRC).toMatch(/export function TypingIndicator/)
  })

  it('has data-testid="typing-indicator" on the wrapper', () => {
    expect(SRC).toMatch(/data-testid="typing-indicator"/)
  })

  it('has role="status" for a11y', () => {
    // Must appear within the TypingIndicator function
    const fnMatch = SRC.match(/export function TypingIndicator[\s\S]{0,600}?\/\/ ----------/)
    expect(fnMatch).toBeTruthy()
    expect(fnMatch[0]).toMatch(/role="status"/)
  })

  it('has aria-label on the wrapper', () => {
    const fnMatch = SRC.match(/export function TypingIndicator[\s\S]{0,600}?\/\/ ----------/)
    expect(fnMatch).toBeTruthy()
    expect(fnMatch[0]).toMatch(/aria-label/)
  })

  it('uses bg-kerf-300 for high-contrast dot color', () => {
    const fnMatch = SRC.match(/export function TypingIndicator[\s\S]{0,600}?\/\/ ----------/)
    expect(fnMatch).toBeTruthy()
    expect(fnMatch[0]).toMatch(/bg-kerf-300/)
  })

  it('uses animate-bounce for animated dots', () => {
    const fnMatch = SRC.match(/export function TypingIndicator[\s\S]{0,600}?\/\/ ----------/)
    expect(fnMatch).toBeTruthy()
    expect(fnMatch[0]).toMatch(/animate-bounce/)
  })

  it('respects reduced prop — omits animate-bounce when reduced=true', () => {
    // The conditional must check `reduced` to choose the class
    const fnMatch = SRC.match(/export function TypingIndicator[\s\S]{0,600}?\/\/ ----------/)
    expect(fnMatch).toBeTruthy()
    expect(fnMatch[0]).toMatch(/reduced/)
  })
})

// ---------------------------------------------------------------------------
// TypingIndicator — render checks
// ---------------------------------------------------------------------------

describe('TypingIndicator — render', () => {
  it('renders three dot spans', () => {
    const html = renderToStaticMarkup(<TypingIndicator />)
    // Three inline spans as dots — count occurrences of bg-kerf-300 class
    const matches = html.match(/bg-kerf-300/g)
    expect(matches).toBeTruthy()
    expect(matches.length).toBeGreaterThanOrEqual(3)
  })

  it('renders with data-testid="typing-indicator"', () => {
    const html = renderToStaticMarkup(<TypingIndicator />)
    expect(html).toContain('data-testid="typing-indicator"')
  })

  it('renders with role="status"', () => {
    const html = renderToStaticMarkup(<TypingIndicator />)
    expect(html).toContain('role="status"')
  })

  it('renders bounce classes when reduced=false (default)', () => {
    const html = renderToStaticMarkup(<TypingIndicator reduced={false} />)
    expect(html).toContain('animate-bounce')
  })

  it('omits bounce classes when reduced=true', () => {
    const html = renderToStaticMarkup(<TypingIndicator reduced={true} />)
    expect(html).not.toContain('animate-bounce')
  })

  it('always renders bg-kerf-300 dots regardless of reduced', () => {
    const htmlReduced = renderToStaticMarkup(<TypingIndicator reduced={true} />)
    const matches = htmlReduced.match(/bg-kerf-300/g)
    expect(matches).toBeTruthy()
    expect(matches.length).toBeGreaterThanOrEqual(3)
  })
})

// ---------------------------------------------------------------------------
// Streaming placeholder (no content yet) — source checks
// ---------------------------------------------------------------------------

describe('ChatPanel — streaming placeholder visibility', () => {
  it('uses data-testid="streaming-placeholder" on the no-content placeholder', () => {
    expect(SRC).toMatch(/data-testid="streaming-placeholder"/)
  })

  it('streaming placeholder renders TypingIndicator, not a plain "…" string', () => {
    // Check the streaming placeholder section uses TypingIndicator component
    const placeholderMatch = SRC.match(/data-testid="streaming-placeholder"[\s\S]{0,300}?<\/span>/)
    expect(placeholderMatch).toBeTruthy()
    expect(placeholderMatch[0]).toMatch(/<TypingIndicator/)
  })

  it('streaming placeholder does NOT use faint text-ink-500', () => {
    // The old faint implementation used text-ink-500 — must be replaced
    const placeholderMatch = SRC.match(/data-testid="streaming-placeholder"[\s\S]{0,200}?<\/span>/)
    expect(placeholderMatch).toBeTruthy()
    expect(placeholderMatch[0]).not.toMatch(/text-ink-500/)
  })

  it('streaming placeholder uses legible text-ink-300 or better', () => {
    const placeholderMatch = SRC.match(/data-testid="streaming-placeholder"[\s\S]{0,200}?<\/span>/)
    expect(placeholderMatch).toBeTruthy()
    // text-ink-300, text-ink-200, text-ink-100, or text-kerf-* are all legible
    expect(placeholderMatch[0]).toMatch(/text-ink-[123]00|text-kerf-/)
  })
})

// ---------------------------------------------------------------------------
// Streaming bubble border — source checks
// ---------------------------------------------------------------------------

describe('ChatPanel — streaming bubble visual indicator', () => {
  it('applies data-streaming="true" attribute to assistant bubble when _streaming', () => {
    expect(SRC).toMatch(/data-streaming=\{.*_streaming.*\}/)
  })

  it('streaming bubble uses highlighted border (border-kerf-300)', () => {
    // When _streaming, the bubble border should change to kerf-300
    expect(SRC).toMatch(/message\._streaming[\s\S]{0,100}border-kerf-300/)
  })
})

// ---------------------------------------------------------------------------
// Status bar ("Kerf is thinking") — source checks
// ---------------------------------------------------------------------------

describe('ChatPanel — streaming status bar', () => {
  it('has data-testid="streaming-status-bar"', () => {
    expect(SRC).toMatch(/data-testid="streaming-status-bar"/)
  })

  it('uses text-ink-200 (high contrast) not text-ink-400 (low contrast)', () => {
    // Find the status bar div and check its text color class
    const barMatch = SRC.match(/data-testid="streaming-status-bar"[\s\S]{0,200}?className/)
    expect(barMatch).toBeTruthy()
    // Should include text-ink-200 in the className string nearby
    const barArea = SRC.match(/data-testid="streaming-status-bar"[^>]{0,400}text-ink-[0-9]+/)
    expect(barArea).toBeTruthy()
    // Verify it's at least ink-200 not ink-400
    expect(barArea[0]).toMatch(/text-ink-[123]00/)
  })

  it('uses TypingIndicator in the status bar (not just Sparkles+pulse)', () => {
    // Find showThinking section and confirm TypingIndicator is there
    const thinkingSection = SRC.match(/showThinking[\s\S]{0,200}?thinking-label/)
    expect(thinkingSection).toBeTruthy()
    expect(thinkingSection[0]).toMatch(/<TypingIndicator/)
  })

  it('has data-testid="thinking-label" on the text label', () => {
    expect(SRC).toMatch(/data-testid="thinking-label"/)
  })

  it('has a visible border to distinguish the status bar', () => {
    const barMatch = SRC.match(/data-testid="streaming-status-bar"[^>]+className[^"]*"[^"]*border[^"]*"/)
    // Accept either format of className
    const barNearby = SRC.match(/data-testid="streaming-status-bar"[\s\S]{0,300}?border-kerf/)
    expect(barNearby).toBeTruthy()
  })
})
