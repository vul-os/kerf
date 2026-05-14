/**
 * ScriptingIllustration — Python `kerf-sdk` snippet on the left, JSON-RPC
 * envelope arrow in the middle, project file tree on the right.
 * Communicates "scriptable from your own machine."
 *
 * viewBox 320×200. Layout columns:
 *   Python pane    x=16  w=156   (ends 172)
 *   RPC envelope   x=178 w=46    (ends 224)   centered between panes
 *   Project pane   x=230 w=78    (ends 308)
 * Outer panel ends at x=312, so all content sits inside the 8px gutter.
 *
 * Code rendered as single-line <text> rows with one fill each so monospace
 * alignment stays clean. Row content kept under 22 mono chars at 7.5pt to
 * stay inside the 156px Python pane (≈4.5px / char → ~99px max width).
 */
export default function ScriptingIllustration({ className = '' }) {
  const codeRows = [
    { y: 60, content: '$ pip install kerf-sdk', fill: '#5a6275' },
    { y: 74, content: 'from kerf import Kerf', fill: '#cbd0dc' },
    { y: 86, content: 'k = Kerf.from_env()', fill: '#cbd0dc' },
    { y: 104, content: '# sweep diameter', fill: '#5a6275' },
    { y: 118, content: 'for d in [4, 5, 6, 8]:', fill: '#cbd0dc' },
    { y: 130, content: '  k.equations.set(', fill: '#cbd0dc' },
    { y: 142, content: '    "dia", d)', fill: '#7BB661' },
    { y: 156, content: '  k.files.write(', fill: '#cbd0dc' },
    { y: 168, content: '    "main.jscad")', fill: '#7BB661' },
  ]

  const files = [
    { y: 76, name: 'main.jscad', active: true },
    { y: 90, name: '.equations' },
    { y: 104, name: 'profile.sketch' },
    { y: 118, name: 'frame.assembly' },
    { y: 132, name: 'sheet.drawing' },
    { y: 146, name: 'board.circuit' },
  ]

  return (
    <svg
      viewBox="0 0 320 200"
      preserveAspectRatio="xMidYMid meet"
      className={className}
      role="img"
      aria-label="Python kerf-sdk snippet sending a JSON-RPC call to a project file tree"
    >
      <defs>
        <marker
          id="scr-arrow"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto"
        >
          <path d="M0,1 L9,5 L0,9 Z" fill="#ffd633" />
        </marker>
      </defs>

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
        KERF-SDK · PYTHON
      </text>
      <line x1="22" y1="40" x2="298" y2="40" stroke="#1a1d24" strokeWidth="0.6" />

      {/* === Left: Python snippet === */}
      <rect x="16" y="48" width="156" height="128" rx="4" fill="#0d0f13" stroke="#1a1d24" />
      <g fontSize="7.5" fontFamily="ui-monospace, SFMono-Regular, monospace">
        {codeRows.map((row, i) => (
          <text key={i} x="24" y={row.y} fill={row.fill}>
            {row.content}
          </text>
        ))}
      </g>

      {/* === Middle: RPC envelope === */}
      <g transform="translate(178, 96)">
        <rect width="46" height="32" rx="3" fill="#0d0f13" stroke="#ffd633" strokeOpacity="0.8" />
        <text
          x="23"
          y="14"
          textAnchor="middle"
          fontSize="7"
          fontFamily="ui-monospace, monospace"
          fill="#ffd633"
          letterSpacing="0.4"
        >
          POST
        </text>
        <text
          x="23"
          y="25"
          textAnchor="middle"
          fontSize="6.5"
          fontFamily="ui-monospace, monospace"
          fill="#cbd0dc"
        >
          /v1/rpc
        </text>
      </g>

      {/* arrows on either side of envelope */}
      <g stroke="#ffd633" strokeWidth="1" fill="none" strokeLinecap="round">
        <line x1="172" y1="112" x2="178" y2="112" />
        <line x1="224" y1="112" x2="232" y2="112" markerEnd="url(#scr-arrow)" />
      </g>

      {/* === Right: project files === */}
      <rect x="230" y="48" width="78" height="128" rx="4" fill="#0d0f13" stroke="#1a1d24" />
      <text
        x="269"
        y="62"
        textAnchor="middle"
        fontSize="7"
        fontFamily="ui-monospace, monospace"
        fill="#5a6275"
        letterSpacing="1.2"
      >
        PROJECT
      </text>
      <line x1="238" y1="68" x2="300" y2="68" stroke="#1a1d24" strokeWidth="0.5" />

      <g fontSize="7" fontFamily="ui-monospace, monospace">
        {files.map((f) => (
          <g key={f.name}>
            {f.active && (
              <rect
                x="236"
                y={f.y - 8}
                width="66"
                height="11"
                rx="2"
                fill="#ffd633"
                fillOpacity="0.12"
                stroke="#ffd633"
                strokeOpacity="0.35"
              />
            )}
            <text x="240" y={f.y} fill={f.active ? '#ffd633' : '#a8aebf'}>
              {f.name}
            </text>
          </g>
        ))}
        <line x1="238" y1="156" x2="300" y2="156" stroke="#1a1d24" strokeWidth="0.5" />
        <text x="240" y="168" fontSize="6.5" fill="#7BB661">
          ↻ revisioned
        </text>
      </g>
    </svg>
  )
}
