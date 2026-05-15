/**
 * Kerf brand mark — yellow K on dark rounded background.
 * currentColor lets callers tint via text-* utilities.
 */

export function LogoMark({ size = 28, className = '', title = 'kerf' }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      className={className}
      role="img"
      aria-label={title}
      shapeRendering="geometricPrecision"
    >
      <title>{title}</title>
      {/* K glyph only — transparent so it sits inline on any surface.
          Geometry matches public/favicon.svg exactly. */}
      <rect x="7" y="6" width="3.5" height="20" fill="currentColor" />
      <polygon points="10.5,16 26,6 26,13" fill="currentColor" />
      <polygon points="10.5,16 26,19 26,26" fill="currentColor" />
    </svg>
  )
}

export function LogoWordmark({ className = '', size = 22 }) {
  return (
    <span
      className={`inline-flex items-center gap-2 font-display leading-none ${className}`}
    >
      <LogoMark size={size} className="text-kerf-300" />
      <span
        className="font-semibold text-ink-100"
        style={{ fontSize: `${size * 0.95}px`, letterSpacing: '-0.02em' }}
      >
        kerf
      </span>
    </span>
  )
}
