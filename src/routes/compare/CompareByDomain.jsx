/**
 * CompareByDomain.jsx — cross-CAD domain matrix page.
 *
 * Route: /compare/by-domain/:slug  (slug = domain word: geometry, structural, …, cost)
 *
 * Shows a single big pivot table: rows are feature names, columns are
 * Feature | Kerf | <CAD1> | <CAD2> | ... (only CADs with rows in this domain).
 *
 * SEO: <title>{domain title} CAD compared — Kerf vs N tools</title>
 *      meta description, JSON-LD WebPage.
 */

import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import Header from '../../components/Header.jsx'
import Footer from '../../components/Footer.jsx'
import { DOMAIN_META, STATUS_META, TONE_CLASSES, loadManifest, pivotByDomain } from '../../lib/compareFeatures.js'

/* -------------------------------------------------------------------------- */
/* Helpers                                                                     */
/* -------------------------------------------------------------------------- */

function StatusCell({ status }) {
  const s = STATUS_META[status] ?? STATUS_META.unknown
  const tone = TONE_CLASSES[s.tone]
  return (
    <span
      className={[
        'inline-flex items-center justify-center w-6 h-6 rounded-full text-[11px] font-mono font-bold',
        'border',
        tone.bg, tone.border, tone.text,
      ].join(' ')}
      title={s.label}
      aria-label={s.label}
      data-testid={`status-cell-${status}`}
    >
      {s.symbol}
    </span>
  )
}

/* -------------------------------------------------------------------------- */
/* Domain matrix table                                                          */
/* -------------------------------------------------------------------------- */

