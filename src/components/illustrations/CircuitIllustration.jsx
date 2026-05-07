/**
 * CircuitIllustration — schematic + PCB + isometric 3D board, side by side.
 *
 * Canonical demo circuit: +5V rail → 1 kΩ resistor → green LED → GND, with a
 * 100 nF bypass cap directly across the rails. Every wire in the schematic
 * starts at one component pin and ends at another (or at a rail) with right-
 * angle joints; junctions are drawn as filled dots. The PCB pane shows the
 * same three parts as SMD footprints with orthogonal copper traces that
 * visibly enter and exit each pad. The 3D pane is an isometric board with
 * extruded component bodies sitting fully INSIDE the board outline.
 *
 * viewBox 320×200. Three panels: 10..104, 110..204, 210..312.
 */
export default function CircuitIllustration({ className = '' }) {
  return (
    <svg
      viewBox="0 0 320 200"
      preserveAspectRatio="xMidYMid meet"
      className={className}
      role="img"
      aria-label="Schematic, PCB layout, and isometric 3D board for a 5 volt LED indicator"
    >
      <Schematic />
      <Pcb />
      <Board3D />
    </svg>
  )
}

/* -------------------------------------------------------------------------- */
/* Schematic                                                                   */
/* -------------------------------------------------------------------------- */
/* Panel: x=10..104, y=14..186.                                                */
/* +5V rail: y=50.   GND rail: y=158.                                          */
/* C1 bypass cap at x=30. R1 resistor at x=66. LED D1 below R1 at x=66.        */
/* Net "node B" at (66, 110): bottom of R1 / anode of LED.                     */

function Schematic() {
  const wire = '#6bd4ff'
  const part = '#ffd633'

  return (
    <g>
      {/* panel */}
      <rect x="10" y="14" width="94" height="172" rx="6" fill="#0a0b0d" stroke="#1a1d24" />
      <text
        x="57"
        y="28"
        textAnchor="middle"
        fontSize="8"
        fontFamily="ui-monospace, monospace"
        fill="#5a6275"
        letterSpacing="1.2"
      >
        SCHEMATIC
      </text>

      {/* rails */}
      <g stroke={wire} strokeWidth="1" fill="none" strokeLinecap="round">
        {/* +5V rail */}
        <line x1="20" y1="50" x2="94" y2="50" />
        {/* GND rail */}
        <line x1="20" y1="158" x2="94" y2="158" />
      </g>
      <text
        x="20"
        y="44"
        fontSize="6.5"
        fontFamily="ui-monospace, monospace"
        fill={wire}
      >
        +5V
      </text>

      {/* GND symbol — three diminishing horizontal bars centred on x=82 */}
      <g stroke={wire} strokeWidth="1" fill="none" strokeLinecap="round">
        <line x1="82" y1="158" x2="82" y2="166" />
        <line x1="76" y1="166" x2="88" y2="166" />
        <line x1="78" y1="170" x2="86" y2="170" />
        <line x1="80" y1="174" x2="84" y2="174" />
      </g>

      {/* C1 bypass cap on left branch (x=30) — connects rail-to-rail */}
      <g stroke={part} strokeWidth="1" fill="none" strokeLinecap="round">
        {/* top wire from +5V rail to top plate */}
        <line x1="30" y1="50"  x2="30" y2="92" />
        {/* top plate */}
        <line x1="22" y1="92"  x2="38" y2="92" />
        {/* bottom plate */}
        <line x1="22" y1="98"  x2="38" y2="98" />
        {/* bottom wire to GND rail */}
        <line x1="30" y1="98"  x2="30" y2="158" />
      </g>
      <text
        x="42"
        y="98"
        fontSize="6.5"
        fontFamily="ui-monospace, monospace"
        fill={part}
      >
        C1
      </text>
      <text
        x="42"
        y="106"
        fontSize="5.5"
        fontFamily="ui-monospace, monospace"
        fill="#5a6275"
      >
        100nF
      </text>

      {/* R1 resistor on right branch (x=66) — top half from rail to node B */}
      <g stroke={part} strokeWidth="1" fill="none" strokeLinejoin="round">
        {/* lead from +5V rail down to start of zigzag */}
        <line x1="66" y1="50" x2="66" y2="62" />
        {/* zigzag body, 6 segments */}
        <polyline points="66,62 60,66 72,72 60,78 72,84 60,90 66,94" />
        {/* lead from end of zigzag down to node B at y=110 */}
        <line x1="66" y1="94" x2="66" y2="110" />
      </g>
      <text
        x="78"
        y="80"
        fontSize="6.5"
        fontFamily="ui-monospace, monospace"
        fill={part}
      >
        R1
      </text>
      <text
        x="78"
        y="88"
        fontSize="5.5"
        fontFamily="ui-monospace, monospace"
        fill="#5a6275"
      >
        1kΩ
      </text>

      {/* LED D1 below R1 (x=66) — node B (y=110) to GND rail */}
      <g stroke={part} strokeWidth="1" fill={part} fillOpacity="0.18" strokeLinejoin="round">
        {/* anode lead from node B down to triangle apex */}
        <line x1="66" y1="110" x2="66" y2="122" stroke={part} fill="none" />
        {/* triangle (anode -> cathode), apex up at (66,122), base at y=138 */}
        <polygon points="66,122 60,138 72,138" />
        {/* cathode bar */}
        <line x1="60" y1="138" x2="72" y2="138" stroke={part} fill="none" strokeWidth="1.4" />
        {/* cathode lead down to GND rail */}
        <line x1="66" y1="138" x2="66" y2="158" stroke={part} fill="none" />
        {/* emission arrows (two short slashes top-right of LED) */}
        <line x1="74" y1="124" x2="80" y2="118" stroke={part} fill="none" strokeWidth="0.8" />
        <line x1="78" y1="118" x2="80" y2="118" stroke={part} fill="none" strokeWidth="0.8" />
        <line x1="80" y1="118" x2="80" y2="120" stroke={part} fill="none" strokeWidth="0.8" />
        <line x1="76" y1="130" x2="82" y2="124" stroke={part} fill="none" strokeWidth="0.8" />
        <line x1="80" y1="124" x2="82" y2="124" stroke={part} fill="none" strokeWidth="0.8" />
        <line x1="82" y1="124" x2="82" y2="126" stroke={part} fill="none" strokeWidth="0.8" />
      </g>
      <text
        x="46"
        y="134"
        fontSize="6.5"
        fontFamily="ui-monospace, monospace"
        fill={part}
        textAnchor="end"
      >
        D1
      </text>

      {/* junction dots — every place a wire meets the rail or another wire */}
      <g fill={wire}>
        <circle cx="30" cy="50"  r="1.6" />
        <circle cx="66" cy="50"  r="1.6" />
        <circle cx="30" cy="158" r="1.6" />
        <circle cx="66" cy="158" r="1.6" />
        <circle cx="82" cy="158" r="1.6" />
      </g>
    </g>
  )
}

