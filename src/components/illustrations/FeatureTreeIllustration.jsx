/**
 * FeatureTreeIllustration — vertical timeline of B-rep features
 * (Pad → Pocket → Fillet → Shell → Hole). Single full-width panel so the
 * whole composition fits cleanly inside aspect-[16/10] at ~280px wide.
 *
 * Bounds discipline: viewBox is 320x200. Outer panel rect is x=8..312, y=14..186.
 * Every row's right-side text terminates at x=292, leaving 20px of slack to
 * the panel border. Five rows at 30px pitch (y=46,76,106,136,166).
 */
export default function FeatureTreeIllustration({ className = '' }) {
  const rows = [
    { y: 46,  icon: 'pad',    label: 'Pad',    sub: '20 mm',         active: true },
    { y: 76,  icon: 'pocket', label: 'Pocket', sub: '8 mm · ø6'      },
    { y: 106, icon: 'fillet', label: 'Fillet', sub: '2 mm · 4 edges' },
    { y: 136, icon: 'shell',  label: 'Shell',  sub: '1.5 mm'         },
    { y: 166, icon: 'hole',   label: 'Hole',   sub: 'M5 thru', muted: true },
  ]

  return (
    <svg
      viewBox="0 0 320 200"
      preserveAspectRatio="xMidYMid meet"
      className={className}
      role="img"
      aria-label="Feature tree timeline showing Pad, Pocket, Fillet, Shell, and Hole operations"
    >
      {/* outer panel */}
      <rect x="8" y="14" width="304" height="172" rx="8" fill="#0a0b0d" stroke="#1a1d24" />

      {/* header strip */}
      <text
        x="22"
        y="30"
        fontSize="8"
        fontFamily="ui-monospace, monospace"
        fill="#5a6275"
        letterSpacing="1.4"
      >
        FEATURES
      </text>
      <text
        x="298"
        y="30"
        textAnchor="end"
        fontSize="8"
        fontFamily="ui-monospace, monospace"
        fill="#3a4150"
        letterSpacing="1.2"
      >
        OCCT
      </text>
      <line x1="22" y1="36" x2="298" y2="36" stroke="#1a1d24" strokeWidth="0.6" />

      {/* timeline rail — runs through the centres of all five row dots */}
      <line
        x1="34"
        y1="46"
        x2="34"
        y2="166"
        stroke="#232730"
        strokeWidth="1"
        strokeDasharray="2 3"
      />

      {/* active-row highlight bar (sits BEHIND glyph + text) */}
      <rect x="22" y="34" width="276" height="24" rx="4" fill="#ffd633" fillOpacity="0.06" />
      <rect x="22" y="34" width="2"   height="24" rx="1" fill="#ffd633" />

      {rows.map((r) => (
        <g key={r.label}>
          <circle
            cx="34"
            cy={r.y}
            r="4"
            fill={r.active ? '#ffd633' : r.muted ? '#1a1d24' : '#3a4150'}
            stroke={r.active ? '#ffe566' : '#3a4150'}
          />
          <FeatureGlyph kind={r.icon} x={48} y={r.y} muted={r.muted} active={r.active} />
          <text
            x="74"
            y={r.y - 1}
            fontSize="11"
            fontFamily="ui-monospace, monospace"
            fontWeight="500"
            fill={r.muted ? '#5a6275' : '#e2e6ee'}
          >
            {r.label}
          </text>
          <text
            x="74"
            y={r.y + 11}
            fontSize="9"
            fontFamily="ui-monospace, monospace"
            fill={r.muted ? '#3a4150' : '#5a6275'}
          >
            {r.sub}
          </text>
          <RowStatus y={r.y} active={r.active} muted={r.muted} />
        </g>
      ))}
    </svg>
  )
}

