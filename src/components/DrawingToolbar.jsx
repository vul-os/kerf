import { useEffect, useState } from 'react'
import {
  MousePointer2,
  Ruler,
  Move3d,
  Triangle,
  Circle as CircleIcon,
  Disc,
  Type,
  CornerDownRight,
  Spline,
  Square,
  Gauge,
  Compass,
  AlignVerticalDistributeCenter,
  AlignHorizontalDistributeCenter,
  Crosshair,
  Hash,
  StickyNote,
  Wrench,
  Layers,
  Slash,
  Tag,
  CircleDot,
  Anchor,
  Box,
  Magnet,
  // NEW: drafting completeness
  Grid2x2,
  ArrowUpRight,
  FileText,
  Link2,
} from 'lucide-react'

// localStorage key for the drawing-canvas snap toggle. Read by both the
// toolbar (button state) and DrawingView (skip-snap when disabled). Both
// listen for the `kerf:drawing-snap-changed` custom event so a click here
// updates the canvas in the same tick.
const SNAP_LS_KEY = 'kerf:drawing:snap'

function readSnapEnabled() {
  if (typeof window === 'undefined') return true
  try {
    const v = window.localStorage.getItem(SNAP_LS_KEY)
    if (v === null) return true // default ON
    return v === '1' || v === 'true'
  } catch {
    return true
  }
}

// Floating toolbar for the drawing editor — modelled on MeasureToolbar but
// reorganized into engineering-drawing groups: Views, Dimensions, Annotations,
// Lines, Sheet. Each group is separated by a thin divider so the visual
// hierarchy makes it easy to find the right tool. Tool ids are forwarded to
// DrawingView; some ids (e.g. `add_3view`) are intercepted by Editor /
// PropertiesPanel and turned into actions instead of dimension/draft modes.

const TOOL_GROUPS = [
  {
    label: 'Pointer',
    items: [
      { id: 'pointer',  icon: MousePointer2, label: 'Pointer (V)' },
    ],
  },
  {
    label: 'Dimensions',
    items: [
      { id: 'linear',   icon: Ruler,         label: 'Distance (L)' },
      { id: 'aligned',  icon: Move3d,        label: 'Aligned distance (A)' },
      { id: 'radius',   icon: CircleIcon,    label: 'Radius (R)' },
      { id: 'diameter', icon: Disc,          label: 'Diameter (D)' },
      { id: 'angular',  icon: Triangle,      label: 'Angle (G)' },
      { id: 'baseline', icon: AlignVerticalDistributeCenter, label: 'Baseline · double-click to finish' },
      { id: 'chain',    icon: AlignHorizontalDistributeCenter, label: 'Chain · double-click to finish' },
      { id: 'ordinate', icon: Hash,          label: 'Ordinate · double-click to finish' },
    ],
  },
  {
    label: 'Annotations',
    items: [
      { id: 'leader',         icon: CornerDownRight, label: 'Leader' },
      { id: 'balloon',        icon: CircleDot,       label: 'Balloon (numbered)' },
      { id: 'note',           icon: StickyNote,      label: 'Note (boxed text)' },
      { id: 'text',           icon: Type,            label: 'Plain text' },
      { id: 'surface_finish', icon: Anchor,          label: 'Surface finish (Ra)' },
      { id: 'weld',           icon: Wrench,          label: 'Weld symbol' },
      { id: 'gdt',            icon: Tag,             label: 'GD&T frame' },
    ],
  },
  {
    label: 'Lines',
    items: [
      { id: 'centerline', icon: Crosshair, label: 'Centerline' },
      { id: 'break',      icon: Slash,     label: 'Break line' },
      { id: 'polyline',   icon: Spline,    label: 'Polyline (dbl-click to finish)' },
      { id: 'rect',       icon: Square,    label: 'Rectangle' },
      { id: 'ann-circle', icon: CircleIcon, label: 'Circle' },
    ],
  },
  {
    label: 'Measure',
    items: [
      { id: 'measure-distance', icon: Gauge,   label: 'Measure distance (transient)' },
      { id: 'measure-angle',    icon: Compass, label: 'Measure angle (transient)' },
    ],
  },
  // ---------------------------------------------------------------------------
  // NEW: Drafting completeness tools.
  {
    label: 'Completeness',
    items: [
      { id: 'hatch',     icon: Grid2x2,      label: 'Hatch · click polygon then dbl-click to pick pattern' },
      { id: 'dc-leader', icon: ArrowUpRight,  label: 'Leader (with text)' },
      { id: 'rich-text', icon: FileText,      label: 'Rich text annotation' },
      { id: 'dim-chain', icon: Link2,         label: 'Dimension chain · click picks, dbl-click to finish' },
    ],
  },
]

