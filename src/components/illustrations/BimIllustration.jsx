/**
 * BimIllustration — axonometric building (walls, slabs, openings) on
 * the right with a `.bim` source snippet on the left. Conveys
 * "text-DSL compiles to IFC".
 *
 * Axonometric projection (cabinet-style):
 *   world X (8m building length) → screen (90, 12)   → unit X = (11.25, 1.5)
 *   world Y (6m depth)           → screen (30, -14)  → unit Y = (5, -2.33)
 *   world Z (3m floor height)    → screen (0, -38)   → unit Z = (0, -12.67)
 *
 * Openings (windows and door) are drawn as PARALLELOGRAMS on the wall
 * plane so they follow the projection. Earlier revision used axis-aligned
 * <rect>s which broke perspective on the slanted wall faces.
 *
 * viewBox 320×200.
 */
export default function BimIllustration({ className = '' }) {
  // Project a point in wall A's local plane (s along wall, h above floor)
  // to screen coords. Wall A runs along world X at world Y=0; its base
  // start (world origin) sits at screen `(baseX, baseY)`.
  const wallA = (baseX, baseY) => (s, h) => [
    baseX + s * 11.25,
    baseY + s * 1.5 - h * 12.67,
  ]
  // Same for wall B which runs along world Y at world X=8m.
  const wallB = (baseX, baseY) => (s, h) => [
    baseX + s * 5,
    baseY - s * 2.33 - h * 12.67,
  ]

  // Wall A base — front-left base in world (0,0,0) → ground slab corner -60,30
  // (taken from the polygon points below).
  const aPoint = wallA(-60, 30)
  // Wall B base — front-right corner at world (8,0,0) → 30,42.
  const bPoint = wallB(30, 42)

  // L1 front window: 1.6m along, 1m above floor, 1.4m × 1.4m
  const winA_BL = aPoint(1.6, 1.0)
  const winA_BR = aPoint(3.0, 1.0)
  const winA_TR = aPoint(3.0, 2.4)
  const winA_TL = aPoint(1.6, 2.4)
  const winAGlazingMid = aPoint(2.3, 1.0)
  const winAGlazingMidTop = aPoint(2.3, 2.4)

  // L1 door on wall A, near right side: 5m along, 0m above floor, 0.9m × 2.1m
  const doorA_BL = aPoint(5.0, 0)
  const doorA_BR = aPoint(5.9, 0)
  const doorA_TR = aPoint(5.9, 2.1)
  const doorA_TL = aPoint(5.0, 2.1)
  const doorHandle = aPoint(5.75, 1.0)

  // L2 window on the L2 front wall (same projection, base shifts by +1*unitZ*3m → up 3m)
  // L2 floor base sits at front-left top of L1 = (-60, -8). So new wallA base.
  const aPointL2 = wallA(-60, -8)
  const winL2_BL = aPointL2(2.5, 0.8)
  const winL2_BR = aPointL2(4.5, 0.8)
  const winL2_TR = aPointL2(4.5, 2.0)
  const winL2_TL = aPointL2(2.5, 2.0)

  // Side wall B small window
  const winB_BL = bPoint(2.0, 1.0)
  const winB_BR = bPoint(3.4, 1.0)
  const winB_TR = bPoint(3.4, 2.3)
  const winB_TL = bPoint(2.0, 2.3)

  const ptStr = (p) => `${p[0].toFixed(2)},${p[1].toFixed(2)}`

  return (
    <svg
      viewBox="0 0 320 200"
      preserveAspectRatio="xMidYMid meet"
      className={className}
      role="img"
      aria-label=".bim source on the left compiling to an axonometric two-storey building on the right"
    >
      <rect x="8" y="14" width="304" height="172" rx="8" fill="#0a0b0d" stroke="#1a1d24" />
      <text
        x="22"
        y="32"
        fontSize="9"
        fontFamily="ui-monospace, SFMono-Regular, monospace"
        fill="#6a7185"
        letterSpacing="1.4"
      >
        BIM · .bim → IFC4
      </text>
      <line x1="22" y1="40" x2="298" y2="40" stroke="#1a1d24" strokeWidth="0.6" />

      {/* source panel */}
      <rect x="18" y="48" width="126" height="128" rx="4" fill="#0f1115" stroke="#1a1d24" />
      <g fontSize="7" fontFamily="ui-monospace, SFMono-Regular, monospace" fill="#b8bfcc">
        <text x="26" y="62" fill="#5a6275">level L1 elev=0</text>
        <text x="26" y="74" fill="#5a6275">level L2 elev=3.0</text>
        <text x="26" y="90" fill="#ffd633">wall</text>
        <text x="46" y="90" fill="#b8bfcc"> A 0,0 8,0</text>
        <text x="26" y="100" fill="#5a6275">  height 3.0</text>
        <text x="26" y="116" fill="#ffd633">slab</text>
        <text x="46" y="116" fill="#b8bfcc"> 0,0 8,6 L1</text>
        <text x="26" y="132" fill="#ffd633">opening</text>
        <text x="62" y="132" fill="#b8bfcc"> A 1.6,1 1.4,1.4</text>
        <text x="26" y="144" fill="#ffd633">door</text>
        <text x="46" y="144" fill="#b8bfcc"> A 5.0 0.9x2.1</text>
        <text x="26" y="160" fill="#5a6275">space LIVING</text>
        <text x="26" y="172" fill="#7BB661"># 14 entities</text>
      </g>

      {/* === building axonometric (right) === */}
      <g transform="translate(220, 110)">
        {/* ground slab */}
        <polygon points="-60,30 30,42 60,28 -30,16" fill="#1a1d24" stroke="#5a6275" strokeWidth="0.6" />

        {/* L1 — front wall A (longest) */}
        <polygon
          points="-60,30 30,42 30,4 -60,-8"
          fill="#232730"
          stroke="#6bd4ff"
          strokeWidth="0.8"
        />
        {/* L1 — side wall B */}
        <polygon
          points="30,42 60,28 60,-10 30,4"
          fill="#1a1d24"
          stroke="#6bd4ff"
          strokeWidth="0.8"
        />

        {/* === L1 front-wall window — parallelogram in wall plane === */}
        <polygon
          points={`${ptStr(winA_BL)} ${ptStr(winA_BR)} ${ptStr(winA_TR)} ${ptStr(winA_TL)}`}
          fill="#0a0b0d"
          stroke="#6bd4ff"
          strokeWidth="0.7"
        />
        {/* mullion (vertical in wall plane) */}
        <line
          x1={winAGlazingMid[0]}
          y1={winAGlazingMid[1]}
          x2={winAGlazingMidTop[0]}
          y2={winAGlazingMidTop[1]}
          stroke="#6bd4ff"
          strokeWidth="0.45"
        />
        {/* transom (horizontal-in-wall = follows unitX slope) */}
        <line
          x1={aPoint(1.6, 1.7)[0]}
          y1={aPoint(1.6, 1.7)[1]}
          x2={aPoint(3.0, 1.7)[0]}
          y2={aPoint(3.0, 1.7)[1]}
          stroke="#6bd4ff"
          strokeWidth="0.45"
        />

        {/* === L1 front-wall door — parallelogram with handle === */}
        <polygon
          points={`${ptStr(doorA_BL)} ${ptStr(doorA_BR)} ${ptStr(doorA_TR)} ${ptStr(doorA_TL)}`}
          fill="#0d0f13"
          stroke="#ffd633"
          strokeWidth="0.8"
        />
        {/* door panel inner reveal */}
        <polygon
          points={`${ptStr(aPoint(5.1, 0.15))} ${ptStr(aPoint(5.8, 0.15))} ${ptStr(aPoint(5.8, 1.95))} ${ptStr(aPoint(5.1, 1.95))}`}
          fill="none"
          stroke="#ffd633"
          strokeOpacity="0.5"
          strokeWidth="0.4"
        />
        {/* handle */}
        <circle cx={doorHandle[0]} cy={doorHandle[1]} r="0.9" fill="#ffd633" />

        {/* mid slab (L2 floor) */}
        <polygon
          points="-60,-8 30,4 60,-10 -30,-22"
          fill="#2d323d"
          stroke="#7BB661"
          strokeWidth="0.6"
        />

        {/* L2 — front wall */}
        <polygon
          points="-60,-8 30,4 30,-32 -60,-44"
          fill="#232730"
          stroke="#7BB661"
          strokeWidth="0.8"
        />
        {/* L2 — side wall */}
        <polygon
          points="30,4 60,-10 60,-46 30,-32"
          fill="#1a1d24"
          stroke="#7BB661"
          strokeWidth="0.8"
        />

        {/* === L2 window — parallelogram in L2 front-wall plane === */}
        <polygon
          points={`${ptStr(winL2_BL)} ${ptStr(winL2_BR)} ${ptStr(winL2_TR)} ${ptStr(winL2_TL)}`}
          fill="#0a0b0d"
          stroke="#7BB661"
          strokeWidth="0.7"
        />
        {/* L2 mullion */}
        <line
          x1={aPointL2(3.5, 0.8)[0]}
          y1={aPointL2(3.5, 0.8)[1]}
          x2={aPointL2(3.5, 2.0)[0]}
          y2={aPointL2(3.5, 2.0)[1]}
          stroke="#7BB661"
          strokeWidth="0.45"
        />

        {/* === L1 side-wall window — parallelogram in wall B plane === */}
        <polygon
          points={`${ptStr(winB_BL)} ${ptStr(winB_BR)} ${ptStr(winB_TR)} ${ptStr(winB_TL)}`}
          fill="#0a0b0d"
          stroke="#6bd4ff"
          strokeWidth="0.6"
        />

        {/* roof slab */}
        <polygon
          points="-60,-44 30,-32 60,-46 -30,-58"
          fill="#3a4150"
          stroke="#7BB661"
          strokeWidth="0.6"
        />

        {/* level markers on side */}
        <line x1="60" y1="28" x2="68" y2="32" stroke="#5a6275" strokeDasharray="2 1" strokeWidth="0.5" />
        <line x1="60" y1="-10" x2="68" y2="-6" stroke="#5a6275" strokeDasharray="2 1" strokeWidth="0.5" />
        <line x1="60" y1="-46" x2="68" y2="-42" stroke="#5a6275" strokeDasharray="2 1" strokeWidth="0.5" />
        <text x="70" y="34" fontSize="6" fontFamily="ui-monospace, monospace" fill="#5a6275">L1</text>
        <text x="70" y="-4" fontSize="6" fontFamily="ui-monospace, monospace" fill="#5a6275">L2</text>
        <text x="70" y="-40" fontSize="6" fontFamily="ui-monospace, monospace" fill="#5a6275">ROOF</text>
      </g>

      {/* compile arrow between source and building */}
      <g stroke="#ffd633" strokeWidth="0.9" fill="none" strokeLinecap="round">
        <line x1="146" y1="108" x2="162" y2="108" />
        <polygon points="162,108 157,105 157,111" fill="#ffd633" />
      </g>
      <text
        x="154"
        y="102"
        textAnchor="middle"
        fontSize="6.5"
        fontFamily="ui-monospace, monospace"
        fill="#ffd633"
      >
        compile
      </text>

      <text
        x="296"
        y="32"
        textAnchor="end"
        fontSize="7"
        fontFamily="ui-monospace, monospace"
        fill="#5a6275"
      >
        IfcOpenShell
      </text>
    </svg>
  )
}