/* -------------------------------------------------------------------------- */
/* PCB top-view                                                                */
/* -------------------------------------------------------------------------- */
/* Panel: x=110..204, y=14..186.                                               */
/* Board outline: x=118..198, y=42..178.                                       */
/* Three SMD parts: C1 (top), R1 (mid), D1 (bottom). All footprints are        */
/* 0805-style two-pad rectangles. Traces connect pad-to-pad orthogonally.      */

function Pcb() {
  const copper = '#ffd633'
  const silk = '#e2e6ee'
  const board = '#0a3a1a'
  const boardEdge = '#7BB661'

  // pad dims: 6 wide × 4 tall, centred on the listed coordinates
  const pad = (cx, cy) => (
    <rect x={cx - 3} y={cy - 2} width="6" height="4" rx="0.5" fill={copper} />
  )
  // body: 14 × 6 centred
  const body = (cx, cy) => (
    <rect
      x={cx - 7}
      y={cy - 3}
      width="14"
      height="6"
      rx="0.6"
      fill="#1a1d24"
      stroke="#3a4150"
      strokeWidth="0.5"
    />
  )

  // Component centre coordinates (panel-local).
  // Footprints are horizontal: left pad + body + right pad.
  // C1 centre (138, 60).  pads at (130, 60) and (146, 60).
  // R1 centre (158, 96).  pads at (150, 96) and (166, 96).
  // D1 centre (168, 138). pads at (160, 138) and (176, 138).
  // VCC pad (top-left)  at (124, 60).
  // GND pad (bottom-right) at (190, 138).
  // Two GND vias on the bottom edge at (134, 168) and (180, 168).

  return (
    <g>
      {/* panel */}
      <rect x="110" y="14" width="94" height="172" rx="6" fill="#0a0b0d" stroke="#1a1d24" />
      <text
        x="157"
        y="28"
        textAnchor="middle"
        fontSize="8"
        fontFamily="ui-monospace, monospace"
        fill="#5a6275"
        letterSpacing="1.2"
      >
        PCB
      </text>

      {/* board substrate */}
      <rect x="118" y="42" width="80" height="136" rx="4" fill={board} stroke={boardEdge} strokeWidth="0.6" />
      {/* board mounting holes (corners) */}
      <g fill="#0a0b0d" stroke={boardEdge} strokeWidth="0.5">
        <circle cx="124" cy="48"  r="1.5" />
        <circle cx="192" cy="48"  r="1.5" />
        <circle cx="124" cy="172" r="1.5" />
        <circle cx="192" cy="172" r="1.5" />
      </g>

      {/* copper traces — drawn BEFORE pads so pads sit on top, no gaps */}
      <g stroke={copper} strokeWidth="1.4" fill="none" strokeLinecap="square" strokeLinejoin="miter">
        {/* VCC trace: VCC pad (124,60) → C1 left pad (130,60) → C1 right pad (146,60) → R1 left pad (150,96) */}
        <line x1="124" y1="60" x2="130" y2="60" />
        {/* C1 right pad (146,60) — kink down to R1 left pad (150,96), 45° kink at (146,92) */}
        <polyline points="146,60 146,92 150,96" />
        {/* R1 right pad (166,96) → D1 left pad (160,138): right-angle path */}
        <polyline points="166,96 172,96 172,138 176,138" />
        {/* D1 right pad (176,138) → GND pad (190,138) — straight east */}
        <line x1="176" y1="138" x2="190" y2="138" />
        {/* GND pour rail along bottom: GND pad → both vias */}
        <polyline points="190,138 190,160 180,160 180,168" />
        <polyline points="190,160 134,160 134,168" />
      </g>

      {/* SMD footprints (pads + body) */}
      {/* C1 */}
      {pad(130, 60)} {pad(146, 60)} {body(138, 60)}
      {/* R1 */}
      {pad(150, 96)} {pad(166, 96)} {body(158, 96)}
      {/* D1 — LED footprint, slightly different body colour with a polarity stripe */}
      {pad(160, 138)} {pad(176, 138)}
      <rect x="161" y="135" width="14" height="6" rx="0.6" fill="#1a1d24" stroke="#3a4150" strokeWidth="0.5" />
      {/* polarity stripe on cathode side (right pad) */}
      <line x1="173" y1="135" x2="173" y2="141" stroke={copper} strokeWidth="0.8" />

      {/* labelled VCC pad (top-left) */}
      <rect x="121" y="58" width="6" height="4" rx="0.5" fill={copper} />
      {/* labelled GND pad (right side of D1) */}
      <rect x="187" y="136" width="6" height="4" rx="0.5" fill={copper} />

      {/* GND vias */}
      <g>
        <circle cx="134" cy="168" r="1.8" fill={copper} />
        <circle cx="134" cy="168" r="0.7" fill="#0a0b0d" />
        <circle cx="180" cy="168" r="1.8" fill={copper} />
        <circle cx="180" cy="168" r="0.7" fill="#0a0b0d" />
      </g>

      {/* silkscreen labels (above each footprint) */}
      <g
        fill={silk}
        fillOpacity="0.85"
        fontSize="5.5"
        fontFamily="ui-monospace, monospace"
        textAnchor="middle"
        letterSpacing="0.4"
      >
        <text x="138" y="54">C1</text>
        <text x="158" y="90">R1</text>
        <text x="168" y="132">D1</text>
      </g>

      {/* edge labels */}
      <text
        x="120"
        y="56"
        fontSize="4.5"
        fontFamily="ui-monospace, monospace"
        fill="#7BB661"
      >
        +5
      </text>
      <text
        x="196"
        y="135"
        fontSize="4.5"
        fontFamily="ui-monospace, monospace"
        fill="#7BB661"
        textAnchor="end"
      >
        GND
      </text>
    </g>
  )
}

