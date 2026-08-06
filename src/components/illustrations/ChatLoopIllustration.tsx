/**
 * ChatLoopIllustration — single-frame view of the LLM loop:
 * user message → tool call card → assistant reply → updated 3D viewport.
 * Connecting arrows between each stage.
 */
export default function ChatLoopIllustration({ className = '' }) {
  return (
    <svg
      viewBox="0 0 880 280"
      preserveAspectRatio="xMidYMid meet"
      className={className}
      role="img"
      aria-label="Chat loop: user message becomes a tool call, then an assistant reply, then an updated 3D model"
    >
      <defs>
        <linearGradient id="cl-top" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#2d323d" />
          <stop offset="100%" stopColor="#1a1d24" />
        </linearGradient>
        <linearGradient id="cl-side" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0%" stopColor="#1a1d24" />
          <stop offset="100%" stopColor="#0f1115" />
        </linearGradient>
        <marker id="cl-arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M0,0 L10,5 L0,10 z" fill="#ffd633" />
        </marker>
      </defs>

      {/* USER MESSAGE */}
      <Stage x={20} y={50} w={180} h={180} label="USER">
        <text x="14" y="38" fontSize="11" fontFamily="ui-sans-serif, system-ui" fill="#e2e6ee">
          make this 6mm
        </text>
        <text x="14" y="56" fontSize="11" fontFamily="ui-sans-serif, system-ui" fill="#e2e6ee">
          and add a fillet
        </text>
        <g transform="translate(14, 80)">
          <rect width="86" height="18" rx="3" fill="#ffd633" fillOpacity="0.12" stroke="#ffd633" strokeOpacity="0.3" />
          <text x="8" y="13" fontSize="10" fontFamily="ui-monospace, monospace" fill="#ffe566">
            bracket#wall
          </text>
        </g>
        <text x="14" y="130" fontSize="9" fontFamily="ui-monospace, monospace" fill="#5a6275">
          @ user · 13:42
        </text>
      </Stage>

      <Arrow x1={206} x2={244} y={140} />

      {/* TOOL CALLS */}
      <Stage x={250} y={50} w={210} h={180} label="TOOL CALLS">
        <ToolRow y={36} kind="search_kerf_docs" arg="fillet" />
        <ToolRow y={66} kind="edit_file" arg="bracket.jscad" />
        <ToolRow y={96} kind="validate" arg="ok ✓" ok />
        <ToolRow y={126} kind="render" arg="3,142 tris" />
      </Stage>

      <Arrow x1={466} x2={504} y={140} />

      {/* ASSISTANT REPLY */}
      <Stage x={510} y={50} w={170} h={180} label="ASSISTANT">
        <text x="14" y="38" fontSize="11" fontFamily="ui-sans-serif, system-ui" fill="#b8bfcc">
          Thickened the wall to
        </text>
        <text x="14" y="54" fontSize="11" fontFamily="ui-sans-serif, system-ui" fill="#b8bfcc">
          6mm and added a 2mm
        </text>
        <text x="14" y="70" fontSize="11" fontFamily="ui-sans-serif, system-ui" fill="#b8bfcc">
          fillet on the top edge.
        </text>
        <text x="14" y="98" fontSize="10" fontFamily="ui-monospace, monospace" fill="#5a6275">
          1 file changed
        </text>
        <text x="14" y="114" fontSize="10" fontFamily="ui-monospace, monospace" fill="#5a6275">
          1 revision logged
        </text>
        <g transform="translate(14, 130)">
          <rect width="58" height="16" rx="3" fill="#7BB661" fillOpacity="0.12" stroke="#7BB661" strokeOpacity="0.4" />
          <circle cx="9" cy="8" r="2.4" fill="#7BB661" />
          <text x="18" y="11" fontSize="9" fontFamily="ui-monospace, monospace" fill="#7BB661">
            applied
          </text>
        </g>
      </Stage>

      <Arrow x1={686} x2={724} y={140} />

      {/* UPDATED VIEWPORT */}
      <Stage x={730} y={50} w={130} h={180} label="3D">
        <g transform="translate(64, 100)">
          <polygon points="-44,-14 18,-26 50,4 -12,16" fill="url(#cl-top)" stroke="#3a4150" />
          <polygon points="-44,-14 -12,16 -12,30 -44,2" fill="#14171c" stroke="#3a4150" />
          <polygon points="-12,16 50,4 50,18 -12,30" fill="url(#cl-side)" stroke="#3a4150" />
          <polygon points="-22,-22 16,-30 16,-50 -22,-44" fill="#1a1d24" stroke="#ffd633" strokeWidth="1.2" />
          <polygon points="16,-30 30,-22 30,-42 16,-50" fill="#0f1115" stroke="#ffd633" strokeWidth="1.2" />
          <polygon points="-22,-22 -8,-14 30,-22 16,-30" fill="url(#cl-top)" stroke="#ffd633" strokeWidth="1.2" />
          <path d="M -22 -44 Q -22 -49 -16 -49 L 12 -55 Q 16 -55 16 -50" fill="none" stroke="#ffd633" strokeWidth="1.6" />
        </g>
      </Stage>
    </svg>
  )
}

function Stage({ x, y, w, h, label, children }) {
  return (
    <g transform={`translate(${x}, ${y})`}>
      <rect width={w} height={h} rx="8" fill="#0a0b0d" stroke="#1a1d24" />
      <rect x="0" y="0" width={w} height="20" fill="#0f1115" />
      <text x="10" y="14" fontSize="9" fontFamily="ui-monospace, monospace" fill="#5a6275" letterSpacing="1.4">
        {label}
      </text>
      {children}
    </g>
  )
}

function Arrow({ x1, x2, y }) {
  return (
    <g>
      <line x1={x1} y1={y} x2={x2 - 8} y2={y} stroke="#ffd633" strokeWidth="1.5" markerEnd="url(#cl-arr)" />
      <circle cx={x1} cy={y} r="2.5" fill="#ffd633" />
    </g>
  )
}

function ToolRow({ y, kind, arg, ok }) {
  return (
    <g transform={`translate(14, ${y})`}>
      <rect width="182" height="22" rx="4" fill="#0f1115" stroke="#1a1d24" />
      <circle cx="10" cy="11" r="2.5" fill={ok ? '#7BB661' : '#ffd633'} />
      <text x="20" y="14" fontSize="9.5" fontFamily="ui-monospace, monospace" fill="#ffe566">
        {kind}
      </text>
      <text x="178" y="14" textAnchor="end" fontSize="9.5" fontFamily="ui-monospace, monospace" fill="#8a93a6">
        {arg}
      </text>
    </g>
  )
}
