/**
 * EmptyState.jsx — Consistent empty / zero-data placeholder.
 *
 * Rendered when a list, table, or view has no content to show. Provides a
 * clear, actionable message with an optional Lucide icon, title, description,
 * and a primary action button/link.
 *
 * Public API
 * ──────────
 *   default export  EmptyState({ icon, title, description, action, size, className })
 *     - icon:        ReactNode  A Lucide icon element (or any SVG/element).
 *                               Rendered at 2× default size; aria-hidden.
 *     - title:       string     Required. Short headline (e.g. "No files yet").
 *     - description: string     Optional explanatory sentence.
 *     - action:      { label, onClick?, href?, disabled? }
 *                               Optional primary CTA button or link.
 *     - size:        'sm'|'md'|'lg'  Overall scale. Default 'md'.
 *     - className:   string     Extra classes on the root element.
 *
 * Accessibility
 * ─────────────
 *   - `role="status"` so screen readers can announce the empty condition
 *     when it replaces a live region that had content.
 *   - The icon is `aria-hidden` since the title + description carry the full
 *     meaning.
 *   - The action button is a standard <button> or <a> with focusable tab stop.
 *
 * Examples
 * ────────
 *   <EmptyState
 *     icon={<FileX size={40} />}
 *     title="No files yet"
 *     description="Upload a file or create a new one to get started."
 *     action={{ label: 'New file', onClick: handleNew }}
 *   />
 *
 *   <EmptyState
 *     icon={<SearchX size={40} />}
 *     title="No results"
 *     description={`No files match "${query}".`}
 *   />
 */

import clsx from 'clsx'

const SIZES = {
  sm: {
    wrapper: 'gap-2 py-8 px-4',
    iconWrap: 'mb-1',
    title: 'text-sm font-semibold',
    desc: 'text-xs',
    btn: 'h-8 px-3 text-xs rounded-md',
  },
  md: {
    wrapper: 'gap-3 py-12 px-6',
    iconWrap: 'mb-2',
    title: 'text-base font-semibold',
    desc: 'text-sm',
    btn: 'h-9 px-4 text-sm rounded-lg',
  },
  lg: {
    wrapper: 'gap-4 py-20 px-8',
    iconWrap: 'mb-3',
    title: 'text-lg font-semibold',
    desc: 'text-base',
    btn: 'h-10 px-5 text-sm rounded-lg',
  },
}

export default function EmptyState({
  icon,
  title,
  description,
  action,
  size = 'md',
  className,
}) {
  const s = SIZES[size] ?? SIZES.md

  return (
    <div
      role="status"
      aria-label={title}
      className={clsx(
        'flex flex-col items-center justify-center text-center',
        s.wrapper,
        className,
      )}
    >
      {icon && (
        <div
          aria-hidden="true"
          className={clsx('text-ink-500', s.iconWrap)}
        >
          {icon}
        </div>
      )}

      <p className={clsx('text-ink-100', s.title)}>{title}</p>

      {description && (
        <p className={clsx('text-ink-400 max-w-sm', s.desc)}>{description}</p>
      )}

      {action && (
        <div className="mt-1">
          {action.href ? (
            <a
              href={action.href}
              className={clsx(
                'inline-flex items-center justify-center font-medium',
                'bg-kerf-300 text-ink-950 hover:bg-kerf-200 active:bg-kerf-400',
                'transition-colors duration-150',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/50 focus-visible:ring-offset-2 focus-visible:ring-offset-ink-950',
                s.btn,
              )}
            >
              {action.label}
            </a>
          ) : (
            <button
              type="button"
              onClick={action.onClick}
              disabled={action.disabled}
              className={clsx(
                'inline-flex items-center justify-center font-medium',
                'bg-kerf-300 text-ink-950 hover:bg-kerf-200 active:bg-kerf-400',
                'transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/50 focus-visible:ring-offset-2 focus-visible:ring-offset-ink-950',
                s.btn,
              )}
            >
              {action.label}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