/* -------------------------------------------------------------------------- */
/* 3D board                                                                    */
/* -------------------------------------------------------------------------- */
/* Panel: x=210..312, y=14..186.                                               */
/* Isometric board centred at (261, 110). Board top is a parallelogram with    */
/* corners                                                                     */
/*   TL (-44,-22)  TR (24,-36)  BR (44,-14)  BL (-24,0)                        */
/* Component baseline lies on this top quad. Each component is a small        */
/* extruded box whose top quad shares the same iso projection. Components are */
/* placed strictly INSIDE the board outline.                                   */

function Board3D() {
  const board = '#0a3a1a'
  const boardEdge = '#7BB661'
  const part = '#ffd633'

  // iso unit vectors (matching the board's parallelogram skew):
  //   right vector =  (1,    -0.21)  — moving +x in board space
  //   up    vector =  (-0.4, +0.21)  — moving +y in board space (toward viewer)
  // Using width 68, depth 22 board so each unit ≈ scaling.
  // Component placement uses small explicit polygons rather than computed transforms
  // so we keep tight visual control.

  return (
    <g>
      {/* panel */}
      <rect x="210" y="14" width="102" height="172" rx="6" fill="#0a0b0d" stroke="#1a1d24" />
      <text
        x="261"
        y="28"
        textAnchor="middle"
        fontSize="8"
        fontFamily="ui-monospace, monospace"
        fill="#5a6275"
        letterSpacing="1.2"
      >
        3D BOARD
      </text>

      {/* board with thickness — drawn at translate(261,110) */}
      <g transform="translate(261, 110)">
        {/* sides (drawn first, sit below top) */}
        {/* front-left side */}
        <polygon
          points="-44,-22 -24,0 -24,8 -44,-14"
          fill="#072010"
          stroke={boardEdge}
          strokeWidth="0.6"
        />
        {/* front-right side */}
        <polygon
          points="-24,0 44,-14 44,-6 -24,8"
          fill="#0a3014"
          stroke={boardEdge}
          strokeWidth="0.6"
        />

        {/* board top */}
        <polygon
          points="-44,-22 24,-36 44,-14 -24,0"
          fill={board}
          stroke={boardEdge}
          strokeWidth="0.7"
        />

        {/* mounting holes — small circles with darker centres to imply countersinks */}
        {[
          [-37, -19],
          [16, -29.5],
          [-19, -3],
          [37, -16.5],
        ].map(([cx, cy], i) => (
          <g key={i}>
            <circle cx={cx} cy={cy} r="1.4" fill="#0a0b0d" stroke={boardEdge} strokeWidth="0.4" />
          </g>
        ))}

        {/*                                                                  */}
        {/* Component placement — bottom faces lie strictly INSIDE the       */}
        {/* board's top parallelogram (TL=-44,-22 to BR=44,-14), so each     */}
        {/* component visibly "sits on" the board surface.                   */}
        {/*                                                                  */}
        {/* C1 — extruded box near the back-left corner                      */}
        <Component3D
          // topQuad: top face of the component (visible upper face).
          // Bottom face = topQuad shifted DOWN (+y) by `height` and must
          // remain inside the board parallelogram.
          // C1 bottom face: (-30,-20),(-20,-22),(-15,-16),(-25,-14) ✓
          topQuad="-30,-24 -20,-26 -15,-20 -25,-18"
          height={4}
          color={part}
          label="C1"
          labelPos={[-22, -30]}
        />

        {/* R1 — central                                                     */}
        {/* R1 bottom face: (-8,-21),(2,-23),(7,-17),(-3,-15) ✓             */}
        <Component3D
          topQuad="-8,-25 2,-27 7,-21 -3,-19"
          height={4}
          color={part}
          label="R1"
          labelPos={[0, -31]}
        />

        {/* D1 (LED) — front-right, with a small dome on top                 */}
        {/* D1 bottom face: (9,-28),(19,-30),(24,-24),(14,-22) ✓            */}
        <Component3D
          topQuad="9,-32 19,-34 24,-28 14,-26"
          height={4}
          color={part}
          label="D1"
          labelPos={[18, -38]}
          dome
        />
      </g>
    </g>
  )
}

