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
      {/* Dark rounded background */}
      <rect width="32" height="32" rx="6" fill="#0a0b0d" />
      {/* Vertical stem of the K */}
      <rect x="7" y="6" width="3.5" height="20" fill="currentColor" />
      {/* Upper diagonal arm: stem top-right → upper-right corner */}
      <polygon points="10.5,16 10.5,6 25,6" fill="currentColor" />
      {/* Lower diagonal arm: stem mid-right → lower-right corner */}
      <polygon points="10.5,16 25,26 10.5,26" fill="currentColor" />
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