// Optional sheet-level actions wired in from the parent. Surfaced as a
// separate button strip below the tool groups so they don't clutter the main
// flow.
export default function DrawingToolbar({
  tool = 'pointer',
  onTool,
  onAddSheet,
  showSheetActions = false,
}) {
  // Snap-enabled state. Persisted under `kerf:drawing:snap`; broadcast via a
  // window custom event so DrawingView (mounted as a sibling, not a child)
  // can react without prop-drilling through Editor.jsx.
  const [snapEnabled, setSnapEnabled] = useState(readSnapEnabled)
  useEffect(() => {
    function onChanged() { setSnapEnabled(readSnapEnabled()) }
    window.addEventListener('kerf:drawing-snap-changed', onChanged)
    window.addEventListener('storage', onChanged)
    return () => {
      window.removeEventListener('kerf:drawing-snap-changed', onChanged)
      window.removeEventListener('storage', onChanged)
    }
  }, [])
  const toggleSnap = () => {
    const next = !snapEnabled
    try { window.localStorage.setItem(SNAP_LS_KEY, next ? '1' : '0') } catch {}
    setSnapEnabled(next)
    window.dispatchEvent(new CustomEvent('kerf:drawing-snap-changed'))
  }

  return (
    <div className="absolute top-3 left-3 z-10 flex flex-col gap-1 p-1 rounded-md bg-ink-900/85 border border-ink-700 backdrop-blur shadow-lg">
      {TOOL_GROUPS.map((group, gi) => (
        <div key={gi} className="flex flex-col gap-1">
          {gi > 0 && <div className="h-px bg-ink-700/70 mx-0.5 my-0.5" />}
          {group.items.map(({ id, icon: Icon, label }) => {
            const active = id === tool
            return (
              <button
                key={id}
                type="button"
                title={label}
                onClick={() => onTool?.(id)}
                className={`p-1.5 rounded transition-colors ${
                  active
                    ? 'bg-kerf-300 text-ink-950'
                    : 'bg-ink-900/60 text-ink-300 hover:text-kerf-300 hover:bg-ink-800 border border-ink-700/50'
                }`}
              >
                <Icon size={14} />
              </button>
            )
          })}
        </div>
      ))}
      {/* Snap toggle — last group, always visible. Active state mirrors the
          tool buttons so the user can scan the column for "what's enabled". */}
      <div className="h-px bg-ink-700/70 mx-0.5 my-0.5" />
      <button
        type="button"
        title={snapEnabled ? 'Snap on (click to disable)' : 'Snap off (click to enable)'}
        onClick={toggleSnap}
        className={`p-1.5 rounded transition-colors ${
          snapEnabled
            ? 'bg-kerf-300 text-ink-950'
            : 'bg-ink-900/60 text-ink-300 hover:text-kerf-300 hover:bg-ink-800 border border-ink-700/50'
        }`}
      >
        <Magnet size={14} />
      </button>
      {showSheetActions && (
        <>
          <div className="h-px bg-ink-700/70 mx-0.5 my-0.5" />
          <button
            type="button"
            title="Add sheet"
            onClick={() => onAddSheet?.()}
            className="p-1.5 rounded bg-ink-900/60 text-ink-300 hover:text-kerf-300 hover:bg-ink-800 border border-ink-700/50"
          >
            <Layers size={14} />
          </button>
        </>
      )}
    </div>
  )
}
