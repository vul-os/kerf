// PartLibrary.tsx — Left sidebar showing part symbols grouped by category.

import PARTS, { CATEGORIES } from './parts_library.js'

// ── Symbol shape read from parts_library.js's PART entries ─────────────────
// parts_library.js is still untyped JS (migrated separately); these interfaces describe only
// the fields this file actually reads off a part, not the full part record.

// A plain number[] (not a fixed tuple) — parts_library.js's array literals infer as
// `number[][]`, which isn't assignable to a 4-tuple.
type SymbolLine = number[]

interface SymbolArc {
  cx: number
  cy: number
  r: number
  a1?: number
  a2?: number
}

interface SymbolCircle {
  cx: number
  cy: number
  r: number
  fill?: string
}

interface PartSymbol {
  lines?: SymbolLine[]
  arcs?: SymbolArc[]
  circles?: SymbolCircle[]
}

interface Part {
  id: string
  label: string
  category: string
  symbol: PartSymbol
}

// ── Part symbol mini-renderer ─────────────────────────────────────────────────

interface PartSymbolSVGProps {
  part: Part
  size?: number
}

function PartSymbolSVG({ part, size = 60 }: PartSymbolSVGProps) {
  const { symbol } = part

  function arcPath(a: SymbolArc): string {
    const { cx, cy, r, a1 = 0, a2 = 180 } = a
    const toRad = (d: number) => (d * Math.PI) / 180
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

export interface PartLibraryProps {
  activePart: string | null
  onSelectPart?: (partId: string) => void
  onDragStart?: (partId: string, e: React.DragEvent) => void
}

export default function PartLibrary({ activePart, onSelectPart, onDragStart }: PartLibraryProps) {
  const grouped = CATEGORIES.map((cat: string) => ({
    cat,
    parts: (PARTS as Part[]).filter((p) => p.category === cat),
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
