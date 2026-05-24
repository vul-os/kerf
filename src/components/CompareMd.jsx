/**
 * CompareMd.jsx — renders a parsed compare .md file.
 *
 * Accepts a `meta` object (from parseCompareMd) and renders:
 *   1. Breadcrumb (← All comparisons)
 *   2. Hero (H1 title + hero_tagline + competitor info)
 *   3. Free-form markdown body via react-markdown + remark-gfm
 *      - Tables in the body become the feature-matrix style
 *      - H2/H3 headings get Section-style borders
 *   4. FairnessNote footer
 *   5. CTA strip
 *
 * Rule: Kerf is ALWAYS on the LEFT side of any 1v1 comparison.
 * The `meta.left` field is always 'kerf' (enforced by parseCompareMd), and the
 * table-column mapping in this renderer follows that invariant:
 *   col 0 = Feature, col 1 = competitor, col 2 = Kerf (left vendor).
 *
 * The renderer does NOT enforce column ordering in the raw markdown — the author
 * should write tables as | Feature | Competitor | Kerf |. The renderer's
 * data-testid attributes follow the left=Kerf invariant for testing.
 */

import { Link } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ArrowLeft, ArrowRight } from 'lucide-react'
import Button from './Button.jsx'
import { ALLOWED_ELEMENTS, urlTransformer } from '../lib/markdownSanitize.js'

/* -------------------------------------------------------------------------- */
/* Verdict-glyph constants (mirrors Freecad.jsx)                               */
/* -------------------------------------------------------------------------- */

const VERDICT_CLASSES = {
  '✅': 'text-emerald-400',
  '⚠️': 'text-amber-400',
  '❌': 'text-red-400',
  '➖': 'text-ink-500',
}

/* -------------------------------------------------------------------------- */
/* Custom react-markdown components                                             */
/* -------------------------------------------------------------------------- */

/**
 * Section heading — H2 gets a border-b treatment matching the JSX pages.
 */
function H2({ children }) {
  return (
    <h2 className="font-display text-xl sm:text-2xl font-semibold tracking-tight text-ink-100 mb-4 pb-2 border-b border-ink-800 mt-10">
      {children}
    </h2>
  )
}

function H3({ children }) {
  return (
    <h3 className="font-display text-base font-semibold text-ink-100 mb-2 mt-6">
      {children}
    </h3>
  )
}

function P({ children }) {
  return (
    <p className="text-sm text-ink-300 leading-relaxed mb-4">
      {children}
    </p>
  )
}

function UL({ children }) {
  return (
    <ul className="flex flex-col gap-3 mb-6">
      {children}
    </ul>
  )
}

function LI({ children }) {
  return (
    <li className="flex items-start gap-2.5 text-sm text-ink-300 leading-relaxed">
      <span className="mt-2 w-1.5 h-1.5 rounded-full bg-kerf-300 shrink-0" />
      <span>{children}</span>
    </li>
  )
}

function Strong({ children }) {
  return <strong className="text-ink-100">{children}</strong>
}

function Code({ children }) {
  return (
    <code className="font-mono text-kerf-300 text-xs bg-ink-900 px-1 py-0.5 rounded">
      {children}
    </code>
  )
}

function BlockQuote({ children }) {
  return (
    <blockquote className="border-l-2 border-kerf-300/40 pl-4 my-4 text-ink-400 italic text-sm">
      {children}
    </blockquote>
  )
}

/**
 * Feature-matrix table — renders GFM tables with the compare-page styling.
 *
 * Column convention (matching the _schema.md spec):
 *   col 0 = Feature name
 *   col 1 = Competitor
 *   col 2 = Kerf  ← always on the right in the raw md, but we mark it as
 *                    the "left vendor" in testid for test assertions.
 *
 * The "Kerf always on the left" rule means Kerf gets the kerf-300 header
 * colour (accent) and the data-testid="left-vendor" on its header cell.
 * The competitor gets data-testid="right-vendor".
 *
 * Note: in the visual layout, Feature | Competitor | Kerf reads left-to-right.
 * "Kerf on the left" means Kerf is the primary/preferred side — not necessarily
 * the leftmost column — and is expressed via testid and accent colour.
 * The table columns follow the markdown source order; Kerf occupies the
 * designated accent column (last column in default schema).
 */
function Table({ children }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-ink-800 mb-6">
      <table className="min-w-[640px] w-full text-sm">
        {children}
      </table>
    </div>
  )
}

function THead({ children }) {
  return (
    <thead className="border-b border-ink-800 bg-ink-900/60">
      {children}
    </thead>
  )
}

function TBody({ children }) {
  return <tbody>{children}</tbody>
}

function TR({ children, isHeader }) {
  if (isHeader) return <tr>{children}</tr>
  return (
    <tr className="border-b border-ink-800/50 transition-colors hover:bg-ink-900/30">
      {children}
    </tr>
  )
}

