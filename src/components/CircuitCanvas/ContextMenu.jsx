// ContextMenu.jsx — Right-click context menu for wire editing actions.
//
// Appears when the user right-clicks (or long-presses) a pcb_trace on the
// canvas.  Calls pure wireEdit.js helpers to produce patched Circuit JSON and
// forwards the result via `onPatch`.
//
// Props:
//   x, y          — screen coordinates (px) where the menu should appear
//   traceId       — pcb_trace_id of the right-clicked wire
//   circuitJson   — current Circuit JSON (flat array)
//   onPatch(next) — called with the patched Circuit JSON after an action
//   onClose()     — called when the menu should close without an action

import { useEffect, useRef } from 'react'
import { deleteWire, rerouteWire, pinWireToGrid } from './wireEdit.js'

// Default grid used for "pin to grid" action (mm)
const DEFAULT_GRID_MM = 0.5

export default function ContextMenu({ x, y, traceId, circuitJson, onPatch, onClose }) {
  const menuRef = useRef(null)

  // Close on outside click or Escape
  useEffect(() => {
    function handlePointerDown(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        onClose?.()
      }
    }
    function handleKeyDown(e) {
      if (e.key === 'Escape') onClose?.()
    }
    document.addEventListener('pointerdown', handlePointerDown, { capture: true })
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown, { capture: true })
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [onClose])

  function handleDelete(e) {
    e.stopPropagation()
    const next = deleteWire(circuitJson, traceId)
    onPatch?.(next)
    onClose?.()
  }

  function handleReroute(e) {
    e.stopPropagation()
    const next = rerouteWire(circuitJson, traceId)
    onPatch?.(next)
    onClose?.()
  }

  function handlePin(e) {
    e.stopPropagation()
    const next = pinWireToGrid(circuitJson, traceId, DEFAULT_GRID_MM)
    onPatch?.(next)
    onClose?.()
  }

  // "Convert to bus" is listed in the spec as a menu item but is a Phase-2
  // feature (requires net grouping which is not yet implemented).  We render
  // it disabled so the menu matches the spec without crashing.
  function handleConvertToBus(e) {
    e.stopPropagation()
    // TODO(phase-2): implement bus conversion
    onClose?.()
  }

  const menuStyle = {
    position: 'fixed',
    left: x,
    top: y,
    zIndex: 9999,
  }

  return (
    <div
      ref={menuRef}
      role="menu"
      aria-label="Wire actions"
      style={menuStyle}
      className="bg-zinc-900 border border-zinc-700 rounded-md shadow-xl py-1 min-w-[160px] text-sm text-zinc-100 select-none"
      onContextMenu={(e) => e.preventDefault()}
    >
      <button
        role="menuitem"
        onClick={handleDelete}
        className="w-full text-left px-3 py-1.5 hover:bg-zinc-700 text-red-400 hover:text-red-300 transition-colors"
      >
        Delete wire
      </button>

      <button
        role="menuitem"
        onClick={handleReroute}
        className="w-full text-left px-3 py-1.5 hover:bg-zinc-700 transition-colors"
      >
        Re-route
      </button>

      <button
        role="menuitem"
        onClick={handlePin}
        className="w-full text-left px-3 py-1.5 hover:bg-zinc-700 transition-colors"
      >
        Pin to grid
      </button>

      <button
        role="menuitem"
        onClick={handleConvertToBus}
        disabled
        className="w-full text-left px-3 py-1.5 text-zinc-500 cursor-not-allowed"
        title="Coming soon"
      >
        Convert to bus
      </button>
    </div>
  )
}
