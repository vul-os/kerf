/**
 * CompareMdRoute.jsx — top-level route for /compare/:slug.
 *
 * TODO (next agent): once a slug's .md file exists under public/compare/<slug>.md,
 * switch the corresponding entry in compare/index.jsx to use this route instead
 * of the legacy JSX page. Migrate slugs one-by-one. Until migrated, this route
 * falls back to the legacy JSX component if the .md file fetch returns 404.
 *
 * Behaviour:
 *   1. Fetches `/compare/<slug>.md` from the public/ directory.
 *   2. If the fetch succeeds, parses front-matter + body with parseCompareMd
 *      and renders <CompareMd> (markdown-driven).
 *   3. If the fetch returns 404 (or any error), falls back to the legacy JSX
 *      compare page for that slug (if registered in LEGACY_PAGES below).
 *   4. If neither is available, renders a 404 message.
 *
 * Kerf is ALWAYS on the left side of any comparison — this invariant is
 * enforced at two levels:
 *   - parseCompareMd always sets meta.left = 'kerf'
 *   - CompareMd renders Kerf as the left/accent vendor regardless of meta.left
 *
 * The Header/Footer wrappers are applied here (not inside CompareMd) so that
 * the legacy JSX pages continue to supply their own wrappers unchanged.
 */

import { useState, useEffect, lazy, Suspense } from 'react'
import { useParams, Navigate } from 'react-router-dom'
import Header from '../../components/Header.jsx'
import Footer from '../../components/Footer.jsx'
import CompareMd from '../../components/CompareMd.jsx'
import { parseCompareMd } from '../../lib/compareMdParser.js'

/* -------------------------------------------------------------------------- */
/* Legacy JSX page registry                                                    */
/* -------------------------------------------------------------------------- */
/*
 * Each entry maps a slug to the lazy-loaded legacy JSX component. When the
 * .md file is absent (404), this registry is consulted for a fallback.
 *
 * TODO: Remove entries from this map as each slug is migrated to .md.
 */
const LEGACY_PAGES = {
  freecad:    lazy(() => import('./Freecad.jsx')),
  fusion:     lazy(() => import('./Fusion.jsx')),
  kicad:      lazy(() => import('./Kicad.jsx')),
  solidworks: lazy(() => import('./Solidworks.jsx')),
  onshape:    lazy(() => import('./Onshape.jsx')),
  inventor:   lazy(() => import('./Inventor.jsx')),
  autocad:    lazy(() => import('./Autocad.jsx')),
  altium:     lazy(() => import('./Altium.jsx')),
  revit:      lazy(() => import('./Revit.jsx')),
  civil3d:    lazy(() => import('./Civil3d.jsx')),
  rhino:      lazy(() => import('./Rhino.jsx')),
  matrixgold: lazy(() => import('./MatrixGold.jsx')),
  blender:    lazy(() => import('./Blender.jsx')),
  max3ds:     lazy(() => import('./Max3ds.jsx')),
}

/* -------------------------------------------------------------------------- */
/* CompareMdRoute                                                              */
/* -------------------------------------------------------------------------- */

export default function CompareMdRoute() {
  const { slug } = useParams()
  const [state, setState] = useState({
    status: 'loading',  // 'loading' | 'md' | 'legacy' | 'not-found'
    meta: null,
    error: null,
  })

  useEffect(() => {
    if (!slug) {
      setState({ status: 'not-found', meta: null, error: null })
      return
    }

    let cancelled = false

    async function loadMd() {
      setState({ status: 'loading', meta: null, error: null })
      try {
        const res = await fetch(`/compare/${slug}.md`)
        if (!res.ok) {
          // 404 or other error — fall back to legacy JSX if registered
          if (!cancelled) {
            const hasLegacy = slug in LEGACY_PAGES
            setState({
              status: hasLegacy ? 'legacy' : 'not-found',
              meta: null,
              error: null,
            })
          }
          return
        }
        const raw = await res.text()
        const meta = parseCompareMd(raw, slug)
        if (!cancelled) {
          setState({ status: 'md', meta, error: null })
        }
      } catch (err) {
        if (!cancelled) {
          // Network error — fall back to legacy if available
          const hasLegacy = slug in LEGACY_PAGES
          setState({
            status: hasLegacy ? 'legacy' : 'not-found',
            meta: null,
            error: String(err?.message || err),
          })
        }
      }
    }

    loadMd()
    return () => { cancelled = true }
  }, [slug])

  // ── Render ──────────────────────────────────────────────────────────────────

  if (state.status === 'loading') {
    return (
      <div className="min-h-screen bg-ink-950 text-ink-100">
        <Header />
        <CompareMd loading={true} meta={null} />
        <Footer />
      </div>
    )
  }

  if (state.status === 'md') {
    return (
      <div className="min-h-screen bg-ink-950 text-ink-100">
        <Header />
        <CompareMd meta={state.meta} />
        <Footer />
      </div>
    )
  }

  if (state.status === 'legacy') {
    const LegacyPage = LEGACY_PAGES[slug]
    if (!LegacyPage) {
      return <Navigate to="/compare" replace />
    }
    return (
      <Suspense
        fallback={
          <div className="min-h-screen bg-ink-950 text-ink-100">
            <Header />
            <CompareMd loading={true} meta={null} />
            <Footer />
          </div>
        }
      >
        <LegacyPage />
      </Suspense>
    )
  }

  // not-found
  return (
    <div className="min-h-screen bg-ink-950 text-ink-100">
      <Header />
      <main className="mx-auto max-w-4xl px-6 pt-24 pb-20 text-center">
        <h1 className="font-display text-3xl font-semibold text-ink-100 mb-4">
          Comparison not found
        </h1>
        <p className="text-ink-400 mb-8">
          No comparison page exists for <code className="font-mono text-kerf-300">{slug}</code>.
        </p>
        <a
          href="/compare"
          className="text-kerf-300 hover:text-kerf-200 underline underline-offset-2 text-sm"
        >
          ← Back to all comparisons
        </a>
      </main>
      <Footer />
    </div>
  )
}