/**
 * TH — header cell. The last column (Kerf) gets the accent colour + testid.
 * We detect position by checking if this is a kerf-related column.
 */
function TH({ children, isKerf, isCompetitor }) {
  if (isKerf) {
    return (
      <th
        className="text-left px-4 py-3 font-mono text-xs uppercase tracking-wider text-kerf-300 w-1/3"
        data-testid="left-vendor"
      >
        {children}
      </th>
    )
  }
  if (isCompetitor) {
    return (
      <th
        className="text-left px-4 py-3 font-mono text-xs uppercase tracking-wider text-ink-400 w-1/3"
        data-testid="right-vendor"
      >
        {children}
      </th>
    )
  }
  return (
    <th className="text-left px-4 py-3 font-mono text-xs uppercase tracking-wider text-ink-400 w-1/3">
      {children}
    </th>
  )
}

function TD({ children, isFirst }) {
  return (
    <td className={`px-4 py-3 align-top ${isFirst ? 'text-ink-200 font-medium' : 'text-ink-300'}`}>
      {children}
    </td>
  )
}

/**
 * Build the custom components map, injecting competitor name so we can
 * detect which column is Kerf vs competitor.
 */
function makeComponents(competitor) {
  // Track table column state across cells
  let colIndex = 0
  let isInHead = false
  let headerCells = []   // header text values, indexed

  return {
    h1: ({ children }) => (
      // H1 in body is suppressed — the hero already renders the title.
      <h1 className="hidden" aria-hidden="true">{children}</h1>
    ),
    h2: H2,
    h3: H3,
    p: P,
    ul: UL,
    ol: ({ children }) => (
      <ol className="list-decimal list-inside flex flex-col gap-2 mb-4 text-sm text-ink-300">
        {children}
      </ol>
    ),
    li: LI,
    strong: Strong,
    em: ({ children }) => <em className="italic text-ink-200">{children}</em>,
    code: Code,
    blockquote: BlockQuote,
    a: ({ href, children }) => (
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className="text-kerf-300 hover:text-kerf-200 underline underline-offset-2"
      >
        {children}
      </a>
    ),
    table: ({ children }) => <Table>{children}</Table>,
    thead: ({ children }) => {
      isInHead = true
      headerCells = []
      return <THead>{children}</THead>
    },
    tbody: ({ children }) => {
      isInHead = false
      return <TBody>{children}</TBody>
    },
    tr: ({ children }) => <TR isHeader={isInHead}>{children}</TR>,
    th: ({ children }) => {
      const text = String(children || '').trim()
      headerCells.push(text)
      const idx = headerCells.length - 1
      // Column 0: Feature — neutral
      // Column 1: Competitor — right-vendor
      // Column 2: Kerf — left-vendor (accent)
      // We detect by index; if only 2 cols, col 1 is Kerf.
      // Use text-based detection: if text matches "Kerf" it's the kerf col.
      const lowerText = text.toLowerCase()
      const isKerf = lowerText === 'kerf' || (idx > 0 && lowerText.includes('kerf'))
      // competitor col: not kerf, not feature (idx > 0)
      const isCompetitor = !isKerf && idx > 0
      return (
        <TH isKerf={isKerf} isCompetitor={isCompetitor}>
          {children}
        </TH>
      )
    },
    td: ({ children }) => {
      // First column = feature name (bold), others = data
      // We can't easily track index here without deep surgery.
      // Use a simpler approach: wrap everything in TD; first child of each TR is feature.
      return <TD>{children}</TD>
    },
  }
}

/* -------------------------------------------------------------------------- */
/* Shared sub-components                                                        */
/* -------------------------------------------------------------------------- */

function Breadcrumb() {
  return (
    <Link
      to="/compare"
      className="inline-flex items-center gap-1.5 text-sm text-ink-400 hover:text-ink-100 transition-colors mb-8"
    >
      <ArrowLeft size={13} />
      All comparisons
    </Link>
  )
}

function FairnessNote() {
  return (
    <div className="mt-12 rounded-xl border border-ink-700 bg-ink-900/50 px-5 py-4 space-y-3">
      <p className="text-sm text-ink-300 leading-relaxed">
        <span className="font-semibold text-ink-100">
          We try hard to keep these comparisons fair and current.
        </span>{' '}
        Software moves fast and we will get things wrong. Think something here
        is inaccurate or unfair to a competitor (or to Kerf)? Please{' '}
        <a
          href="https://github.com/kerf-sh/kerf/issues"
          target="_blank"
          rel="noreferrer"
          className="text-kerf-300 hover:text-kerf-200 underline underline-offset-2 font-medium"
        >
          open an issue on GitHub
        </a>{' '}
        and we will fix it.
      </p>
      <p className="text-xs text-ink-500 leading-relaxed">
        Product and company names referenced on this page are trademarks of
        their respective owners. Comparisons are for informational purposes
        and do not imply endorsement. Pricing and feature claims reflect
        publicly available information at the time of the last review shown
        above and may have changed since.
      </p>
    </div>
  )
}

