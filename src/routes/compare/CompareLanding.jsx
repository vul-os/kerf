// TODO(parent): wire as the new /compare default route, demote current /compare index.jsx to /compare/legacy

/**
 * CompareLanding.jsx — polished Compare landing page (markdown era).
 *
 * Single entry point with:
 *   • Search box — substring match on competitor + slug + hero_tagline
 *   • Category pill row — filter by CAD domain
 *   • Responsive card grid — "Kerf vs <competitor>" cards
 *   • By-domain grid — 14 D-domains as clickable cards
 *
 * Does NOT modify any existing file. Intended to become the /compare default
 * route once wired by the parent (see TODO above).
 */
import { useState, useMemo, useCallback, useId, useEffect } from 'react'
import { Search, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import Header from '../../components/Header.jsx'
import Footer from '../../components/Footer.jsx'
import CompareCategoryPill from '../../components/CompareCategoryPill.jsx'
import CompareCardGrid from '../../components/CompareCardGrid.jsx'
import {
  compareSearch,
  groupByCategory,
  COMPARE_CATEGORIES,
} from '../../lib/compareSearch.js'
import { DOMAIN_META, loadManifest } from '../../lib/compareFeatures.js'

/* -------------------------------------------------------------------------- */
/* Domain accent colours (matching CompareCardGrid pattern)                    */
/* -------------------------------------------------------------------------- */

const DOMAIN_ACCENTS = [
  'text-kerf-300 bg-kerf-300/10 border-kerf-300/25',
  'text-sky-400 bg-sky-400/10 border-sky-400/25',
  'text-violet-400 bg-violet-400/10 border-violet-400/25',
  'text-orange-400 bg-orange-400/10 border-orange-400/25',
  'text-cyan-400 bg-cyan-400/10 border-cyan-400/25',
  'text-emerald-400 bg-emerald-400/10 border-emerald-400/25',
  'text-amber-400 bg-amber-400/10 border-amber-400/25',
  'text-lime-400 bg-lime-400/10 border-lime-400/25',
  'text-rose-400 bg-rose-400/10 border-rose-400/25',
  'text-yellow-400 bg-yellow-400/10 border-yellow-400/25',
  'text-teal-400 bg-teal-400/10 border-teal-400/25',
  'text-fuchsia-400 bg-fuchsia-400/10 border-fuchsia-400/25',
  'text-pink-400 bg-pink-400/10 border-pink-400/25',
  'text-indigo-400 bg-indigo-400/10 border-indigo-400/25',
]

/* -------------------------------------------------------------------------- */
/* By-domain card grid                                                          */
/* -------------------------------------------------------------------------- */

function DomainCard({ domain, cadCount, accent }) {
  return (
    <Link
      to={`/compare/by-domain/${domain.slug}`}
      className="group relative flex flex-col rounded-2xl border border-ink-800 bg-ink-900/40 p-4 sm:p-5 hover:border-ink-700 hover:bg-ink-900/70 transition-colors"
      aria-label={`Browse ${domain.title} comparisons`}
      data-testid="domain-card"
    >
      {/* Domain code badge */}
      <span
        className={[
          'self-start mb-3 rounded-full px-2.5 py-0.5 text-[10px] font-mono font-medium',
          'border tracking-wide uppercase',
          accent,
        ].join(' ')}
      >
        {domain.code}
      </span>

      <h3 className="font-display text-sm font-semibold tracking-tight text-ink-100 leading-snug mb-1">
        {domain.title}
      </h3>
      <p className="text-xs text-ink-500 font-mono mt-auto pt-2">
        {cadCount > 0 ? `${cadCount} tool${cadCount !== 1 ? 's' : ''}` : 'No data yet'}
        {' '}covered
      </p>
      <p className="mt-2 text-xs font-medium text-kerf-300 group-hover:text-kerf-200 transition-colors">
        Compare →
      </p>
    </Link>
  )
}

/* -------------------------------------------------------------------------- */
/* Page                                                                       */
/* -------------------------------------------------------------------------- */

export default function CompareLanding() {
  const [query, setQuery]     = useState('')
  const [category, setCategory] = useState(null)
  const [domainCadCounts, setDomainCadCounts] = useState({})
  const searchId = useId()

  // Load manifest to get per-domain CAD counts
  useEffect(() => {
    loadManifest().then((manifest) => {
      const counts = {}
      for (const dm of DOMAIN_META) {
        counts[dm.code] = 0
      }
      for (const item of manifest.items) {
        if (!Array.isArray(item.features)) continue
        const seenDomains = new Set()
        for (const feat of item.features) {
          if (feat.domain && !seenDomains.has(feat.domain)) {
            seenDomains.add(feat.domain)
            if (feat.domain in counts) counts[feat.domain]++
          }
        }
      }
      setDomainCadCounts(counts)
    }).catch(() => {/* silently ignore */})
  }, [])

  // Filtered item list
  const results = useMemo(
    () => compareSearch(query, category),
    [query, category],
  )

  // When query is non-empty or a category is active → flat list.
  // When both are empty → grouped by category (default landing view).
  const isFiltering = query.trim().length > 0 || category !== null
  const groups = useMemo(
    () => (isFiltering ? null : groupByCategory(results)),
    [isFiltering, results],
  )

  const handleClearSearch = useCallback(() => setQuery(''), [])
  const handleClearAll    = useCallback(() => { setQuery(''); setCategory(null) }, [])

  return (
    <div className="min-h-screen bg-ink-950 text-ink-100">
      <Header />

      <main
        className="mx-auto max-w-5xl px-6 pt-14 pb-24"
        aria-label="Compare Kerf against other CAD and EDA tools"
      >
        {/* ── Hero ── */}
        <div className="mb-10">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-kerf-300 mb-2">
            Compare
          </p>
          <h1 className="font-display text-3xl sm:text-4xl lg:text-5xl font-semibold tracking-[-0.02em] leading-tight">
            How does Kerf compare?
          </h1>
          {/* Quick nav: By CAD | By domain */}
          <div className="mt-4 flex items-center gap-4 text-sm font-mono">
            <a
              href="#by-cad"
              className="text-kerf-300 hover:text-kerf-200 transition-colors underline underline-offset-2"
            >
              By CAD
            </a>
            <span className="text-ink-700" aria-hidden="true">|</span>
            <a
              href="#by-domain"
              className="text-ink-400 hover:text-ink-200 transition-colors underline underline-offset-2"
            >
              By domain
            </a>
          </div>
          <p className="mt-4 text-ink-300 leading-relaxed max-w-2xl text-sm sm:text-base">
            These tools are genuinely excellent — many are decades old, deeply
            validated, and free or affordable. Kerf is young by comparison.
            Each page credits every competitor's real strengths first, marks
            Kerf's gaps without spin, and links out to a full feature matrix.
          </p>
          <p className="mt-3 text-xs text-ink-500 leading-relaxed max-w-2xl">
            Product and company names referenced on these pages are trademarks
            of their respective owners. Comparisons are for informational
            purposes and do not imply endorsement.
          </p>
        </div>

        {/* ── Search + filters ── */}
        <div className="mb-8 space-y-4">
          {/* Search box */}
          <div className="relative max-w-lg">
            <label htmlFor={searchId} className="sr-only">
              Search comparisons
            </label>
            <Search
              size={15}
              className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-500"
              aria-hidden="true"
            />
            <input
              id={searchId}
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search tools… (e.g. FreeCAD, SPICE, BIM)"
              className={[
                'w-full rounded-xl border border-ink-700 bg-ink-900/60 py-2.5 pl-9 pr-10',
                'text-sm text-ink-100 placeholder:text-ink-600',
                'focus:border-kerf-400 focus:outline-none focus:ring-1 focus:ring-kerf-400/40',
                'transition-colors',
              ].join(' ')}
              data-testid="compare-search-input"
            />
            {query.length > 0 && (
              <button
                onClick={handleClearSearch}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-500 hover:text-ink-300 transition-colors"
                aria-label="Clear search"
                data-testid="compare-search-clear"
              >
                <X size={14} />
              </button>
            )}
          </div>

          {/* Category pills */}
          <CompareCategoryPill
            categories={COMPARE_CATEGORIES}
            active={category}
            onSelect={setCategory}
          />

          {/* Active filter summary */}
          {isFiltering && (
            <div className="flex items-center gap-3 text-xs text-ink-400 font-mono">
              <span>
                {results.length === 0
                  ? 'No results'
                  : `${results.length} comparison${results.length === 1 ? '' : 's'}`}
                {query.trim() && ` for "${query.trim()}"`}
                {category && ` in ${COMPARE_CATEGORIES.find((c) => c.id === category)?.label ?? category}`}
              </span>
              <button
                onClick={handleClearAll}
                className="text-kerf-300 hover:text-kerf-200 transition-colors underline underline-offset-2"
                data-testid="compare-clear-all"
              >
                Clear all
              </button>
            </div>
          )}
        </div>

        {/* ── Content area (by CAD) ── */}
        <section id="by-cad" className="scroll-mt-20">
          {isFiltering ? (
            /* Flat results when filtering */
            <CompareCardGrid items={results} />
          ) : (
            /* Grouped by category when browsing */
            <div className="space-y-12">
              {groups?.map((group) => (
                <section
                  key={group.category}
                  aria-label={`${group.label} comparisons`}
                  className="scroll-mt-20"
                >
                  {/* Section header */}
                  <header className="mb-4 flex items-baseline gap-3">
                    <h2 className="font-display text-lg sm:text-xl font-semibold tracking-tight text-ink-100">
                      {group.label}
                    </h2>
                    <span className="text-xs font-mono text-ink-500">
                      {group.items.length} tool{group.items.length !== 1 ? 's' : ''}
                    </span>
                  </header>

                  <CompareCardGrid items={group.items} />
                </section>
              ))}
            </div>
          )}
        </section>

        {/* ── By domain section ── */}
        <section
          id="by-domain"
          className="mt-20 scroll-mt-20"
          aria-label="Browse comparisons by engineering domain"
        >
          <header className="mb-6">
            <h2 className="font-display text-2xl sm:text-3xl font-semibold tracking-tight text-ink-100">
              Browse by domain
            </h2>
            <p className="mt-2 text-sm text-ink-400 max-w-2xl">
              See how Kerf stacks up against all tools in a specific engineering discipline.
              Each domain page shows a full cross-tool feature matrix.
            </p>
          </header>

          <div
            className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3"
            data-testid="domain-card-grid"
          >
            {DOMAIN_META.map((domain, idx) => (
              <DomainCard
                key={domain.code}
                domain={domain}
                cadCount={domainCadCounts[domain.code] ?? 0}
                accent={DOMAIN_ACCENTS[idx] ?? DOMAIN_ACCENTS[0]}
              />
            ))}
          </div>
        </section>
      </main>

      <Footer />
    </div>
  )
}
