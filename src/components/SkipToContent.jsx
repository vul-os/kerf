/**
 * SkipToContent.jsx — Keyboard-only "skip to main content" link.
 *
 * WCAG 2.1 Success Criterion 2.4.1 ("Bypass Blocks") requires that keyboard
 * users can skip repeated navigation blocks (sidebars, toolbars, headers) and
 * jump directly to the page's primary content region.
 *
 * The link is visually hidden until it receives keyboard focus, at which point
 * it appears as a prominent chip so that sighted keyboard users can see it.
 * Screen readers announce it as the first interactive element on the page.
 *
 * Usage
 * ─────
 *   // 1. Place SkipToContent at the very start of <body> / app root:
 *   <SkipToContent />                          // targets #main-content
 *   <SkipToContent target="#workspace-canvas" label="Skip to canvas" />
 *
 *   // 2. Ensure the target element exists and has the matching id:
 *   <main id="main-content" tabIndex={-1}>…</main>
 *   // tabIndex={-1} lets JS focus() work on non-interactive elements.
 *
 * Props
 * ─────
 *   target  string  CSS id selector for the content region. Default '#main-content'.
 *   label   string  Visible + accessible link text. Default 'Skip to main content'.
 */

export default function SkipToContent({
  target = '#main-content',
  label = 'Skip to main content',
}) {
  return (
    <a
      href={target}
      className={[
        // Hidden by default: visually moved off-screen but still in the
        // focus order (not display:none or visibility:hidden which would
        // remove it from the tab order entirely).
        'absolute -translate-y-full left-4 top-4 z-[9999]',
        // Revealed on focus: translate back into view with a styled chip.
        'focus:translate-y-0',
        // Chip styles matching the Kerf design system.
        'inline-flex items-center px-4 py-2 rounded-lg text-sm font-medium',
        'bg-kerf-300 text-ink-950',
        'shadow-[0_2px_8px_rgba(0,0,0,0.6)]',
        'transition-transform duration-150',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/50 focus-visible:ring-offset-2 focus-visible:ring-offset-ink-950',
      ].join(' ')}
    >
      {label}
    </a>
  )
}
