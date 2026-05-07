/**
 * DrawingIllustration — TechDraw-style multi-sheet 2D drawing with three
 * orthographic views, dimensions, and a title block. Stylised as a
 * white-on-paper render to evoke real engineering drawings.
 */
export default function DrawingIllustration({ className = '' }) {
  return (
    <svg
      viewBox="0 0 320 200"
      preserveAspectRatio="xMidYMid meet"
      className={className}
      role="img"
      aria-label="Engineering drawing sheet with three views, dimensions, and a title block"
    >
      {/* sheet stack */}
      <rect x="14" y="22" width="280" height="160" rx="3" fill="#0f1115" stroke="#1a1d24" />
      <rect x="10" y="18" width="280" height="160" rx="3" fill="#14171c" stroke="#232730" />
      <rect x="6" y="14" width="280" height="160" rx="3" fill="#1a1d24" stroke="#3a4150" />

      {/* sheet border */}
      <rect x="14" y="22" width="264" height="144" fill="none" stroke="#5a6275" strokeWidth="0.6" />

      {/* top view */}
      <g stroke="#e2e6ee" strokeWidth="1" fill="none">
        <rect x="32" y="40" width="68" height="40" />
        <line x1="46" y1="40" x2="46" y2="80" />
        <line x1="86" y1="40" x2="86" y2="80" />
        <circle cx="46" cy="60" r="3" />
        <circle cx="86" cy="60" r="3" />
      </g>

      {/* front view */}
      <g stroke="#e2e6ee" strokeWidth="1" fill="none">
        <rect x="32" y="98" width="68" height="46" />
        <line x1="46" y1="98" x2="46" y2="144" stroke="#5a6275" strokeDasharray="2 3" />
        <line x1="86" y1="98" x2="86" y2="144" stroke="#5a6275" strokeDasharray="2 3" />
      </g>

      {/* right side view (iso preview) */}
      <g stroke="#ffd633" strokeWidth="1" fill="none">
        <polygon points="146,68 196,52 226,72 176,88" />
        <polygon points="146,68 176,88 176,112 146,92" />
        <polygon points="176,88 226,72 226,96 176,112" />
      </g>

      {/* dim lines on top view */}
      <g stroke="#8a93a6" strokeWidth="0.6">
        <line x1="32" y1="32" x2="100" y2="32" />
        <line x1="32" y1="28" x2="32" y2="40" />
        <line x1="100" y1="28" x2="100" y2="40" />
        <text x="66" y="30" textAnchor="middle" fontSize="7" fontFamily="ui-monospace, monospace" fill="#e2e6ee">
          40
        </text>
      </g>
      <g stroke="#8a93a6" strokeWidth="0.6">
        <line x1="24" y1="40" x2="24" y2="80" />
        <line x1="20" y1="40" x2="32" y2="40" />
        <line x1="20" y1="80" x2="32" y2="80" />
        <text x="22" y="62" textAnchor="middle" fontSize="7" fontFamily="ui-monospace, monospace" fill="#e2e6ee">
          25
        </text>
      </g>

      {/* GD&T frame */}
      <g transform="translate(116, 130)">
        <rect width="46" height="12" fill="none" stroke="#e2e6ee" strokeWidth="0.6" />
        <line x1="14" y1="0" x2="14" y2="12" stroke="#e2e6ee" strokeWidth="0.6" />
        <line x1="32" y1="0" x2="32" y2="12" stroke="#e2e6ee" strokeWidth="0.6" />
        <text x="7" y="9" textAnchor="middle" fontSize="8" fontFamily="ui-monospace, monospace" fill="#e2e6ee">
          ⊥
        </text>
        <text x="23" y="9" textAnchor="middle" fontSize="6.5" fontFamily="ui-monospace, monospace" fill="#e2e6ee">
          0.05
        </text>
        <text x="39" y="9" textAnchor="middle" fontSize="7" fontFamily="ui-monospace, monospace" fill="#e2e6ee">
          A
        </text>
      </g>

      {/* surface finish (∇) */}
      <g transform="translate(96, 84)">
        <path d="M 0 4 L 4 -4 L 8 4" fill="none" stroke="#e2e6ee" strokeWidth="0.6" />
        <text x="4" y="-8" textAnchor="middle" fontSize="6.5" fontFamily="ui-monospace, monospace" fill="#e2e6ee">
          Ra 1.6
        </text>
      </g>

      {/* title block */}
      <g>
        <rect x="166" y="120" width="112" height="46" fill="none" stroke="#5a6275" strokeWidth="0.6" />
        <line x1="166" y1="134" x2="278" y2="134" stroke="#5a6275" strokeWidth="0.4" />
        <line x1="166" y1="148" x2="278" y2="148" stroke="#5a6275" strokeWidth="0.4" />
        <line x1="222" y1="120" x2="222" y2="166" stroke="#5a6275" strokeWidth="0.4" />
        <text x="170" y="130" fontSize="6.5" fontFamily="ui-monospace, monospace" fill="#5a6275">PART NO.</text>
        <text x="170" y="144" fontSize="7.5" fontFamily="ui-monospace, monospace" fill="#e2e6ee">BR-001</text>
        <text x="170" y="158" fontSize="6" fontFamily="ui-monospace, monospace" fill="#5a6275">1:2</text>
        <text x="226" y="130" fontSize="6.5" fontFamily="ui-monospace, monospace" fill="#5a6275">SHEET</text>
        <text x="226" y="144" fontSize="7.5" fontFamily="ui-monospace, monospace" fill="#ffd633">1 of 3</text>
        <text x="226" y="158" fontSize="6" fontFamily="ui-monospace, monospace" fill="#5a6275">A4</text>
      </g>
    </svg>
  )
}
