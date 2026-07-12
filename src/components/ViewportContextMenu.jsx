// ViewportContextMenu — right-click menu for an object in the 3D viewport.
//
// Modelled on the SolidWorks body / Fusion browser context menus: visibility
// first (the thing people reach for most), then appearance (opacity, colour,
// material), then the destructive/utility actions.
//
// Appearance edits are dispatched as PATCHES: a field set to null clears it, so
// "Default" on the colour submenu is `{ color: null }` and drops back to the
// renderer's palette colour rather than baking one in.
//
// Rendered at fixed screen coords (like FileTree's ContextMenu), flipped when it
// would overflow the window.

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import {
  Eye, EyeOff, Focus, Layers, Droplet, Palette, Boxes, RotateCcw,
  Crosshair, Copy, Trash2, ChevronRight, Check, Download,
} from 'lucide-react'

// Same swatches the renderer cycles through for unstyled parts, so a user can
// always get back to "what it looked like before" by eye.
const SWATCHES = [
  '#c9a96b', '#6b9bc9', '#c96b89', '#89c96b', '#c9b86b', '#9b6bc9',
  '#d94f4f', '#e08b3c', '#e8c547', '#4fa96b', '#3c8be0', '#8e8e93',
  '#f2f2f2', '#1c1c1e',
]

const OPACITY_PRESETS = [
  { label: 'Opaque', value: 1 },
  { label: '75%', value: 0.75 },
  { label: '50%', value: 0.5 },
  { label: '25%', value: 0.25 },
]

const EXPORT_FORMATS = ['stl', 'obj', 'glb']

function Divider() {
  return <div className="my-1 border-t border-ink-700" />
}

