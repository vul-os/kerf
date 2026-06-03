/**
 * Connection.jsx — SVG Bezier wire between two node pins.
 *
 * Props:
 *   fromX, fromY  – start point (output pin world coords)
 *   toX, toY      – end point (input pin world coords)
 *   selected      – boolean highlight
 *   color         – stroke colour (defaults to #6bd4ff)
 *   onClick       – called with connection id when clicked
 *   id            – connection id passed to onClick
 */

export default function Connection({
  fromX,
  fromY,
  toX,
  toY,
  selected = false,
  color = '#6bd4ff',
  onClick,
  id,
}) {
  const dx = Math.abs(toX - fromX) * 0.6
  const cp1x = fromX + dx
  const cp2x = toX  - dx

  const d = `M ${fromX},${fromY} C ${cp1x},${fromY} ${cp2x},${toY} ${toX},${toY}`

  return (
    <g
      onClick={onClick ? (e) => { e.stopPropagation(); onClick(id) } : undefined}
      style={{ cursor: onClick ? 'pointer' : 'default' }}
    >
      {/* Fat invisible hit area */}
      <path
        d={d}
        fill="none"
        stroke="transparent"
        strokeWidth={12}
        style={{ pointerEvents: 'stroke' }}
      />
      {/* Shadow / glow behind the wire */}
      {selected && (
        <path
          d={d}
          fill="none"
          stroke={color}
          strokeWidth={5}
          strokeOpacity={0.35}
          style={{ pointerEvents: 'none' }}
        />
      )}
      {/* Actual wire */}
      <path
        d={d}
        fill="none"
        stroke={color}
        strokeWidth={selected ? 2.5 : 1.8}
        strokeOpacity={selected ? 1 : 0.75}
        strokeLinecap="round"
        style={{ pointerEvents: 'none' }}
      />
    </g>
  )
}
