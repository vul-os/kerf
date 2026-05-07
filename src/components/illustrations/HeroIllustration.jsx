/**
 * HeroIllustration — isometric three-pane editor (file tree, viewport, chat).
 *
 * Stroke-based, geometric, palette-locked to ink-* and kerf-300. Designed
 * to read at full hero size or scaled down to ~600px wide; arrows and
 * labels disappear cleanly via masks at small sizes.
 *
 * Renders a 3D bracket part (with a fillet and counterbore) in the centre
 * pane, a real chat exchange in the right pane, and a file tree on the
 * left to anchor the layout.
 */
export default function HeroIllustration({ className = '' }) {
  return (
    <svg
      viewBox="0 0 720 460"
      preserveAspectRatio="xMidYMid meet"
      className={className}
      role="img"
      aria-label="Kerf editor: file tree, 3D viewport, and chat panel side by side"
    >
      <defs>
        <linearGradient id="hero-bg" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#0f1115" />
          <stop offset="100%" stopColor="#0a0b0d" />
        </linearGradient>
        <linearGradient id="hero-top" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#2d323d" />
          <stop offset="100%" stopColor="#1a1d24" />
        </linearGradient>
        <linearGradient id="hero-front" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#232730" />
          <stop offset="100%" stopColor="#14171c" />
        </linearGradient>
        <linearGradient id="hero-side" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0%" stopColor="#1a1d24" />
          <stop offset="100%" stopColor="#0f1115" />
        </linearGradient>
        <pattern id="hero-grid" width="20" height="20" patternUnits="userSpaceOnUse">
          <path d="M 20 0 L 0 0 0 20" fill="none" stroke="#1a1d24" strokeWidth="0.5" />
        </pattern>
        <radialGradient id="hero-glow" cx="50%" cy="50%" r="60%">
          <stop offset="0%" stopColor="#ffd633" stopOpacity="0.15" />
          <stop offset="100%" stopColor="#ffd633" stopOpacity="0" />
        </radialGradient>
      </defs>

      {/* outer frame */}
      <rect x="0" y="0" width="720" height="460" rx="14" fill="url(#hero-bg)" stroke="#1a1d24" />

      {/* tab strip */}
      <rect x="0" y="0" width="720" height="28" fill="#0f1115" />
      <line x1="0" y1="28" x2="720" y2="28" stroke="#1a1d24" />
      <circle cx="14" cy="14" r="3" fill="#232730" />
      <circle cx="26" cy="14" r="3" fill="#232730" />
      <circle cx="38" cy="14" r="3" fill="#232730" />
      <text x="360" y="18" textAnchor="middle" fontSize="10" fontFamily="ui-monospace, monospace" fill="#5a6275">
        kerf · bracket-v3
      </text>

      {/* file tree (left pane) */}
      <rect x="0" y="28" width="148" height="432" fill="#0f1115" />
      <line x1="148" y1="28" x2="148" y2="460" stroke="#1a1d24" />
      <text x="14" y="50" fontSize="9" fontFamily="ui-monospace, monospace" fill="#5a6275" letterSpacing="1.2">
        FILES
      </text>
      {[
        { y: 70, name: 'bracket.jscad', active: true },
        { y: 88, name: 'mount.feature' },
        { y: 106, name: 'profile.sketch' },
        { y: 124, name: 'frame.assembly' },
        { y: 142, name: 'sheet.drawing' },
        { y: 160, name: 'board.circuit' },
      ].map((f) => (
        <g key={f.name}>
          {f.active && <rect x="6" y={f.y - 12} width="136" height="20" rx="4" fill="#ffd633" fillOpacity="0.08" stroke="#ffd633" strokeOpacity="0.25" />}
          <rect x="14" y={f.y - 4} width="6" height="6" fill="none" stroke={f.active ? '#ffd633' : '#5a6275'} />
          <text x="26" y={f.y + 1} fontSize="11" fontFamily="ui-monospace, monospace" fill={f.active ? '#ffe566' : '#b8bfcc'}>
            {f.name}
          </text>
        </g>
      ))}

      <text x="14" y="200" fontSize="9" fontFamily="ui-monospace, monospace" fill="#5a6275" letterSpacing="1.2">
        THREADS
      </text>
      {[
        { y: 220, t: 'thicken the wall', star: true },
        { y: 238, t: 'add 2mm fillet' },
        { y: 256, t: 'shell + 1.5mm' },
      ].map((row) => (
        <g key={row.t}>
          {row.star ? (
            <path d={`M 16 ${row.y - 3} l 2.5 -1.4 l 2.5 1.4 l -1 -2.8 l 2 -2 l -2.7 -0.2 l -0.8 -2.6 l -0.8 2.6 l -2.7 0.2 l 2 2 z`} fill="#ffd633" />
          ) : (
            <rect x="14" y={row.y - 4} width="6" height="6" rx="1" fill="none" stroke="#5a6275" />
          )}
          <text x="26" y={row.y + 1} fontSize="10.5" fontFamily="ui-monospace, monospace" fill="#8a93a6">
            {row.t}
          </text>
        </g>
      ))}

      {/* center 3D viewport */}
      <rect x="148" y="28" width="380" height="432" fill="#0a0b0d" />
      <rect x="148" y="28" width="380" height="432" fill="url(#hero-grid)" />
      <rect x="148" y="28" width="380" height="432" fill="url(#hero-glow)" />
      <line x1="528" y1="28" x2="528" y2="460" stroke="#1a1d24" />

      {/* viewport tag */}
      <g transform="translate(168, 50)">
        <rect width="86" height="18" rx="4" fill="#ffd633" fillOpacity="0.12" stroke="#ffd633" strokeOpacity="0.35" />
        <circle cx="9" cy="9" r="2.2" fill="#ffd633" />
        <text x="18" y="12.5" fontSize="9.5" fontFamily="ui-monospace, monospace" fill="#ffe566">
          bracket#wall
        </text>
      </g>

      {/* gizmo top-right */}
      <g transform="translate(488, 48)">
        <line x1="0" y1="14" x2="20" y2="14" stroke="#E03C31" strokeWidth="1.5" />
        <line x1="14" y1="0" x2="14" y2="28" stroke="#7BB661" strokeWidth="1.5" />
        <line x1="14" y1="14" x2="2" y2="26" stroke="#6bd4ff" strokeWidth="1.5" />
        <text x="22" y="17" fontSize="8" fontFamily="ui-monospace, monospace" fill="#5a6275">X</text>
        <text x="11" y="-2" fontSize="8" fontFamily="ui-monospace, monospace" fill="#5a6275">Z</text>
      </g>

      {/* iso bracket — base + raised wall with rounded corner (fillet) and a
          counterbore hole. All faces are pure polygons; no rasterised art. */}
      <g transform="translate(338, 268)">
        {/* base: 200×40×16 */}
        <polygon points="-160,-20 80,-50 160,20 -80,50" fill="url(#hero-top)" stroke="#3a4150" strokeWidth="1" />
        <polygon points="-160,-20 -80,50 -80,82 -160,12" fill="#14171c" stroke="#3a4150" />
        <polygon points="-80,50 160,20 160,52 -80,82" fill="url(#hero-side)" stroke="#3a4150" />

        {/* upright wall, with the fillet edge highlighted */}
        <polygon points="-46,-32 84,-48 84,-114 -46,-98" fill="url(#hero-front)" stroke="#3a4150" />
        <polygon points="84,-48 124,-22 124,-88 84,-114" fill="url(#hero-side)" stroke="#3a4150" />
        <polygon points="-46,-32 -6,-6 124,-22 84,-48" fill="url(#hero-top)" stroke="#3a4150" />

        {/* fillet highlight on top-front edge */}
        <path
          d="M -46,-98 Q -46,-104 -40,-105 L 78,-119 Q 84,-120 84,-114"
          fill="none"
          stroke="#ffd633"
          strokeWidth="1.6"
        />

        {/* counterbore on base */}
        <ellipse cx="-30" cy="14" rx="14" ry="7" fill="#0a0b0d" stroke="#3a4150" />
        <ellipse cx="-30" cy="14" rx="8" ry="4" fill="#14171c" stroke="#5a6275" />

        {/* fastener hole (right) */}
        <ellipse cx="80" cy="0" rx="11" ry="5.5" fill="#0a0b0d" stroke="#3a4150" />
        <ellipse cx="80" cy="0" rx="6" ry="3" fill="#14171c" stroke="#5a6275" />
      </g>

      {/* dimension callout above part */}
      <g>
        <line x1="200" y1="170" x2="478" y2="170" stroke="#5a6275" strokeWidth="1" strokeDasharray="3 3" />
        <line x1="200" y1="166" x2="200" y2="174" stroke="#5a6275" />
        <line x1="478" y1="166" x2="478" y2="174" stroke="#5a6275" />
        <rect x="318" y="158" width="42" height="16" rx="3" fill="#0a0b0d" stroke="#1a1d24" />
        <text x="339" y="170" textAnchor="middle" fontSize="10" fontFamily="ui-monospace, monospace" fill="#ffd633">
          120mm
        </text>
      </g>

      {/* viewport HUD */}
      <text x="156" y="450" fontSize="9" fontFamily="ui-monospace, monospace" fill="#3a4150">
        ISO · 1:2 · 3,142 tris
      </text>
      <text x="520" y="450" textAnchor="end" fontSize="9" fontFamily="ui-monospace, monospace" fill="#3a4150">
        X 12.4  Y 0.0  Z 8.2
      </text>

      {/* right chat pane */}
      <rect x="528" y="28" width="192" height="432" fill="#0f1115" />
      <text x="544" y="50" fontSize="9" fontFamily="ui-monospace, monospace" fill="#5a6275" letterSpacing="1.2">
        CHAT
      </text>

      {/* user message 1 */}
      <g transform="translate(540, 64)">
        <rect width="168" height="52" rx="6" fill="#1a1d24" />
        <g transform="translate(8, 8)">
          <rect width="74" height="14" rx="3" fill="#ffd633" fillOpacity="0.12" stroke="#ffd633" strokeOpacity="0.3" />
          <text x="6" y="10" fontSize="9" fontFamily="ui-monospace, monospace" fill="#ffe566">
            bracket#wall
          </text>
        </g>
        <text x="8" y="40" fontSize="11" fontFamily="ui-sans-serif, system-ui" fill="#e2e6ee">
          make this 6mm thick
        </text>
      </g>

      {/* assistant — tool call + reply */}
      <g transform="translate(540, 128)">
        <rect width="168" height="44" rx="6" fill="#0a0b0d" stroke="#1a1d24" />
        <g transform="translate(8, 8)">
          <circle cx="3" cy="4" r="2" fill="#ffd633" />
          <text x="10" y="7" fontSize="9" fontFamily="ui-monospace, monospace" fill="#ffe566">
            edit_file
          </text>
          <text x="10" y="22" fontSize="9.5" fontFamily="ui-monospace, monospace" fill="#8a93a6">
            size[1]: 4 → 6
          </text>
        </g>
      </g>

      <g transform="translate(540, 184)">
        <rect width="168" height="48" rx="6" fill="#0a0b0d" stroke="#1a1d24" />
        <text x="8" y="20" fontSize="11" fontFamily="ui-sans-serif, system-ui" fill="#b8bfcc">
          Updated wall thickness
        </text>
        <text x="8" y="36" fontSize="11" fontFamily="ui-sans-serif, system-ui" fill="#b8bfcc">
          to 6mm. Re-rendered.
        </text>
      </g>

      {/* user message 2 */}
      <g transform="translate(540, 244)">
        <rect width="168" height="36" rx="6" fill="#1a1d24" />
        <text x="8" y="22" fontSize="11" fontFamily="ui-sans-serif, system-ui" fill="#e2e6ee">
          add a 2mm fillet on top
        </text>
      </g>

      {/* thinking */}
      <g transform="translate(548, 296)">
        <circle cx="2" cy="4" r="2.5" fill="#ffd633" />
        <text x="10" y="8" fontSize="10" fontFamily="ui-monospace, monospace" fill="#5a6275">
          thinking…
        </text>
      </g>

      {/* input box */}
      <rect x="540" y="420" width="168" height="24" rx="6" fill="#0a0b0d" stroke="#1a1d24" />
      <text x="550" y="436" fontSize="10" fontFamily="ui-sans-serif, system-ui" fill="#3a4150">
        Ask kerf…
      </text>
    </svg>
  )
}
