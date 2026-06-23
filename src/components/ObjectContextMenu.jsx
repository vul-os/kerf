// ObjectContextMenu.jsx — Right-click context menu for 3D objects (parts).
//
// Appears when the user right-clicks a part in the Renderer viewport. Surfaces
// the common "standard modelling" actions: hide/show, isolate, change colour,
// and change transparency. Visibility + transparency are session-only viewport
// state; colour is persisted to the JSCAD source via the store's recolorPart.
//
// Props:
//   x, y            — screen coordinates (px) where the menu should appear
//   partId          — id of the right-clicked part
//   isHidden        — whether the part is currently hidden
//   colorHex        — current swatch colour as "#rrggbb" (for the picker default)
//   opacity         — current opacity 0..1 (1 = fully opaque)
//   isStepFile      — STEP files are read-only, so colour editing is disabled
//   onHide()        — toggle visibility for this part
//   onIsolate()     — hide all other parts
//   onShowAll()     — un-hide everything
//   onRecolor(rgb)  — set colour; rgb is [r,g,b] each 0..1
//   onSetOpacity(o) — set opacity 0..1
//   onClose()       — dismiss the menu without an action

import { useEffect, useRef } from 'react'
import { Eye, EyeOff, Focus, Layers, Palette, Droplet } from 'lucide-react'

function hexToRgb(h) {
  const m = /^#?([0-9a-f]{6})$/i.exec(h || '')
  if (!m) return [1, 1, 1]
  const n = parseInt(m[1], 16)
  return [((n >> 16) & 0xff) / 255, ((n >> 8) & 0xff) / 255, (n & 0xff) / 255]
}

// Transparency presets shown as quick buttons (label → opacity).
const OPACITY_PRESETS = [
  { label: '100%', value: 1 },
  { label: '75%', value: 0.75 },
  { label: '50%', value: 0.5 },
  { label: '25%', value: 0.25 },
]

export default function ObjectContextMenu({
  x,
  y,
  partId,
  isHidden = false,
  colorHex = '#cccccc',
  opacity = 1,
  isStepFile = false,
  onHide,
  onIsolate,
  onShowAll,
  onRecolor,
  onSetOpacity,
  onClose,
}) {
  const menuRef = useRef(null)
  const colorInputRef = useRef(null)

  // Close on outside click or Escape. Capture phase so we win the race with
  // the Renderer's own pointer handlers underneath.
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

  // Keep the menu on-screen: nudge left/up if it would overflow the viewport.
  // Approximate dims are fine — the menu is small and fixed-width.
  const MENU_W = 220
  const MENU_H = 280
  const left = typeof window !== 'undefined' ? Math.min(x, window.innerWidth - MENU_W - 8) : x
  const top = typeof window !== 'undefined' ? Math.min(y, window.innerHeight - MENU_H - 8) : y

  const pct = Math.round((opacity ?? 1) * 100)

  return (
    <div
      ref={menuRef}
      role="menu"
      aria-label={`Actions for ${partId}`}
      style={{ position: 'fixed', left: Math.max(8, left), top: Math.max(8, top), zIndex: 9999 }}
      className="w-[200px] rounded-md bg-ink-850 border border-ink-700 shadow-xl py-1 text-[12px] text-ink-100 select-none"
      onContextMenu={(e) => e.preventDefault()}
      onClick={(e) => e.stopPropagation()}
    >
      <div className="px-3 py-1 text-[10px] uppercase tracking-wider text-ink-500 font-semibold font-mono truncate">
        {partId}
      </div>
      <div className="my-1 border-t border-ink-800" />

      <MenuItem
        icon={isHidden ? <Eye size={13} /> : <EyeOff size={13} />}
        onClick={() => { onHide?.(); onClose?.() }}
      >
        {isHidden ? 'Show' : 'Hide'}
      </MenuItem>

      <MenuItem icon={<Focus size={13} />} onClick={() => { onIsolate?.(); onClose?.() }}>
        Isolate (hide others)
      </MenuItem>

      <MenuItem icon={<Layers size={13} />} onClick={() => { onShowAll?.(); onClose?.() }}>
        Show all
      </MenuItem>

      <div className="my-1 border-t border-ink-800" />

      {/* Colour — native picker, disabled for read-only STEP files. */}
      <MenuItem
        icon={<Palette size={13} />}
        disabled={isStepFile}
        title={isStepFile ? 'STEP files are read-only' : 'Change colour'}
        onClick={() => {
          if (isStepFile) return
          colorInputRef.current?.click()
        }}
      >
        <span className="flex-1">Change colour…</span>
        <span
          className="w-3 h-3 rounded-sm border border-ink-600 flex-shrink-0"
          style={{ backgroundColor: colorHex }}
        />
      </MenuItem>
      <input
        ref={colorInputRef}
        type="color"
        defaultValue={colorHex}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => {
          onRecolor?.(hexToRgb(e.target.value))
          onClose?.()
        }}
        className="absolute opacity-0 w-0 h-0 pointer-events-none"
      />

      {/* Transparency — inline slider + presets. */}
      <div className="px-3 pt-2 pb-1">
        <div className="flex items-center gap-2 mb-1.5 text-ink-200">
          <Droplet size={13} className="text-ink-400" />
          <span className="flex-1">Transparency</span>
          <span className="font-mono text-[10px] text-ink-400">{100 - pct}%</span>
        </div>
        <input
          type="range"
          min={0}
          max={100}
          step={5}
          // Slider tracks opacity (left = more transparent) so it reads
          // naturally; the label shows transparency = 100 - opacity.
          value={pct}
          onChange={(e) => onSetOpacity?.(Number(e.target.value) / 100)}
          className="w-full accent-kerf-300 cursor-pointer"
          aria-label="Opacity"
        />
        <div className="flex gap-1 mt-1.5">
          {OPACITY_PRESETS.map((p) => (
            <button
              key={p.label}
              type="button"
              onClick={() => onSetOpacity?.(p.value)}
              className={`flex-1 px-1 py-0.5 rounded-sm text-[10px] border transition-colors ${
                pct === Math.round(p.value * 100)
                  ? 'border-kerf-300 text-kerf-200 bg-kerf-300/10'
                  : 'border-ink-700 text-ink-300 hover:border-kerf-300 hover:text-kerf-300'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

function MenuItem({ icon, children, onClick, disabled = false, title }) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`w-full text-left px-3 py-1.5 flex items-center gap-2 transition-colors ${
        disabled
          ? 'text-ink-600 cursor-not-allowed'
          : 'hover:bg-ink-800 hover:text-kerf-300'
      }`}
    >
      <span className="flex-shrink-0 text-ink-400">{icon}</span>
      {children}
    </button>
  )
}
