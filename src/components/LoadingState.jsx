/**
 * LoadingState.jsx — Consistent skeleton / loading placeholder.
 *
 * Provides a set of composable skeleton primitives for use wherever data is
 * being fetched asynchronously. The skeletons pulse with a CSS animation and
 * are announced to screen readers via `role="status"` + `aria-busy="true"` on
 * the wrapper.
 *
 * Public API
 * ──────────
 *   default export  LoadingState({ rows, showAvatar, label, className })
 *     A pre-composed "card skeleton" that fits most list/detail loading states.
 *     - rows:       number  Number of text-line skeletons to render. Default 3.
 *     - showAvatar: bool    Show a circular avatar skeleton at the top. Default false.
 *     - label:      string  sr-only announcement text. Default 'Loading…'.
 *     - className:  string  Extra classes on the wrapper.
 *
 *   named export  SkeletonLine({ width, height, className })
 *     A single animated placeholder bar.
 *     - width:   string  Tailwind width class or 'full'. Default 'full'.
 *     - height:  string  Tailwind height class. Default 'h-4'.
 *
 *   named export  SkeletonBlock({ aspect, className })
 *     A rectangular block placeholder (for images / charts).
 *     - aspect: string  Tailwind aspect-ratio class. Default 'aspect-video'.
 *
 *   named export  SkeletonCircle({ size, className })
 *     A circular avatar/icon placeholder.
 *     - size: string  Tailwind size class. Default 'size-10'.
 *
 * Accessibility
 * ─────────────
 *   - Wrapper uses role="status" aria-busy="true" aria-live="polite".
 *   - A sr-only span announces the label text so screen readers don't read
 *     the meaningless skeleton elements.
 *   - Once data loads, swap LoadingState for the real content; aria-busy
 *     disappears naturally (the component unmounts).
 *
 * Animation
 * ─────────
 *   Standard Tailwind `animate-pulse` (opacity 1 → 0.5 → 1). Respects
 *   `prefers-reduced-motion: reduce` — Tailwind disables animate-* when
 *   the user has reduced motion enabled.
 */

import clsx from 'clsx'

// ── Primitive skeletons ───────────────────────────────────────────────────────

/**
 * A single animated placeholder bar.
 *
 * @param {{ width?: string, height?: string, className?: string }} props
 */
export function SkeletonLine({ width = 'w-full', height = 'h-4', className }) {
  return (
    <div
      aria-hidden="true"
      className={clsx(
        'animate-pulse rounded-md bg-ink-700',
        width,
        height,
        className,
      )}
    />
  )
}

/**
 * A rectangular block placeholder for images or charts.
 *
 * @param {{ aspect?: string, className?: string }} props
 */
export function SkeletonBlock({ aspect = 'aspect-video', className }) {
  return (
    <div
      aria-hidden="true"
      className={clsx(
        'animate-pulse rounded-lg bg-ink-700 w-full',
        aspect,
        className,
      )}
    />
  )
}

/**
 * A circular avatar / icon placeholder.
 *
 * @param {{ size?: string, className?: string }} props
 */
export function SkeletonCircle({ size = 'size-10', className }) {
  return (
    <div
      aria-hidden="true"
      className={clsx(
        'animate-pulse rounded-full bg-ink-700 shrink-0',
        size,
        className,
      )}
    />
  )
}

// ── Composed card skeleton ────────────────────────────────────────────────────

/**
 * Pre-composed loading skeleton that fits most list-item / detail-card states.
 *
 * @param {{ rows?: number, showAvatar?: boolean, label?: string, className?: string }} props
 */
export default function LoadingState({
  rows = 3,
  showAvatar = false,
  label = 'Loading…',
  className,
}) {
  return (
    <div
      role="status"
      aria-busy="true"
      aria-live="polite"
      className={clsx('flex flex-col gap-3 p-4', className)}
    >
      <span className="sr-only">{label}</span>

      {showAvatar && (
        <div className="flex items-center gap-3">
          <SkeletonCircle />
          <div className="flex flex-col gap-2 flex-1">
            <SkeletonLine width="w-1/3" height="h-3" />
            <SkeletonLine width="w-1/4" height="h-3" />
          </div>
        </div>
      )}

      <div className="flex flex-col gap-2">
        {Array.from({ length: rows }, (_, i) => (
          <SkeletonLine
            key={i}
            // Vary widths to look more natural
            width={i === rows - 1 ? 'w-2/3' : 'w-full'}
            height="h-4"
          />
        ))}
      </div>
    </div>
  )
}
