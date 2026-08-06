/**
 * WorkshopIllustration — three published project cards arranged in a small
 * grid. Each card shows a stylised geometric thumbnail and footer with a
 * heart (likes) and fork icon, communicating the "publish + fork" loop.
 */
export default function WorkshopIllustration({ className = '' }) {
  return (
    <svg
      viewBox="0 0 320 200"
      preserveAspectRatio="xMidYMid meet"
      className={className}
      role="img"
      aria-label="Three Workshop project cards with heart and fork icons"
    >
      <rect x="8" y="14" width="304" height="172" rx="8" fill="#0a0b0d" stroke="#1a1d24" />
      <text x="22" y="32" fontSize="8" fontFamily="ui-monospace, monospace" fill="#5a6275" letterSpacing="1.4">
        WORKSHOP
      </text>

      <ProjectCard x={20} y={48} thumb="gear" title="planet-gear" likes={142} forks={31} highlighted />
      <ProjectCard x={118} y={48} thumb="lattice" title="lattice" likes={87} forks={12} />
      <ProjectCard x={216} y={48} thumb="enclosure" title="esp32-case" likes={216} forks={48} />
    </svg>
  )
}

function ProjectCard({ x, y, thumb, title, likes, forks, highlighted }) {
  const stroke = highlighted ? '#ffd633' : '#232730'
  const strokeOp = highlighted ? 0.55 : 1
  return (
    <g transform={`translate(${x}, ${y})`}>
      <rect
        width="84"
        height="124"
        rx="6"
        fill="#0f1115"
        stroke={stroke}
        strokeOpacity={strokeOp}
      />
      {/* thumb area */}
      <rect x="6" y="6" width="72" height="62" rx="3" fill="#0a0b0d" stroke="#1a1d24" />
      <Thumb kind={thumb} />

      {/* title */}
      <text
        x="8"
        y="84"
        fontSize="8.5"
        fontFamily="ui-monospace, monospace"
        fill="#e6e9ef"
      >
        {title}
      </text>
      <text
        x="8"
        y="96"
        fontSize="7"
        fontFamily="ui-monospace, monospace"
        fill="#5a6275"
      >
        @maker
      </text>

      {/* footer divider */}
      <line x1="6" y1="104" x2="78" y2="104" stroke="#232730" strokeWidth="0.6" />

      {/* heart + fork stats */}
      <g transform="translate(8, 113)">
        <path
          d="M 4 4 C 4 2 2 1 1 2 C 0 3 0 4 4 7 C 8 4 8 3 7 2 C 6 1 4 2 4 4 Z"
          fill={highlighted ? '#ff6b9b' : 'none'}
          stroke="#ff6b9b"
          strokeWidth="0.8"
        />
        <text x="11" y="6" fontSize="7" fontFamily="ui-monospace, monospace" fill="#b8bfcc">
          {likes}
        </text>
      </g>
      <g transform="translate(44, 113)">
        {/* fork glyph: two branches off a stem */}
        <circle cx="2" cy="2" r="1.3" fill="none" stroke="#6bd4ff" strokeWidth="0.8" />
        <circle cx="8" cy="2" r="1.3" fill="none" stroke="#6bd4ff" strokeWidth="0.8" />
        <circle cx="5" cy="7" r="1.3" fill="none" stroke="#6bd4ff" strokeWidth="0.8" />
        <line x1="2" y1="3.3" x2="2" y2="5" stroke="#6bd4ff" strokeWidth="0.8" />
        <line x1="8" y1="3.3" x2="8" y2="5" stroke="#6bd4ff" strokeWidth="0.8" />
        <path d="M 2 5 Q 5 5.5 5 6" fill="none" stroke="#6bd4ff" strokeWidth="0.8" />
        <path d="M 8 5 Q 5 5.5 5 6" fill="none" stroke="#6bd4ff" strokeWidth="0.8" />
        <text x="14" y="6" fontSize="7" fontFamily="ui-monospace, monospace" fill="#b8bfcc">
          {forks}
        </text>
      </g>
    </g>
  )
}

function Thumb({ kind }) {
  const c = '#ffd633'
  if (kind === 'gear') {
    return (
      <g transform="translate(42, 36)">
        <circle cx="0" cy="0" r="14" fill="none" stroke={c} strokeWidth="1" />
        <circle cx="0" cy="0" r="5" fill="none" stroke={c} strokeWidth="1" />
        {Array.from({ length: 10 }).map((_, i) => {
          const a = (i / 10) * Math.PI * 2
          const x1 = Math.cos(a) * 14
          const y1 = Math.sin(a) * 14
          const x2 = Math.cos(a) * 18
          const y2 = Math.sin(a) * 18
          return (
            <line
              key={i}
              x1={x1}
              y1={y1}
              x2={x2}
              y2={y2}
              stroke={c}
              strokeWidth="1.6"
            />
          )
        })}
      </g>
    )
  }
  if (kind === 'lattice') {
    return (
      <g transform="translate(42, 36)" stroke={c} strokeWidth="0.9" fill="none">
        {/* triangulated lattice bracket */}
        <polygon points="-22,12 22,12 18,-10 -18,-10" />
        <line x1="-22" y1="12" x2="18" y2="-10" />
        <line x1="22" y1="12" x2="-18" y2="-10" />
        <line x1="0" y1="12" x2="0" y2="-10" />
        <line x1="-11" y1="1" x2="11" y2="1" />
      </g>
    )
  }
  if (kind === 'enclosure') {
    return (
      <g transform="translate(42, 36)" stroke={c} strokeWidth="0.9" fill="none">
        {/* isometric box */}
        <polygon points="-18,-4 4,-12 22,-4 0,4" />
        <polygon points="-18,-4 0,4 0,14 -18,6" />
        <polygon points="0,4 22,-4 22,6 0,14" />
        {/* port cutout */}
        <rect x="6" y="0" width="10" height="3" />
      </g>
    )
  }
  return null
}