function RowStatus({ y, active, muted }) {
  if (muted) {
    return (
      <text
        x="292"
        y={y + 3}
        textAnchor="end"
        fontSize="8"
        fontFamily="ui-monospace, monospace"
        fill="#3a4150"
      >
        suppressed
      </text>
    )
  }
  if (active) {
    return (
      <g>
        <rect
          x="244"
          y={y - 6}
          width="48"
          height="13"
          rx="2.5"
          fill="#ffd633"
          fillOpacity="0.12"
          stroke="#ffd633"
          strokeOpacity="0.5"
          strokeWidth="0.6"
        />
        <text
          x="268"
          y={y + 3}
          textAnchor="middle"
          fontSize="8"
          fontFamily="ui-monospace, monospace"
          fill="#ffd633"
          letterSpacing="0.6"
        >
          editing
        </text>
      </g>
    )
  }
  return (
    <text
      x="292"
      y={y + 3}
      textAnchor="end"
      fontSize="8"
      fontFamily="ui-monospace, monospace"
      fill="#5a6275"
      letterSpacing="0.4"
    >
      ok
    </text>
  )
}

function FeatureGlyph({ kind, x, y, muted, active }) {
  const stroke = muted ? '#3a4150' : active ? '#ffd633' : '#8a93a6'
  const sw = 1.2
  if (kind === 'pad') {
    return (
      <g
        transform={`translate(${x - 7}, ${y - 7})`}
        stroke={stroke}
        strokeWidth={sw}
        fill="none"
        strokeLinejoin="round"
      >
        <polygon points="0,4 7,0 14,4 7,8" />
        <line x1="0"  y1="4" x2="0"  y2="10" />
        <line x1="7"  y1="8" x2="7"  y2="14" />
        <line x1="14" y1="4" x2="14" y2="10" />
        <polyline points="0,10 7,14 14,10" />
      </g>
    )
  }
  if (kind === 'pocket') {
    return (
      <g
        transform={`translate(${x - 7}, ${y - 7})`}
        stroke={stroke}
        strokeWidth={sw}
        fill="none"
      >
        <polygon points="0,4 7,0 14,4 7,8" />
        <polygon points="2.5,5 7,2.5 11.5,5 7,7" fill="#0a0b0d" />
        <line x1="0"  y1="4" x2="0"  y2="10" />
        <line x1="14" y1="4" x2="14" y2="10" />
        <line x1="7"  y1="8" x2="7"  y2="14" />
        <polyline points="0,10 7,14 14,10" />
      </g>
    )
  }
  if (kind === 'fillet') {
    return (
      <g
        transform={`translate(${x - 6}, ${y - 6})`}
        stroke={stroke}
        strokeWidth={sw}
        fill="none"
        strokeLinecap="round"
      >
        <path d="M 0 12 L 0 4 Q 0 0 4 0 L 12 0" />
      </g>
    )
  }
  if (kind === 'shell') {
    return (
      <g
        transform={`translate(${x - 7}, ${y - 7})`}
        stroke={stroke}
        strokeWidth={sw}
        fill="none"
      >
        <rect x="0"   y="2"   width="14" height="10" rx="0.5" />
        <rect x="2.5" y="4.5" width="9"  height="5.5" rx="0.5" strokeWidth="0.8" />
      </g>
    )
  }
  if (kind === 'hole') {
    return (
      <g
        transform={`translate(${x}, ${y})`}
        stroke={stroke}
        strokeWidth={sw}
        fill="none"
      >
        <circle cx="0" cy="0" r="6" />
        <circle cx="0" cy="0" r="2.4" fill={stroke} fillOpacity="0.4" stroke="none" />
        <line x1="-8"  y1="0"  x2="-6.5" y2="0"   />
        <line x1="6.5" y1="0"  x2="8"    y2="0"   />
        <line x1="0"   y1="-8" x2="0"    y2="-6.5"/>
        <line x1="0"   y1="6.5"x2="0"    y2="8"   />
      </g>
    )
  }
  return null
}