function DomainMatrix({ features, cadSlugs, cadNames }) {
  const featureNames = [...features.keys()]

  if (featureNames.length === 0) {
    return (
      <p className="text-ink-500 text-sm py-8 text-center">
        No structured feature data available for this domain yet.
      </p>
    )
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-ink-800" data-testid="domain-matrix-table">
      <table className="min-w-max w-full text-sm">
        <thead className="border-b border-ink-800 bg-ink-900/60">
          <tr>
            <th className="text-left px-4 py-3 font-mono text-[10px] uppercase tracking-wider text-ink-400 whitespace-nowrap sticky left-0 bg-ink-900/90 z-10 min-w-[200px]">
              Feature
            </th>
            {/* Kerf column — pinned accent */}
            <th className="text-left px-4 py-3 font-mono text-[10px] uppercase tracking-wider text-kerf-300 whitespace-nowrap min-w-[80px]" data-testid="domain-kerf-header">
              Kerf
            </th>
            {cadSlugs.map((slug) => (
              <th
                key={slug}
                className="text-left px-4 py-3 font-mono text-[10px] uppercase tracking-wider text-ink-400 whitespace-nowrap min-w-[100px]"
              >
                <Link
                  to={`/compare/${slug}`}
                  className="hover:text-ink-200 transition-colors underline underline-offset-2"
                >
                  {cadNames[slug] ?? slug}
                </Link>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {featureNames.map((feat, idx) => {
            const entry = features.get(feat)
            return (
              <tr
                key={feat}
                className={[
                  'border-b border-ink-800/50 hover:bg-ink-900/30 transition-colors',
                  idx % 2 === 0 ? '' : 'bg-ink-900/20',
                ].join(' ')}
                data-testid="domain-feature-row"
              >
                <td className="px-4 py-2.5 text-ink-200 font-medium text-sm align-middle sticky left-0 bg-ink-950/90 z-10 whitespace-nowrap">
                  {feat}
                </td>
                <td className="px-4 py-2.5 align-middle">
                  <StatusCell status={entry.kerf} />
                </td>
                {cadSlugs.map((slug) => (
                  <td key={slug} className="px-4 py-2.5 align-middle">
                    <StatusCell status={entry.competitors[slug] ?? 'unknown'} />
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* CompareByDomain                                                              */
/* -------------------------------------------------------------------------- */

export default function CompareByDomain() {
  const { slug } = useParams()

  // Resolve domain slug → domain meta synchronously
  const domainMeta = DOMAIN_META.find((d) => d.slug === slug)

  // Initialise to not-found immediately when slug is unknown — avoids showing
  // the loading spinner only to flip to 404 after the useEffect fires.
  const [state, setState] = useState(() => ({
    status: domainMeta ? 'loading' : 'not-found',
    data: null,
  }))

  useEffect(() => {
    // domainMeta is null → state was already initialised to 'not-found'
    if (!domainMeta) return

    let cancelled = false
    ;(async () => {
      setState({ status: 'loading', data: null })
      try {
        const manifest = await loadManifest()
        const { features, cadSlugs } = pivotByDomain(manifest.items, domainMeta.code)
        // Build a slug → competitor name map
        const cadNames = {}
        for (const item of manifest.items) {
          if (cadSlugs.includes(item.slug)) {
            cadNames[item.slug] = item.competitor
          }
        }
        if (!cancelled) {
          setState({ status: 'ok', data: { features, cadSlugs, cadNames, totalItems: manifest.items.length } })
        }
      } catch (err) {
        if (!cancelled) {
          setState({ status: 'error', data: null })
        }
      }
    })()
    return () => { cancelled = true }
  }, [slug, domainMeta])

  // ── SEO helpers ──────────────────────────────────────────────────────────────

  const cadCount = state.data?.cadSlugs?.length ?? 0
  const featureCount = state.data?.features?.size ?? 0
  const pageTitle = domainMeta
    ? `${domainMeta.title} CAD compared — Kerf vs ${cadCount} tool${cadCount !== 1 ? 's' : ''}`
    : 'Domain not found — Kerf Compare'
  const metaDescription = domainMeta
    ? `How Kerf compares to ${cadCount} tools in ${domainMeta.title}: ${featureCount} features across Geometry, Structural, Manufacturing and more.`
    : ''

  // JSON-LD
  const jsonLd = domainMeta
    ? JSON.stringify({
        '@context': 'https://schema.org',
        '@type': 'WebPage',
        name: pageTitle,
        description: metaDescription,
        url: `https://kerf.sh/compare/by-domain/${slug}`,
      })
    : null

  // ── Not found ──────────────────────────────────────────────────────────────

  if (state.status === 'not-found') {
    return (
      <div className="min-h-screen bg-ink-950 text-ink-100">
        <Header />
        <main className="mx-auto max-w-4xl px-6 pt-24 pb-20 text-center">
          <h1 className="font-display text-3xl font-semibold text-ink-100 mb-4">
            Domain not found
          </h1>
          <p className="text-ink-400 mb-8">
            No domain exists with slug{' '}
            <code className="font-mono text-kerf-300">{slug}</code>.
          </p>
          <Link
            to="/compare#by-domain"
            className="text-kerf-300 hover:text-kerf-200 underline underline-offset-2 text-sm"
          >
            Browse all domains
          </Link>
        </main>
        <Footer />
      </div>
    )
  }

  // ── Error ─────────────────────────────────────────────────────────────────

  if (state.status === 'error') {
    return (
      <div className="min-h-screen bg-ink-950 text-ink-100">
        <Header />
        <main className="mx-auto max-w-4xl px-6 pt-24 pb-20 text-center">
          <h1 className="font-display text-3xl font-semibold text-ink-100 mb-4">
            Could not load comparison data
          </h1>
          <p className="text-ink-400 mb-8">
            There was a problem loading the feature matrix. Please try again later.
          </p>
          <Link to="/compare" className="text-kerf-300 hover:text-kerf-200 underline underline-offset-2 text-sm">
            Back to all comparisons
          </Link>
        </main>
        <Footer />
      </div>
    )
  }

  // ── Main render ───────────────────────────────────────────────────────────

  const { features, cadSlugs, cadNames } = state.data ?? { features: new Map(), cadSlugs: [], cadNames: {} }

  return (
    <div className="min-h-screen bg-ink-950 text-ink-100">
      {/* SEO */}
      {jsonLd && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: jsonLd }}
        />
      )}

      <Header />

      <main
        className="mx-auto max-w-6xl px-6 pt-12 pb-24"
        aria-label={`${domainMeta?.title ?? slug} CAD comparison`}
      >
        {/* Breadcrumb */}
        <Link
          to="/compare#by-domain"
          className="inline-flex items-center gap-1.5 text-sm text-ink-400 hover:text-ink-100 transition-colors mb-8"
        >
          <span aria-hidden="true">←</span>
          All comparisons
        </Link>

        {/* Hero */}
        <header className="mb-10">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-kerf-300 mb-2">
            Compare by domain
          </p>
          {state.status === 'loading' ? (
            <div className="h-10 w-64 rounded-lg bg-ink-800 animate-pulse mb-4" />
          ) : (
            <h1 className="font-display text-3xl sm:text-4xl lg:text-5xl font-semibold tracking-[-0.02em] leading-tight" data-testid="domain-hero-title">
              {domainMeta?.title} CAD compared
            </h1>
          )}
          {state.status === 'ok' && (
            <p className="mt-4 text-ink-300 leading-relaxed max-w-2xl text-sm sm:text-base">
              How Kerf compares to {cadCount} tool{cadCount !== 1 ? 's' : ''} in{' '}
              <strong className="text-ink-100">{domainMeta?.title}</strong> across{' '}
              {featureCount} feature{featureCount !== 1 ? 's' : ''}.
            </p>
          )}
        </header>

        {/* Matrix */}
        {state.status === 'loading' ? (
          <div className="rounded-xl border border-ink-800 bg-ink-900/40 p-8 flex items-center justify-center">
            <p className="text-ink-400 text-sm font-mono animate-pulse">Loading feature matrix…</p>
          </div>
        ) : (
          <DomainMatrix
            features={features}
            cadSlugs={cadSlugs}
            cadNames={cadNames}
          />
        )}

        {/* Legend */}
        {state.status === 'ok' && (
          <div className="mt-6 flex flex-wrap gap-3">
            {Object.entries(STATUS_META).map(([key, s]) => {
              const tone = TONE_CLASSES[s.tone]
              return (
                <span
                  key={key}
                  className={[
                    'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-mono border',
                    tone.bg, tone.border, tone.text,
                  ].join(' ')}
                >
                  <span aria-hidden="true">{s.symbol}</span>
                  {s.label}
                </span>
              )
            })}
          </div>
        )}

        {/* Footer CTA */}
        <div className="mt-12 pt-8 border-t border-ink-800 text-center">
          <p className="text-sm text-ink-400 mb-3">Browse another domain</p>
          <Link
            to="/compare#by-domain"
            className="inline-flex items-center gap-1.5 text-kerf-300 hover:text-kerf-200 text-sm font-medium transition-colors"
          >
            Browse all domains →
          </Link>
        </div>
      </main>

      <Footer />
    </div>
  )
}
