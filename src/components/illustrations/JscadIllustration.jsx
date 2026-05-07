/**
 * JscadIllustration — code editor pane on the left, isometric bracket on
 * the right, dotted arrow connecting them. Communicates "code becomes
 * geometry" without copy.
 */
export default function JscadIllustration({ className = '' }) {
  return (
    <svg
      viewBox="0 0 320 200"
      preserveAspectRatio="xMidYMid meet"
      className={className}
      role="img"
      aria-label="JSCAD code on the left, 3D bracket on the right"
    >
      <defs>
        <linearGradient id="js-top" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#2d323d" />
          <stop offset="100%" stopColor="#1a1d24" />
        </linearGradient>
        <linearGradient id="js-side" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0%" stopColor="#1a1d24" />
          <stop offset="100%" stopColor="#0f1115" />
        </linearGradient>
        <marker id="js-arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M0,0 L10,5 L0,10 z" fill="#ffd633" />
        </marker>
      </defs>

      {/* code panel */}
      <rect x="8" y="14" width="148" height="172" rx="8" fill="#0a0b0d" stroke="#1a1d24" />
      <rect x="8" y="14" width="148" height="20" rx="8" fill="#0f1115" />
      <circle cx="20" cy="24" r="2.5" fill="#232730" />
      <circle cx="30" cy="24" r="2.5" fill="#232730" />
      <circle cx="40" cy="24" r="2.5" fill="#232730" />
      <text x="78" y="28" textAnchor="middle" fontSize="8" fontFamily="ui-monospace, monospace" fill="#5a6275">
        bracket.jscad
      </text>

      {/* code lines */}
      <g fontSize="8" fontFamily="ui-monospace, monospace">
        <text x="18" y="50" fill="#3a4150">1</text>
        <text x="30" y="50" fill="#ff6bd4">import</text>
        <text x="58" y="50" fill="#b8bfcc">{'{ cuboid }'}</text>
        <text x="18" y="64" fill="#3a4150">2</text>
        <text x="30" y="64" fill="#ff6bd4">export default</text>
        <text x="86" y="64" fill="#6bd4ff">main</text>
        <text x="18" y="78" fill="#3a4150">3</text>
        <text x="30" y="78" fill="#b8bfcc">  size = [</text>
        <text x="64" y="78" fill="#ffd633">40</text>
        <text x="74" y="78" fill="#b8bfcc">,</text>
        <text x="80" y="78" fill="#ffd633">6</text>
        <text x="86" y="78" fill="#b8bfcc">,</text>
        <text x="92" y="78" fill="#ffd633">20</text>
        <text x="100" y="78" fill="#b8bfcc">]</text>
        <text x="18" y="92" fill="#3a4150">4</text>
        <text x="30" y="92" fill="#ff6bd4">return</text>
        <text x="60" y="92" fill="#6bd4ff">cuboid</text>
        <text x="84" y="92" fill="#b8bfcc">({'{ size }'})</text>
        <text x="18" y="108" fill="#3a4150">5</text>
        <text x="18" y="124" fill="#3a4150">6</text>
        <text x="30" y="124" fill="#5a6275">// re-renders</text>
        <text x="18" y="138" fill="#3a4150">7</text>
        <text x="30" y="138" fill="#5a6275">// on save</text>
      </g>

      {/* arrow */}
      <path d="M 162 100 L 188 100" stroke="#ffd633" strokeWidth="1.5" markerEnd="url(#js-arr)" />

      {/* iso part */}
      <g transform="translate(255, 105)">
        <polygon points="-50,-12 26,-26 56,4 -20,18" fill="url(#js-top)" stroke="#3a4150" />
        <polygon points="-50,-12 -20,18 -20,32 -50,2" fill="#14171c" stroke="#3a4150" />
        <polygon points="-20,18 56,4 56,18 -20,32" fill="url(#js-side)" stroke="#3a4150" />
        {/* upright */}
        <polygon points="-12,-22 30,-30 30,-58 -12,-50" fill="#1a1d24" stroke="#ffd633" strokeWidth="1.2" />
        <polygon points="30,-30 44,-22 44,-50 30,-58" fill="#0f1115" stroke="#ffd633" strokeWidth="1.2" />
        <polygon points="-12,-22 2,-14 44,-22 30,-30" fill="url(#js-top)" stroke="#ffd633" strokeWidth="1.2" />
      </g>
    </svg>
  )
}
