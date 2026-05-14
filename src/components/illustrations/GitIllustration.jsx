/**
 * GitIllustration — clear git-graph metaphor: a main lane with a feature
 * branch that diverges and merges back, plus a second feature branch that
 * tips out. Commit dots are large and unlabeled so the SHAPE of the graph
 * reads at a glance; a single HEAD chip + GitHub corner tile carry the
 * cloud-sync meaning. Heavy text removed.
 *
 * viewBox 320×200. Palette locked.
 */
export default function GitIllustration({ className = '' }) {
  const MAIN = '#ffd633'
  const FEAT_A = '#6bd4ff'
  const FEAT_B = '#ff6bd4'

  // Lane x positions (horizontal layout: commits flow left → right).
  const LANE_MAIN_Y = 110
  const LANE_A_Y = 78
  const LANE_B_Y = 142

  // Commit x positions along main lane.
  const X = [44, 76, 108, 140, 172, 204]

  return (
    <svg
      viewBox="0 0 320 200"
      preserveAspectRatio="xMidYMid meet"
      className={className}
      role="img"
      aria-label="A horizontal git graph with a feature branch diverging from and merging back into main, plus a second feature branch tipping out"
    >
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
        GIT · CLOUD SYNC
      </text>
      <line x1="22" y1="40" x2="298" y2="40" stroke="#1a1d24" strokeWidth="0.6" />

      {/* lane labels (very minimal) */}
      <text
        x="22"
        y={LANE_A_Y + 3}
        fontSize="7"
        fontFamily="ui-monospace, SFMono-Regular, monospace"
        fill={FEAT_A}
        opacity="0.85"
      >
        feat/a
      </text>
      <text
        x="22"
        y={LANE_MAIN_Y + 3}
        fontSize="7"
        fontFamily="ui-monospace, SFMono-Regular, monospace"
        fill={MAIN}
      >
        main
      </text>
      <text
        x="22"
        y={LANE_B_Y + 3}
        fontSize="7"
        fontFamily="ui-monospace, SFMono-Regular, monospace"
        fill={FEAT_B}
        opacity="0.85"
      >
        feat/b
      </text>

      {/* === branch curves === */}
      <g fill="none" strokeWidth="1.6" strokeLinecap="round">
        {/* main lane — straight horizontal */}
        <line x1={X[0]} y1={LANE_MAIN_Y} x2={X[5]} y2={LANE_MAIN_Y} stroke={MAIN} />

        {/* feat/a: branch from main at X[1], merge back at X[4] */}
        <path
          d={`M ${X[1]} ${LANE_MAIN_Y} C ${X[1] + 12} ${LANE_MAIN_Y}, ${X[2] - 12} ${LANE_A_Y}, ${X[2]} ${LANE_A_Y}`}
          stroke={FEAT_A}
        />
        <line x1={X[2]} y1={LANE_A_Y} x2={X[3]} y2={LANE_A_Y} stroke={FEAT_A} />
        <path
          d={`M ${X[3]} ${LANE_A_Y} C ${X[3] + 12} ${LANE_A_Y}, ${X[4] - 12} ${LANE_MAIN_Y}, ${X[4]} ${LANE_MAIN_Y}`}
          stroke={FEAT_A}
        />

        {/* feat/b: branch from main at X[3], tips out (in progress) */}
        <path
          d={`M ${X[3]} ${LANE_MAIN_Y} C ${X[3] + 12} ${LANE_MAIN_Y}, ${X[4] - 12} ${LANE_B_Y}, ${X[4]} ${LANE_B_Y}`}
          stroke={FEAT_B}
        />
        <line x1={X[4]} y1={LANE_B_Y} x2={X[5] - 10} y2={LANE_B_Y} stroke={FEAT_B} />
      </g>

      {/* === commit dots === */}
      {/* main lane dots */}
      <CommitDot cx={X[0]} cy={LANE_MAIN_Y} color={MAIN} />
      <CommitDot cx={X[1]} cy={LANE_MAIN_Y} color={MAIN} />
      <CommitDot cx={X[3]} cy={LANE_MAIN_Y} color={MAIN} />
      <CommitDot cx={X[4]} cy={LANE_MAIN_Y} color={MAIN} merge />
      <CommitDot cx={X[5]} cy={LANE_MAIN_Y} color={MAIN} head />

      {/* feat/a dots */}
      <CommitDot cx={X[2]} cy={LANE_A_Y} color={FEAT_A} />
      <CommitDot cx={X[3]} cy={LANE_A_Y} color={FEAT_A} />

      {/* feat/b tip */}
      <CommitDot cx={X[4]} cy={LANE_B_Y} color={FEAT_B} />
      <CommitDot cx={X[5] - 10} cy={LANE_B_Y} color={FEAT_B} tip />

      {/* HEAD chip floats above the latest main commit */}
      <g transform={`translate(${X[5] - 16}, ${LANE_MAIN_Y - 24})`}>
        <rect width="34" height="13" rx="2.5" fill="#0a0b0d" stroke={MAIN} strokeOpacity="0.75" />
        <text
          x="17"
          y="9.5"
          textAnchor="middle"
          fontSize="7"
          fontFamily="ui-monospace, SFMono-Regular, monospace"
          fill={MAIN}
        >
          HEAD
        </text>
        <line
          x1="17"
          y1="13"
          x2="17"
          y2={20}
          stroke={MAIN}
          strokeOpacity="0.55"
          strokeWidth="0.7"
        />
      </g>

      {/* === GitHub sync tile (right side) === */}
      <g transform="translate(240, 64)">
        <rect width="60" height="56" rx="6" fill="#0f1115" stroke="#1a1d24" />
        {/* GitHub mark — simplified circle + cat tail loop */}
        <g transform="translate(10, 8)">
          <circle cx="20" cy="20" r="14" fill="#0a0b0d" stroke="#cbd0dc" strokeWidth="1" />
          <path
            d="M 20 11 C 25 11, 28.5 14, 28.5 19 C 28.5 23, 26 25, 23 25.5 C 23.4 25.9, 23.7 26.6, 23.7 27.6 L 23.7 30.5 M 16.3 30.5 L 16.3 28 C 13.5 28.5, 12.4 26.8, 12 26.0 C 11.6 25.2, 10.7 24, 9.6 23.8 M 16.3 28 C 17.5 28.2, 18.5 28.2, 19.5 28"
            fill="none"
            stroke="#cbd0dc"
            strokeWidth="1"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </g>
        <text
          x="30"
          y="51"
          textAnchor="middle"
          fontSize="7"
          fontFamily="ui-monospace, SFMono-Regular, monospace"
          fill="#7BB661"
        >
          ↑ in sync
        </text>
      </g>

      {/* sync arrow from HEAD area to github tile */}
      <g stroke="#3a4150" strokeWidth="0.8" fill="none" strokeDasharray="2 2">
        <line x1={X[5] + 4} y1={LANE_MAIN_Y - 10} x2="244" y2="92" />
      </g>

      {/* footer — pygit2 only (cloud-internal tech stripped) */}
      <text
        x="22"
        y="180"
        fontSize="7"
        fontFamily="ui-monospace, SFMono-Regular, monospace"
        fill="#5a6275"
      >
        pygit2 · branches · merges
      </text>
      <text
        x="298"
        y="180"
        textAnchor="end"
        fontSize="7"
        fontFamily="ui-monospace, SFMono-Regular, monospace"
        fill="#5a6275"
      >
        push / pull
      </text>
    </svg>
  )
}

function CommitDot({ cx, cy, color, head, merge, tip }) {
  const outerR = head ? 5.5 : merge ? 5 : 4
  return (
    <g>
      {tip && (
        <circle
          cx={cx}
          cy={cy}
          r={outerR + 3}
          fill="none"
          stroke={color}
          strokeOpacity="0.35"
          strokeWidth="0.8"
        />
      )}
      <circle cx={cx} cy={cy} r={outerR} fill="#0a0b0d" stroke={color} strokeWidth="1.4" />
      <circle cx={cx} cy={cy} r={outerR - 2.2} fill={color} />
    </g>
  )
}
