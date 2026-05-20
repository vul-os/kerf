import { Link } from 'react-router-dom'
import { LogoWordmark } from '../components/Logo.jsx'

/**
 * NotFound — catch-all 404 page (T-A3).
 *
 * Rendered whenever no other route matches. Replaces the silent
 * `<Navigate to="/" replace />` so users on mistyped/dead URLs get
 * meaningful feedback instead of an invisible redirect.
 *
 * Accessibility contract:
 *   - `<main>` with `aria-labelledby` pointing at the heading
 *   - Heading conveys the HTTP-equivalent concept ("Page not found")
 *   - Home link is a real `<a>` (via React Router Link) with descriptive text
 */
export default function NotFound() {
  return (
    <div className="min-h-screen flex flex-col bg-ink-950 text-ink-100">
      {/* Subtle dot-grid — purely decorative */}
      <div
        aria-hidden="true"
        className="pointer-events-none fixed inset-0 opacity-[0.12]"
        style={{
          backgroundImage:
            'radial-gradient(circle at 1px 1px, rgba(255,255,255,0.5) 1px, transparent 0)',
          backgroundSize: '28px 28px',
          maskImage: 'radial-gradient(ellipse at center, black 30%, transparent 75%)',
          WebkitMaskImage: 'radial-gradient(ellipse at center, black 30%, transparent 75%)',
        }}
      />

      <main
        aria-labelledby="not-found-heading"
        className="relative flex-1 flex flex-col items-center justify-center px-6 py-12 text-center"
      >
        <Link to="/" aria-label="Kerf home" className="mb-10 inline-block">
          <LogoWordmark className="text-2xl" />
        </Link>

        {/* Large muted 404 numeral — decorative, hidden from SR */}
        <p aria-hidden="true" className="text-[8rem] font-black leading-none text-ink-800 select-none">
          404
        </p>

        <h1
          id="not-found-heading"
          className="mt-4 text-2xl font-semibold text-ink-100"
        >
          Page not found
        </h1>

        <p className="mt-3 text-sm text-ink-400 max-w-xs">
          The URL you visited doesn&apos;t exist or may have moved.
        </p>

        <Link
          to="/"
          className="mt-8 inline-flex items-center gap-2 rounded-md bg-brand-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-brand-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-400 transition-colors"
        >
          Go to home
        </Link>
      </main>
    </div>
  )
}