function Component3D({ topQuad, height, color, label, labelPos, dome }) {
  // topQuad expects 4 "x,y" points: TL, TR, BR, BL (in same iso convention as board)
  const pts = topQuad.split(' ').map((p) => p.split(',').map(Number))
  const [TL, TR, BR, BL] = pts
  // bottom quad simply shifts every point down by `height` along screen-y
  const offset = (p) => `${p[0]},${p[1] + height}`
  const BLb = [BL[0], BL[1] + height]
  const BRb = [BR[0], BR[1] + height]

  return (
    <g>
      {/* front-left side */}
      <polygon
        points={`${TL.join(',')} ${BL.join(',')} ${offset(BL)} ${offset(TL)}`}
        fill="#1a1d24"
        stroke={color}
        strokeWidth="0.5"
        strokeOpacity="0.8"
      />
      {/* front-right side */}
      <polygon
        points={`${BL.join(',')} ${BR.join(',')} ${BRb.join(',')} ${BLb.join(',')}`}
        fill="#0f1115"
        stroke={color}
        strokeWidth="0.5"
        strokeOpacity="0.8"
      />
      {/* top */}
      <polygon
        points={pts.map((p) => p.join(',')).join(' ')}
        fill="#2d323d"
        stroke={color}
        strokeWidth="0.7"
      />
      {/* dome on top (LEDs) — small ellipse centred on quad centroid */}
      {dome && (() => {
        const cx = (TL[0] + TR[0] + BR[0] + BL[0]) / 4
        const cy = (TL[1] + TR[1] + BR[1] + BL[1]) / 4
        return (
          <ellipse
            cx={cx}
            cy={cy - 1.2}
            rx="3.5"
            ry="1.4"
            fill={color}
            fillOpacity="0.6"
            stroke={color}
            strokeWidth="0.5"
          />
        )
      })()}
      {/* label */}
      <text
        x={labelPos[0]}
        y={labelPos[1]}
        fontSize="5.5"
        fontFamily="ui-monospace, monospace"
        fill={color}
        textAnchor="middle"
        letterSpacing="0.4"
      >
        {label}
      </text>
    </g>
  )
}
