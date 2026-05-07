/**
 * SketcherIllustration — 2D constraint sketcher showing a fully constrained
 * profile in green, with dimension callouts (10mm, 30mm) and constraint
 * glyphs (parallel hash, perpendicular tick).
 */
export default function SketcherIllustration({ className = '' }) {
  return (
    <svg
      viewBox="0 0 320 200"
      preserveAspectRatio="xMidYMid meet"
      className={className}
      role="img"
      aria-label="Constrained 2D sketch with dimensions and parallel constraint marks"
    >
      <defs>
        <pattern id="sk-grid" width="16" height="16" patternUnits="userSpaceOnUse">
          <path d="M 16 0 L 0 0 0 16" fill="none" stroke="#14171c" strokeWidth="0.6" />
        </pattern>
      </defs>
      <rect x="8" y="14" width="304" height="172" rx="8" fill="#0a0b0d" stroke="#1a1d24" />
      <rect x="8" y="14" width="304" height="172" fill="url(#sk-grid)" />

      {/* Origin axes */}
      <line x1="56" y1="100" x2="280" y2="100" stroke="#3a4150" strokeWidth="0.8" strokeDasharray="2 3" />
      <line x1="56" y1="40" x2="56" y2="180" stroke="#3a4150" strokeWidth="0.8" strokeDasharray="2 3" />
      <circle cx="56" cy="100" r="3" fill="#0a0b0d" stroke="#5a6275" />

      {/* fully-constrained profile (green = solved) */}
      <g stroke="#7BB661" strokeWidth="1.6" fill="none">
        <line x1="80" y1="60" x2="240" y2="60" />
        <line x1="240" y1="60" x2="240" y2="140" />
        <line x1="240" y1="140" x2="80" y2="140" />
        <line x1="80" y1="140" x2="80" y2="60" />
        {/* inner cutout */}
        <circle cx="160" cy="100" r="22" />
      </g>

      {/* vertices */}
      {[
        [80, 60],
        [240, 60],
        [240, 140],
        [80, 140],
      ].map(([x, y]) => (
        <circle key={`${x}-${y}`} cx={x} cy={y} r="2.6" fill="#0a0b0d" stroke="#7BB661" strokeWidth="1.2" />
      ))}

      {/* parallel hash marks on top + bottom */}
      <g stroke="#7BB661" strokeWidth="1">
        <line x1="156" y1="56" x2="160" y2="64" />
        <line x1="160" y1="56" x2="164" y2="64" />
        <line x1="156" y1="136" x2="160" y2="144" />
        <line x1="160" y1="136" x2="164" y2="144" />
      </g>

      {/* perpendicular ticks at each corner */}
      <g stroke="#6bd4ff" strokeWidth="0.9" fill="none">
        <rect x="80" y="60" width="6" height="6" />
        <rect x="234" y="60" width="6" height="6" />
        <rect x="234" y="134" width="6" height="6" />
        <rect x="80" y="134" width="6" height="6" />
      </g>

      {/* horizontal dim 30mm */}
      <g>
        <line x1="80" y1="36" x2="240" y2="36" stroke="#5a6275" />
        <line x1="80" y1="32" x2="80" y2="60" stroke="#5a6275" strokeDasharray="2 2" />
        <line x1="240" y1="32" x2="240" y2="60" stroke="#5a6275" strokeDasharray="2 2" />
        <polygon points="80,36 86,33 86,39" fill="#5a6275" />
        <polygon points="240,36 234,33 234,39" fill="#5a6275" />
        <rect x="148" y="28" width="24" height="14" rx="3" fill="#0a0b0d" stroke="#1a1d24" />
        <text x="160" y="38" textAnchor="middle" fontSize="9" fontFamily="ui-monospace, monospace" fill="#ffd633">
          30
        </text>
      </g>

      {/* vertical dim 10 (radius really, but treat as side dim for clarity) */}
      <g>
        <line x1="36" y1="60" x2="36" y2="140" stroke="#5a6275" />
        <line x1="36" y1="60" x2="80" y2="60" stroke="#5a6275" strokeDasharray="2 2" />
        <line x1="36" y1="140" x2="80" y2="140" stroke="#5a6275" strokeDasharray="2 2" />
        <polygon points="36,60 33,66 39,66" fill="#5a6275" />
        <polygon points="36,140 33,134 39,134" fill="#5a6275" />
        <rect x="22" y="92" width="24" height="14" rx="3" fill="#0a0b0d" stroke="#1a1d24" />
        <text x="34" y="102" textAnchor="middle" fontSize="9" fontFamily="ui-monospace, monospace" fill="#ffd633">
          15
        </text>
      </g>

      {/* DOF tag */}
      <g transform="translate(244, 14)">
        <rect width="60" height="16" rx="3" fill="#7BB661" fillOpacity="0.12" stroke="#7BB661" strokeOpacity="0.4" />
        <circle cx="9" cy="8" r="2.5" fill="#7BB661" />
        <text x="18" y="11" fontSize="9" fontFamily="ui-monospace, monospace" fill="#7BB661">
          solved
        </text>
      </g>
    </svg>
  )
}
