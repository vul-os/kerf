/**
 * GitIllustration — clear git-graph metaphor on the left + a clean GitHub
 * sync tile on the right. Commit dots carry the graph SHAPE; minimal text.
 *
 * viewBox 320×200. Palette locked.
 */
export default function GitIllustration({ className = '' }) {
  const MAIN = '#ffd633'
  const FEAT_A = '#6bd4ff'
  const FEAT_B = '#ff6bd4'

  // Graph occupies the LEFT 60% of the card; GitHub tile sits in the RIGHT
  // 35%. Lanes are evenly spaced vertically; main is the middle.
  const LANE_MAIN_Y = 110
  const LANE_A_Y = 78
  const LANE_B_Y = 142

  // Commit x positions along main lane. Kept inside x=[60, 200].
  const X = [60, 88, 116, 144, 172, 200]

  return (
    <svg
      viewBox="0 0 320 200"
      preserveAspectRatio="xMidYMid meet"
      className={className}
      role="img"
      aria-label="A horizontal git graph with a feature branch diverging from and merging back into main, plus a second feature branch in progress, syncing to GitHub"
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

      {/* lane labels — sit BEFORE the first commit so they never overlap the
          graph; right-aligned to a vertical guide at x=54. */}
      <g
        fontSize="7"
        fontFamily="ui-monospace, SFMono-Regular, monospace"
        textAnchor="end"
      >
        <text x="54" y={LANE_A_Y + 3} fill={FEAT_A} opacity="0.9">feat/a</text>
        <text x="54" y={LANE_MAIN_Y + 3} fill={MAIN}>main</text>
        <text x="54" y={LANE_B_Y + 3} fill={FEAT_B} opacity="0.9">feat/b</text>
      </g>

      {/* === branch curves === */}
      <g fill="none" strokeWidth="1.6" strokeLinecap="round">
        {/* main lane — straight horizontal */}
        <line x1={X[0]} y1={LANE_MAIN_Y} x2={X[5]} y2={LANE_MAIN_Y} stroke={MAIN} />

        {/* feat/a: branch from main at X[1], merge back at X[4] */}
        <path
          d={`M ${X[1]} ${LANE_MAIN_Y} C ${X[1] + 10} ${LANE_MAIN_Y}, ${X[2] - 10} ${LANE_A_Y}, ${X[2]} ${LANE_A_Y}`}
          stroke={FEAT_A}
        />
        <line x1={X[2]} y1={LANE_A_Y} x2={X[3]} y2={LANE_A_Y} stroke={FEAT_A} />
        <path
          d={`M ${X[3]} ${LANE_A_Y} C ${X[3] + 10} ${LANE_A_Y}, ${X[4] - 10} ${LANE_MAIN_Y}, ${X[4]} ${LANE_MAIN_Y}`}
          stroke={FEAT_A}
        />

        {/* feat/b: branch from main at X[3], in-progress tip */}
        <path
          d={`M ${X[3]} ${LANE_MAIN_Y} C ${X[3] + 10} ${LANE_MAIN_Y}, ${X[4] - 10} ${LANE_B_Y}, ${X[4]} ${LANE_B_Y}`}
          stroke={FEAT_B}
        />
        <line x1={X[4]} y1={LANE_B_Y} x2={X[5] - 6} y2={LANE_B_Y} stroke={FEAT_B} />
      </g>

      {/* === commit dots === */}
      <CommitDot cx={X[0]} cy={LANE_MAIN_Y} color={MAIN} />
      <CommitDot cx={X[1]} cy={LANE_MAIN_Y} color={MAIN} />
      <CommitDot cx={X[3]} cy={LANE_MAIN_Y} color={MAIN} />
      <CommitDot cx={X[4]} cy={LANE_MAIN_Y} color={MAIN} merge />
      <CommitDot cx={X[5]} cy={LANE_MAIN_Y} color={MAIN} head />

      <CommitDot cx={X[2]} cy={LANE_A_Y} color={FEAT_A} />
      <CommitDot cx={X[3]} cy={LANE_A_Y} color={FEAT_A} />

      <CommitDot cx={X[4]} cy={LANE_B_Y} color={FEAT_B} />
      <CommitDot cx={X[5] - 6} cy={LANE_B_Y} color={FEAT_B} tip />

      {/* HEAD chip below the latest main commit so it doesn't crowd the
          sync arrow at the top. */}
      <g transform={`translate(${X[5] - 16}, ${LANE_MAIN_Y + 12})`}>
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
      </g>

      {/* === GitHub sync tile (right side) ===
          Clean octocat-inspired mark: face circle + ears + smile + tentacle.
          Sized to fit cleanly inside a 64×44 tile. */}
      <g transform="translate(232, 70)">
        <rect width="64" height="44" rx="6" fill="#0f1115" stroke="#1a1d24" />
        <g transform="translate(8, 6)">
          {/* head */}
          <circle cx="16" cy="17" r="13" fill="#0a0b0d" stroke="#cbd0dc" strokeWidth="1.1" />
          {/* ears */}
          <path d="M 7 8 L 10 5 L 12 10 Z" fill="#cbd0dc" />
          <path d="M 25 8 L 22 5 L 20 10 Z" fill="#cbd0dc" />
          {/* eyes */}
          <circle cx="12.5" cy="16" r="1.4" fill="#0a0b0d" />
          <circle cx="19.5" cy="16" r="1.4" fill="#0a0b0d" />
          {/* mouth */}
          <path d="M 13 21 Q 16 23 19 21" fill="none" stroke="#cbd0dc" strokeWidth="0.9" strokeLinecap="round" />
          {/* tentacle */}
          <path d="M 16 30 Q 16 33 19 33 Q 22 33 22 30" fill="none" stroke="#cbd0dc" strokeWidth="0.9" strokeLinecap="round" />
        </g>
        {/* GitHub label */}
        <text
          x="58"
          y="18"
          textAnchor="end"
          fontSize="8"
          fontFamily="ui-sans-serif, system-ui, sans-serif"
          fontWeight="600"
          fill="#cbd0dc"
        >
          GitHub
        </text>
        <text
          x="58"
          y="30"
          textAnchor="end"
          fontSize="7"
          fontFamily="ui-monospace, SFMono-Regular, monospace"
          fill="#7BB661"
        >
          ↑ in sync
        </text>
      </g>

      {/* sync arrow from latest commit → tile (curved, dashed) */}
      <g stroke="#3a4150" strokeWidth="0.8" fill="none" strokeDasharray="2 2">
        <path d={`M ${X[5] + 4} ${LANE_MAIN_Y - 4} Q 226 90 232 92`} />
      </g>

      {/* footer — pygit2 only (cloud-internal tech stripped) */}
      <text
        x="22"
        y="178"
        fontSize="7"
        fontFamily="ui-monospace, SFMono-Regular, monospace"
        fill="#5a6275"
      >
        pygit2 · branches · merges · push / pull
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