function MenuItem({ icon: Icon, label, hint, onClick, disabled, danger }) {
  if (!onClick) return null
  return (
    <button
      type="button"
      role="menuitem"
      disabled={disabled}
      onClick={onClick}
      className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs disabled:opacity-40 disabled:cursor-not-allowed ${
        danger
          ? 'text-red-300 hover:bg-red-500/10'
          : 'text-ink-200 hover:bg-ink-800 hover:text-kerf-300'
      }`}
    >
      {Icon && <Icon size={13} className="shrink-0 opacity-70" />}
      <span className="flex-1 truncate">{label}</span>
      {hint && <span className="text-[10px] text-ink-500">{hint}</span>}
    </button>
  )
}

// A row that reveals a flyout panel to its right on hover. The flyout stays open
// while the pointer is anywhere in the row OR the panel (they share the wrapper),
// which is what makes diagonal travel to the panel work.
function Submenu({ icon: Icon, label, hint, disabled, children }) {
  const [open, setOpen] = useState(false)
  return (
    <div
      className="relative"
      onMouseEnter={() => !disabled && setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        role="menuitem"
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-ink-200 hover:bg-ink-800 hover:text-kerf-300 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {Icon && <Icon size={13} className="shrink-0 opacity-70" />}
        <span className="flex-1 truncate">{label}</span>
        {hint && <span className="text-[10px] text-ink-500">{hint}</span>}
        <ChevronRight size={12} className="shrink-0 opacity-50" />
      </button>
      {open && !disabled && (
        <div
          role="menu"
          className="absolute left-full top-0 z-10 -ml-1 min-w-[168px] rounded-md border border-ink-700 bg-ink-850 py-1 shadow-lg"
        >
          {children}
        </div>
      )}
    </div>
  )
}

export default function ViewportContextMenu({
  x,
  y,
  partId,
  isHidden = false,
  appearance = {},
  materials = [],
  canEdit = true,
  onClose,
  onToggleVisibility,
  onIsolate,
  onShowAll,
  onSetAppearance,
  onResetAppearance,
  onZoomTo,
  onDuplicate,
  onDelete,
  onExport,
}) {
  const ref = useRef(null)
  const colorInputRef = useRef(null)
  const [pos, setPos] = useState({ x, y })

  // Flip the menu back inside the window when it would overflow. Measured after
  // layout so we use the real size rather than guessing at it.
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const { width, height } = el.getBoundingClientRect()
    const margin = 8
    setPos({
      x: x + width + margin > window.innerWidth ? Math.max(margin, x - width) : x,
      y: y + height + margin > window.innerHeight ? Math.max(margin, y - height) : y,
    })
  }, [x, y])

  // Dismiss on an outside press, or Escape.
  //
  // We deliberately do NOT close on `contextmenu`. The event's timing is
  // platform-dependent: Linux/GTK fires it on mouse DOWN, but Windows fires it
  // on mouse UP — i.e. straight after the pointerup that opened this menu. A
  // contextmenu-close listener therefore dismissed the menu in the same gesture
  // that opened it on Windows (it looked like a flicker and no menu at all),
  // while passing fine on Linux.
  //
  // pointerdown-outside covers the dismissal anyway, including right-clicking a
  // different object: that press closes this menu, and the following pointerup
  // opens a fresh one at the new location.
  useEffect(() => {
    const close = (ev) => {
      if (ref.current && ev && ev.target && ref.current.contains(ev.target)) return
      onClose?.()
    }
    const onKey = (ev) => {
      if (ev.key === 'Escape') onClose?.()
    }
    window.addEventListener('pointerdown', close, true)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('pointerdown', close, true)
      window.removeEventListener('keydown', onKey)
    }
  }, [onClose])

  // Every appearance action closes the menu after dispatching — matching the
  // native menus, where picking a value commits and dismisses.
  const dispatch = (patch) => {
    onSetAppearance?.(patch)
    onClose?.()
  }

  const currentOpacity = appearance.opacity == null ? 1 : appearance.opacity
  const currentColor = appearance.color || null
  const currentMaterial = appearance.material || null
  const hasOverrides = Object.keys(appearance || {}).length > 0

  return (
    <div
      ref={ref}
      role="menu"
      aria-label="Object actions"
      data-testid="viewport-context-menu"
      className="fixed z-50 min-w-[196px] rounded-md border border-ink-700 bg-ink-850 py-1 shadow-xl"
      style={{ left: pos.x, top: pos.y }}
      onContextMenu={(e) => {
        e.preventDefault()
        e.stopPropagation()
      }}
    >
      <div className="truncate px-3 pb-1 pt-0.5 font-mono text-[10px] uppercase tracking-wider text-ink-500">
        {partId}
      </div>
      <Divider />

      <MenuItem
        icon={isHidden ? Eye : EyeOff}
        label={isHidden ? 'Show' : 'Hide'}
        onClick={() => {
          onToggleVisibility?.()
          onClose?.()
        }}
      />
      <MenuItem
        icon={Focus}
        label="Isolate"
        hint="hide others"
        onClick={() => {
          onIsolate?.()
          onClose?.()
        }}
      />
      <MenuItem
        icon={Layers}
        label="Show all"
        onClick={() => {
          onShowAll?.()
          onClose?.()
        }}
      />

      <Divider />

      <Submenu
        icon={Droplet}
        label="Opacity"
        hint={currentOpacity === 1 ? '' : `${Math.round(currentOpacity * 100)}%`}
        disabled={!canEdit}
      >
        {OPACITY_PRESETS.map((preset) => (
          <button
            key={preset.value}
            type="button"
            role="menuitemradio"
            aria-checked={currentOpacity === preset.value}
            onClick={() => dispatch({ opacity: preset.value === 1 ? null : preset.value })}
            className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-ink-200 hover:bg-ink-800 hover:text-kerf-300"
          >
            <span className="w-3 shrink-0">
              {currentOpacity === preset.value && <Check size={12} />}
            </span>
            <span className="flex-1">{preset.label}</span>
          </button>
        ))}
        <Divider />
        {/* Committing on change (not input) keeps us to one PATCH per drag. */}
        <div className="px-3 py-1.5">
          <label className="mb-1 block text-[10px] uppercase tracking-wider text-ink-500">
            Custom
          </label>
          <input
            type="range"
            min="5"
            max="100"
            step="5"
            defaultValue={Math.round(currentOpacity * 100)}
            onChange={(e) => {
              const v = Number(e.target.value) / 100
              dispatch({ opacity: v >= 1 ? null : v })
            }}
            className="w-full accent-kerf-300"
          />
        </div>
      </Submenu>

      <Submenu icon={Palette} label="Colour" disabled={!canEdit}>
        <div className="grid grid-cols-7 gap-1 px-2 py-1.5">
          {SWATCHES.map((sw) => (
            <button
              key={sw}
              type="button"
              title={sw}
              aria-label={`Colour ${sw}`}
              onClick={() => dispatch({ color: sw })}
              className={`h-4 w-4 rounded-sm border ${
                currentColor === sw ? 'border-kerf-300' : 'border-ink-700'
              }`}
              style={{ background: sw }}
            />
          ))}
        </div>
        <Divider />
        <MenuItem
          icon={Palette}
          label="Custom…"
          onClick={() => colorInputRef.current?.click()}
        />
        <MenuItem
          icon={RotateCcw}
          label="Default"
          disabled={!currentColor}
          onClick={() => dispatch({ color: null })}
        />
        {/* Native picker, driven by the "Custom…" row above. `change` fires on
            commit (not while dragging), so this is one PATCH per pick. */}
        <input
          ref={colorInputRef}
          type="color"
          className="sr-only"
          aria-label="Custom colour"
          defaultValue={currentColor || '#c9a96b'}
          onChange={(e) => dispatch({ color: e.target.value })}
        />
      </Submenu>

      <Submenu
        icon={Boxes}
        label="Material"
        hint={currentMaterial || ''}
        disabled={!canEdit}
      >
        {materials.length === 0 && (
          <div className="px-3 py-2 text-[11px] leading-snug text-ink-500">
            No .material files in this project yet.
          </div>
        )}
        {materials.map((m) => (
          <button
            key={m.id || m.name}
            type="button"
            role="menuitemradio"
            aria-checked={currentMaterial === m.name}
            onClick={() =>
              // A material carries its own look: apply its colour and PBR values
              // alongside the name, so assigning one is visible immediately.
              dispatch({
                material: m.name,
                color: m.color || null,
                metalness: m.metalness ?? null,
                roughness: m.roughness ?? null,
              })
            }
            className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-ink-200 hover:bg-ink-800 hover:text-kerf-300"
          >
            <span className="w-3 shrink-0">
              {currentMaterial === m.name && <Check size={12} />}
            </span>
            <span
              className="h-3 w-3 shrink-0 rounded-sm border border-ink-700"
              style={{ background: m.color || '#8e8e93' }}
            />
            <span className="flex-1 truncate">{m.name}</span>
          </button>
        ))}
        {currentMaterial && (
          <>
            <Divider />
            <MenuItem
              icon={RotateCcw}
              label="Clear material"
              onClick={() => dispatch({ material: null })}
            />
          </>
        )}
      </Submenu>

      <MenuItem
        icon={RotateCcw}
        label="Reset appearance"
        disabled={!canEdit || !hasOverrides}
        onClick={() => {
          onResetAppearance?.()
          onClose?.()
        }}
      />

      <Divider />

      <MenuItem
        icon={Crosshair}
        label="Zoom to selection"
        onClick={() => {
          onZoomTo?.()
          onClose?.()
        }}
      />
      {onExport && (
        <Submenu icon={Download} label="Export">
          {EXPORT_FORMATS.map((fmt) => (
            <MenuItem
              key={fmt}
              label={fmt.toUpperCase()}
              onClick={() => {
                onExport(fmt)
                onClose?.()
              }}
            />
          ))}
        </Submenu>
      )}

      <Divider />

      <MenuItem
        icon={Copy}
        label="Duplicate"
        disabled={!canEdit}
        onClick={() => {
          onDuplicate?.()
          onClose?.()
        }}
      />
      <MenuItem
        icon={Trash2}
        label="Delete"
        danger
        disabled={!canEdit}
        onClick={() => {
          onDelete?.()
          onClose?.()
        }}
      />
    </div>
  )
}