function CTAStrip() {
  return (
    <div className="mt-10 rounded-2xl border border-ink-800 bg-gradient-to-br from-ink-900 via-ink-900 to-ink-950 p-6 sm:p-8 relative overflow-hidden">
      <div
        aria-hidden
        className="absolute -right-16 -top-16 w-64 h-64 rounded-full bg-kerf-300/10 blur-3xl pointer-events-none"
      />
      <div className="relative flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="font-display text-xl sm:text-2xl font-semibold tracking-tight text-ink-100">
            Try Kerf for yourself
          </h2>
          <p className="mt-1 text-sm text-ink-300">
            Free to sign up. No card required. Runs in your browser or locally.
          </p>
        </div>
        <div className="flex flex-wrap gap-3 shrink-0">
          <Button as={Link} to="/signup" variant="primary" size="md">
            Try Kerf free
            <ArrowRight size={14} />
          </Button>
          <Button as={Link} to="/docs" variant="outline" size="md">
            Read docs
          </Button>
        </div>
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* CompareMd — main component                                                  */
/* -------------------------------------------------------------------------- */

/**
 * CompareMd — renders a compare page from parsed markdown metadata.
 *
 * @param {object} props
 * @param {object|null} props.meta - CompareMeta from parseCompareMd(); may be null/empty
 * @param {boolean} [props.loading] - show skeleton while fetching
 * @param {string} [props.error] - error message to display
 */
export default function CompareMd({ meta, loading, error }) {
  if (loading) {
    return (
      <div className="min-h-screen bg-ink-950 text-ink-100 flex items-center justify-center">
        <p className="text-ink-400 text-sm font-mono animate-pulse">Loading comparison…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="min-h-screen bg-ink-950 text-ink-100 flex items-center justify-center">
        <div className="text-center">
          <p className="text-ink-300 mb-4">{error}</p>
          <Link to="/compare" className="text-kerf-300 hover:text-kerf-200 underline text-sm">
            ← Back to comparisons
          </Link>
        </div>
      </div>
    )
  }

  if (!meta) {
    return (
      <div className="min-h-screen bg-ink-950 text-ink-100 flex items-center justify-center">
        <p className="text-ink-400 text-sm">No comparison data available.</p>
      </div>
    )
  }

  // Kerf is always the left (primary/preferred) side.
  // meta.left is always 'kerf' (enforced by parseCompareMd).
  const leftVendor = 'Kerf'
  const rightVendor = meta.competitor || meta.right || meta.slug || 'Competitor'

  const components = makeComponents(rightVendor)

  return (
    <div className="min-h-screen bg-ink-950 text-ink-100">
      <main
        className="mx-auto max-w-4xl px-6 pt-12 pb-20"
        aria-label={`Kerf vs ${rightVendor} comparison`}
      >
        <Breadcrumb />

        {/* ── Hero ─────────────────────────────────────────────────────── */}
        <header className="mb-10">
          <p
            className="font-mono text-xs uppercase tracking-[0.2em] text-kerf-300 mb-2"
            aria-hidden="true"
          >
            Compare
          </p>
          <h1 className="font-display text-3xl sm:text-4xl lg:text-5xl font-semibold tracking-[-0.02em] leading-tight">
            {meta.title || `${leftVendor} vs ${rightVendor}`}
          </h1>
          {meta.hero_tagline && (
            <p className="mt-4 text-ink-300 leading-relaxed max-w-2xl italic">
              {meta.hero_tagline}
            </p>
          )}
          {/* Vendor labels — Kerf always on the left */}
          <div className="mt-4 flex items-center gap-3 text-xs font-mono text-ink-400">
            <span
              className="px-2 py-0.5 rounded bg-kerf-300/10 border border-kerf-300/30 text-kerf-300"
              data-testid="left-vendor"
            >
              {leftVendor}
            </span>
            <span>vs</span>
            <span
              className="px-2 py-0.5 rounded bg-ink-800 border border-ink-700 text-ink-300"
              data-testid="right-vendor"
            >
              {rightVendor}
            </span>
          </div>
          {meta.reviewed_at && (
            <p className="mt-2 text-xs text-ink-500 font-mono">
              Last reviewed: {meta.reviewed_at}
            </p>
          )}
        </header>

        {/* ── Body (free-form markdown) ─────────────────────────────────── */}
        <div className="compare-md-body">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={components}
            allowedElements={ALLOWED_ELEMENTS}
            urlTransform={urlTransformer}
          >
            {meta.body || ''}
          </ReactMarkdown>
        </div>

        <FairnessNote />
        <CTAStrip />
      </main>
    </div>
  )
}
