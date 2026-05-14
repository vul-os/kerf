/**
 * TolerancePlusMatesIllustration — assembly dimension stack with per-part
 * tolerance callouts and an RSS total chip. Visualises what
 * `tolerance_auto_chain` produces: a BFS walk across the mate graph
 * between two feature refs that turns into a chain of dimensions plus a
 * worst-case / RSS / Monte-Carlo total.
 *
 * Composition:
 *   - 3 stacked parts in a horizontal assembly (block · block · block)
 *     joined by mate faces, with per-part nominal + tolerance callouts.
 *   - A dimension chain row underneath spanning the full stack.
 *   - A small mate-graph chip top-right showing the BFS path.
 *   - An RSS total chip bottom-right.
 *
 * viewBox 320×200. Palette locked.
 */
export default function TolerancePlusMatesIllustration({ className = '' }) {
  // Three parts along x: bases at 36, 110, 188, lengths 60, 64, 60.
  const parts = [
    { x: 36, w: 60, label: 'A', nom: '20.0', tol: '±0.05' },
    { x: 110, w: 64, label: 'B', nom: '25.0', tol: '±0.10' },
    { x: 188, w: 60, label: 'C', nom: '20.0', tol: '±0.05' },
  ]
  const stackY = 90 // top edge of parts
  const stackH = 34
  const dimY = stackY + stackH + 18 // dim line position

  return (
    <svg
      viewBox="0 0 320 200"
      preserveAspectRatio="xMidYMid meet"
      className={className}
      role="img"
      aria-label="An assembly of three parts with per-part tolerance callouts and an RSS total dimension chain"
    >
      <defs>
        <marker
          id="tol-arrow"
          viewBox="0 0 10 10"
          refX="5"
          refY="5"
          markerWidth="5"
          markerHeight="5"
          orient="auto"
        >
          <path d="M0,1 L9,5 L0,9 Z" fill="#5a6275" />
        </marker>
        <marker
          id="tol-arrow-end"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="5"
          markerHeight="5"
          orient="auto"
        >
          <path d="M0,1 L9,5 L0,9 Z" fill="#ffd633" />
        </marker>
      </defs>

      {/* outer panel */}
      <rect x="8" y="14" width="304" height="172" rx="8" fill="#0a0b0d" stroke="#1a1d24" />

      {/* header */}
      <text
        x="22"
        y="32"
        fontSize="9"
        fontFamily="ui-monospace, SFMono-Regular, monospace"
        fill="#6a7185"
        letterSpacing="1.4"
      >
        TOLERANCE · MATE CHAIN
      </text>
      <text
        x="298"
        y="32"
        textAnchor="end"
        fontSize="8"
        fontFamily="ui-monospace, monospace"
        fill="#3a4150"
        letterSpacing="1.2"
      >
        worst-case · RSS · MC
      </text>
      <line x1="22" y1="40" x2="298" y2="40" stroke="#1a1d24" strokeWidth="0.6" />

      {/* === mate-graph chip (top-left) === */}
      <g transform="translate(22, 50)">
        <rect width="116" height="32" rx="4" fill="#0d0f13" stroke="#1a1d24" />
        <text
          x="8"
          y="11"
          fontSize="7"
          fontFamily="ui-monospace, SFMono-Regular, monospace"
          fill="#5a6275"
          letterSpacing="1"
        >
          BFS mate graph
        </text>
        {/* tiny graph: 3 nodes + edges */}
        <g>
          <line x1="14" y1="23" x2="40" y2="23" stroke="#ffd633" strokeWidth="0.9" />
          <line x1="40" y1="23" x2="66" y2="23" stroke="#ffd633" strokeWidth="0.9" />
          <line x1="66" y1="23" x2="92" y2="23" stroke="#ffd633" strokeWidth="0.9" />
          {[14, 40, 66, 92].map((cx, i) => (
            <g key={cx}>
              <circle cx={cx} cy="23" r="3" fill="#0a0b0d" stroke="#ffd633" strokeWidth="1.1" />
              <text
                x={cx}
                y="25.5"
                textAnchor="middle"
                fontSize="5.2"
                fontFamily="ui-monospace, monospace"
                fill="#ffd633"
              >
                {['F1', 'A', 'B', 'C'][i] /* face refs and parts along the BFS walk */}
              </text>
            </g>
          ))}
          {/* terminal node F2 to the right */}
          <line x1="92" y1="23" x2="108" y2="23" stroke="#ffd633" strokeWidth="0.9" />
          <circle cx="108" cy="23" r="3" fill="#ffd633" />
        </g>
      </g>

      {/* === assembly: three parts in a row, drawn axonometric-front === */}
      <g>
        {/* tiny axonometric depth (one shared back face for unity) */}
        {parts.map((p) => (
          <g key={`back-${p.label}`}>
            {/* top face (offset back) */}
            <polygon
              points={`${p.x},${stackY} ${p.x + p.w},${stackY} ${p.x + p.w + 6},${stackY - 6} ${p.x + 6},${stackY - 6}`}
              fill="#1a1d24"
              stroke="#3a4150"
              strokeWidth="0.6"
            />
            {/* right face (only on last part to keep clean) */}
            {p.label === 'C' && (
              <polygon
                points={`${p.x + p.w},${stackY} ${p.x + p.w + 6},${stackY - 6} ${p.x + p.w + 6},${stackY + stackH - 6} ${p.x + p.w},${stackY + stackH}`}
                fill="#0f1115"
                stroke="#3a4150"
                strokeWidth="0.6"
              />
            )}
          </g>
        ))}

        {/* front face of each part */}
        {parts.map((p, i) => {
          const colors = ['#6bd4ff', '#ffd633', '#ff6bd4']
          const c = colors[i]
          return (
            <g key={p.label}>
              <rect
                x={p.x}
                y={stackY}
                width={p.w}
                height={stackH}
                fill="#0f1115"
                stroke={c}
                strokeWidth="1"
              />
              {/* part label chip */}
              <rect
                x={p.x + 4}
                y={stackY + 4}
                width="13"
                height="11"
                rx="2"
                fill={c}
                fillOpacity="0.18"
                stroke={c}
                strokeOpacity="0.55"
                strokeWidth="0.7"
              />
              <text
                x={p.x + 10.5}
                y={stackY + 12.5}
                textAnchor="middle"
                fontSize="7.5"
                fontFamily="ui-monospace, SFMono-Regular, monospace"
                fill={c}
                fontWeight="600"
              >
                {p.label}
              </text>
              {/* nominal */}
              <text
                x={p.x + p.w / 2}
                y={stackY + 22}
                textAnchor="middle"
                fontSize="8"
                fontFamily="ui-monospace, SFMono-Regular, monospace"
                fill="#cbd0dc"
              >
                {p.nom}
              </text>
              {/* tolerance */}
              <text
                x={p.x + p.w / 2}
                y={stackY + 31}
                textAnchor="middle"
                fontSize="6.5"
                fontFamily="ui-monospace, SFMono-Regular, monospace"
                fill="#8a93a6"
              >
                {p.tol}
              </text>
            </g>
          )
        })}

        {/* mate join markers between A-B and B-C */}
        {[parts[0].x + parts[0].w, parts[1].x + parts[1].w].map((mx, i) => (
          <g key={`mate-${i}`}>
            <line
              x1={mx}
              y1={stackY - 4}
              x2={mx}
              y2={stackY + stackH + 4}
              stroke="#ffd633"
              strokeWidth="0.5"
              strokeDasharray="2 2"
              opacity="0.7"
            />
            {/* tiny mate glyph */}
            <circle cx={mx} cy={stackY + stackH / 2} r="2.4" fill="#0a0b0d" stroke="#ffd633" strokeWidth="0.8" />
            <circle cx={mx} cy={stackY + stackH / 2} r="0.9" fill="#ffd633" />
          </g>
        ))}
      </g>

      {/* === dimension chain underneath the stack === */}
      <g>
        {/* extension lines from each segment boundary */}
        {[parts[0].x, parts[0].x + parts[0].w, parts[1].x + parts[1].w, parts[2].x + parts[2].w].map((x, i) => (
          <line
            key={`ext-${i}`}
            x1={x}
            y1={stackY + stackH + 2}
            x2={x}
            y2={dimY + 4}
            stroke="#3a4150"
            strokeWidth="0.5"
            strokeDasharray="2 2"
          />
        ))}
        {/* per-segment dim arrows */}
        {parts.map((p) => (
          <g key={`dim-${p.label}`}>
            <line
              x1={p.x + 1}
              y1={dimY}
              x2={p.x + p.w - 1}
              y2={dimY}
              stroke="#5a6275"
              strokeWidth="0.7"
              markerStart="url(#tol-arrow)"
              markerEnd="url(#tol-arrow)"
            />
            <text
              x={p.x + p.w / 2}
              y={dimY - 3}
              textAnchor="middle"
              fontSize="6.5"
              fontFamily="ui-monospace, SFMono-Regular, monospace"
              fill="#8a93a6"
            >
              {p.nom}
              <tspan fill="#5a6275"> {p.tol}</tspan>
            </text>
          </g>
        ))}

        {/* total dim spanning the whole chain, below */}
        <line
          x1={parts[0].x + 1}
          y1={dimY + 18}
          x2={parts[2].x + parts[2].w - 1}
          y2={dimY + 18}
          stroke="#ffd633"
          strokeWidth="0.9"
          markerStart="url(#tol-arrow)"
          markerEnd="url(#tol-arrow-end)"
        />
        <g transform={`translate(${(parts[0].x + parts[2].x + parts[2].w) / 2 - 32}, ${dimY + 22})`}>
          <rect width="64" height="14" rx="3" fill="#0a0b0d" stroke="#ffd633" strokeWidth="0.8" />
          <text
            x="32"
            y="10"
            textAnchor="middle"
            fontSize="7.5"
            fontFamily="ui-monospace, SFMono-Regular, monospace"
            fill="#ffd633"
            fontWeight="600"
          >
            65.0 ±0.12 RSS
          </text>
        </g>
      </g>

      {/* === auto_chain footer chip (right side, header level) === */}
      <g transform="translate(212, 50)">
        <rect width="86" height="32" rx="4" fill="#0d0f13" stroke="#1a1d24" />
        <text
          x="8"
          y="13"
          fontSize="7"
          fontFamily="ui-monospace, SFMono-Regular, monospace"
          fill="#5a6275"
          letterSpacing="1"
        >
          auto_chain
        </text>
        <text
          x="8"
          y="25"
          fontSize="7"
          fontFamily="ui-monospace, SFMono-Regular, monospace"
          fill="#7BB661"
        >
          ✓ 4 hops · 3 mates
        </text>
      </g>
    </svg>
  )
}
