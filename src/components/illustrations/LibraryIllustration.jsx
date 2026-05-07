/**
 * LibraryIllustration — parts catalog grid (six tiles) with a verified-
 * publisher star badge in the top-right. Shows a mix of passives (R/C/L),
 * a 555 timer IC and a screw to communicate breadth.
 */
export default function LibraryIllustration({ className = '' }) {
  return (
    <svg
      viewBox="0 0 320 200"
      preserveAspectRatio="xMidYMid meet"
      className={className}
      role="img"
      aria-label="Library catalog grid showing parts with a verified-publisher star badge"
    >
      <rect x="8" y="14" width="304" height="172" rx="8" fill="#0a0b0d" stroke="#1a1d24" />
      <text x="22" y="32" fontSize="9" fontFamily="ui-monospace, monospace" fill="#5a6275" letterSpacing="1.2">
        LIBRARY
      </text>

      {/* verified publisher star badge */}
      <g transform="translate(244, 22)">
        <rect width="60" height="16" rx="3" fill="#ffd633" fillOpacity="0.12" stroke="#ffd633" strokeOpacity="0.4" />
        <path
          d="M 9 4 L 10.5 7.5 L 14 8 L 11.5 10.4 L 12.1 14 L 9 12.2 L 5.9 14 L 6.5 10.4 L 4 8 L 7.5 7.5 Z"
          fill="#ffd633"
          fillOpacity="0.85"
          stroke="#ffd633"
          strokeWidth="0.5"
        />
        <text x="20" y="11" fontSize="8" fontFamily="ui-monospace, monospace" fill="#ffd633">
          verified
        </text>
      </g>

      {/* parts grid */}
      {[
        { x: 22, y: 50, kind: 'resistor', label: 'R 10kΩ', verified: true },
        { x: 116, y: 50, kind: 'capacitor', label: 'C 10µF' },
        { x: 210, y: 50, kind: 'inductor', label: 'L 100µH' },
        { x: 22, y: 118, kind: 'timer555', label: 'NE555' },
        { x: 116, y: 118, kind: 'screw', label: 'M3×8' },
        { x: 210, y: 118, kind: 'led', label: 'LED' },
      ].map((p) => (
        <PartTile key={p.label} {...p} />
      ))}
    </svg>
  )
}

function PartTile({ x, y, kind, label, verified }) {
  return (
    <g transform={`translate(${x}, ${y})`}>
      <rect width="84" height="56" rx="5" fill="#0f1115" stroke="#232730" />
      {verified && (
        <g transform="translate(72, 8)">
          <path
            d="M 4 0 L 4.9 2.5 L 7.5 2.7 L 5.5 4.4 L 6.1 7 L 4 5.7 L 1.9 7 L 2.5 4.4 L 0.5 2.7 L 3.1 2.5 Z"
            fill="#ffd633"
            stroke="#ffd633"
            strokeWidth="0.4"
          />
        </g>
      )}
      <PartGlyph kind={kind} />
      <text
        x="42"
        y="50"
        textAnchor="middle"
        fontSize="9"
        fontFamily="ui-monospace, monospace"
        fill="#b8bfcc"
      >
        {label}
      </text>
    </g>
  )
}

function PartGlyph({ kind }) {
  const c = '#ffd633'
  if (kind === 'resistor') {
    return (
      <g transform="translate(42, 24)" stroke={c} strokeWidth="1.2" fill="none">
        <line x1="-18" y1="0" x2="-12" y2="0" />
        <path d="M -12 0 L -9 -6 L -3 6 L 3 -6 L 9 6 L 12 0" />
        <line x1="12" y1="0" x2="18" y2="0" />
      </g>
    )
  }
  if (kind === 'capacitor') {
    return (
      <g transform="translate(42, 24)">
        <line x1="-16" y1="0" x2="-3" y2="0" stroke={c} strokeWidth="1" />
        <line x1="3" y1="0" x2="16" y2="0" stroke={c} strokeWidth="1" />
        <line x1="-3" y1="-8" x2="-3" y2="8" stroke={c} strokeWidth="1.6" />
        <line x1="3" y1="-8" x2="3" y2="8" stroke={c} strokeWidth="1.6" />
      </g>
    )
  }
  if (kind === 'inductor') {
    return (
      <g transform="translate(42, 24)" stroke={c} strokeWidth="1.2" fill="none">
        <line x1="-18" y1="0" x2="-12" y2="0" />
        <path d="M -12 0 A 3 3 0 0 1 -6 0 A 3 3 0 0 1 0 0 A 3 3 0 0 1 6 0 A 3 3 0 0 1 12 0" />
        <line x1="12" y1="0" x2="18" y2="0" />
      </g>
    )
  }
  if (kind === 'timer555') {
    return (
      <g transform="translate(42, 24)">
        <rect x="-16" y="-9" width="32" height="18" fill="none" stroke={c} strokeWidth="1.2" />
        {/* DIP pins */}
        {[-6, -1, 4, 9].map((dx, i) => (
          <g key={i}>
            <line x1={-16} y1={-6 + i * 4} x2={-19} y2={-6 + i * 4} stroke={c} strokeWidth="1" />
            <line x1={16} y1={-6 + i * 4} x2={19} y2={-6 + i * 4} stroke={c} strokeWidth="1" />
          </g>
        ))}
        <text x="0" y="3" textAnchor="middle" fontSize="7" fontFamily="ui-monospace, monospace" fill={c}>
          555
        </text>
      </g>
    )
  }
  if (kind === 'screw') {
    return (
      <g transform="translate(42, 24)">
        <rect x="-16" y="-6" width="6" height="12" stroke={c} strokeWidth="1" fill="none" />
        <line x1="-10" y1="0" x2="14" y2="0" stroke={c} strokeWidth="1.4" />
        <line x1="-7" y1="-4" x2="11" y2="-4" stroke={c} strokeWidth="1" />
        <line x1="-7" y1="4" x2="11" y2="4" stroke={c} strokeWidth="1" />
      </g>
    )
  }
  if (kind === 'led') {
    return (
      <g transform="translate(42, 24)">
        <circle cx="0" cy="-1" r="6" fill="none" stroke={c} strokeWidth="1.2" />
        <line x1="-4" y1="6" x2="-4" y2="11" stroke={c} strokeWidth="1.2" />
        <line x1="4" y1="6" x2="4" y2="11" stroke={c} strokeWidth="1.2" />
        <path d="M 8 -7 L 12 -11 M 11 -8 L 12 -11 L 9 -10" stroke={c} strokeWidth="0.8" fill="none" />
        <path d="M 4 -5 L 8 -9 M 7 -6 L 8 -9 L 5 -8" stroke={c} strokeWidth="0.8" fill="none" />
      </g>
    )
  }
  return null
}
