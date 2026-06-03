// PartLibrary.jsx — Left sidebar showing part symbols grouped by category.
//
// Props:
//   activePart    — currently selected part type id (or null)
//   onSelectPart  — (partId) => void  called when user clicks a part
//   onDragStart   — (partId, e) => void  called when drag begins

import PARTS, { CATEGORIES } from './parts_library.js'

// ── Part symbol mini-renderer ─────────────────────────────────────────────────

function PartSymbolSVG({ part, size = 60 }) {
  const { symbol } = part
  const scale = size / 120  // symbols are defined in a ±60mil box

  function arcPath(a) {
    const { cx, cy, r, a1 = 0, a2 = 180 } = a
    const toRad = (d) => (d * Math.PI) / 180
    const x1 = cx + r * Math.cos(toRad(a1))
    const y1 = cy + r * Math.sin(toRad(a1))
    const x2 = cx + r * Math.cos(toRad(a2))
    const y2 = cy + r * Math.sin(toRad(a2))
    const largeArc = Math.abs(a2 - a1) > 180 ? 1 : 0
    return `M${x1},${y1} A${r},${r} 0 ${largeArc} 1 ${x2},${y2}`
  }

  return (
    <svg
      width={size}
      height={size}
      viewBox="-60 -60 120 120"
      className="flex-shrink-0"
      aria-hidden="true"
    >
      <g stroke="#7dd3fc" strokeWidth={2.5} fill="none" strokeLinecap="round" strokeLinejoin="round">
        {symbol.lines?.map(([x1, y1, x2, y2], i) => (
          <line key={`l${i}`} x1={x1} y1={y1} x2={x2} y2={y2} />
        ))}
        {symbol.arcs?.map((a, i) => (
          <path key={`a${i}`} d={arcPath(a)} />
        ))}
        {symbol.circles?.map((c, i) => (
          <circle
            key={`c${i}`}
            cx={c.cx}
            cy={c.cy}
            r={c.r}
            stroke="#7dd3fc"
            fill={c.fill !== undefined ? c.fill : 'none'}
          />
        ))}
      </g>
    </svg>
  )
}

// ── Sidebar component ─────────────────────────────────────────────────────────

export default function PartLibrary({ activePart, onSelectPart, onDragStart }) {
  const grouped = CATEGORIES.map((cat) => ({
    cat,
    parts: PARTS.filter((p) => p.category === cat),
  })).filter((g) => g.parts.length > 0)

  return (
    <div
      className="flex flex-col h-full bg-[#0b1120] border-r border-white/10 overflow-y-auto"
      style={{ width: 180, minWidth: 180 }}
      data-testid="part-library"
    >
      <div className="px-3 py-2 border-b border-white/10">
        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Parts</span>
      </div>

      {grouped.map(({ cat, parts }) => (
        <div key={cat}>
          <div className="px-3 pt-3 pb-1">
            <span className="text-[10px] font-bold text-indigo-400 uppercase tracking-widest">{cat}</span>
          </div>
          {parts.map((part) => {
            const active = activePart === part.id
            return (
              <div
                key={part.id}
                role="button"
                tabIndex={0}
                data-testid={`part-${part.id}`}
                draggable
                onDragStart={(e) => onDragStart?.(part.id, e)}
                onClick={() => onSelectPart?.(part.id)}
                onKeyDown={(e) => e.key === 'Enter' && onSelectPart?.(part.id)}
                className={[
                  'flex items-center gap-2 px-2 py-1.5 mx-1 my-0.5 rounded cursor-pointer transition-colors select-none',
                  active
                    ? 'bg-indigo-600/40 ring-1 ring-indigo-400'
                    : 'hover:bg-white/5',
                ].join(' ')}
              >
                <PartSymbolSVG part={part} size={36} />
                <span className="text-xs text-gray-300 leading-tight">{part.label}</span>
              </div>
            )
          })}
        </div>
      ))}

      <div className="mt-auto px-3 py-2 border-t border-white/10">
        <p className="text-[10px] text-gray-600 leading-relaxed">
          Click or drag a part to place it on the canvas
        </p>
      </div>
    </div>
  )
}
