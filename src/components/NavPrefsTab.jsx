// NavPrefsTab — bottom-right tab in the viewport for choosing a navigation
// style ("make the mouse behave like the CAD tool I already know").
//
// Collapsed it's a small pill showing the active preset; expanded it lists the
// presets with their actual bindings, so you can see what you're getting without
// trial and error.

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Mouse, Check, ChevronDown } from 'lucide-react'
import { NAV_PRESET_LIST, NAV_PRESETS } from '../lib/navPresets.js'
import { useWorkspace } from '../store/workspace.js'

// The viewport container runs the FULL width of the editor — the chat drawer is
// an overlay on top of it (z-30), not a sibling that shrinks it. So a plain
// `right-3` puts this tab underneath the drawer, invisible and unclickable (the
// renderer's own right-side HUD has the same problem). Inset by the drawer width
// when it's showing. The drawer is `hidden lg:flex`, so below lg there's nothing
// to dodge.
const DRAWER_W = 420
const EDGE = 12

export default function NavPrefsTab({ value, onChange }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  const drawerOpen = useWorkspace((s) => s.rightDrawer?.open)
  const [isLg, setIsLg] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(min-width: 1024px)').matches,
  )
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 1024px)')
    const onChangeMq = () => setIsLg(mq.matches)
    mq.addEventListener('change', onChangeMq)
    return () => mq.removeEventListener('change', onChangeMq)
  }, [])

  const right = drawerOpen && isLg ? DRAWER_W + EDGE : EDGE

  // The panel lists six presets WITH their bindings, so it's ~470 px tall and
  // opens upward — taller than the viewport pane on a laptop, which pushed the
  // first entries off the top of the screen. Cap it to the room actually
  // available above the tab and let it scroll.
  const btnRef = useRef(null)
  const [maxH, setMaxH] = useState(420)
  useLayoutEffect(() => {
    if (!open || !btnRef.current) return
    const r = btnRef.current.getBoundingClientRect()
    setMaxH(Math.max(180, r.top - 16))
  }, [open])

  useEffect(() => {
    if (!open) return
    const close = (ev) => {
      if (ref.current && ev.target && ref.current.contains(ev.target)) return
      setOpen(false)
    }
    const onKey = (ev) => ev.key === 'Escape' && setOpen(false)
    window.addEventListener('pointerdown', close, true)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('pointerdown', close, true)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  const active = NAV_PRESETS[value] || NAV_PRESET_LIST[0]

  return (
    <div
      ref={ref}
      className="absolute bottom-3 z-20"
      style={{ right }}
      data-testid="nav-prefs-tab"
    >
      {open && (
        <div
          role="menu"
          aria-label="Navigation style"
          style={{ maxHeight: maxH }}
          className="mb-2 w-[268px] overflow-y-auto rounded-lg border border-ink-700 bg-ink-850/95 shadow-xl backdrop-blur"
        >
          <div className="sticky top-0 border-b border-ink-700 bg-ink-850/95 px-3 py-2 text-[10px] uppercase tracking-wider text-ink-500 backdrop-blur">
            Navigation style
          </div>
          {NAV_PRESET_LIST.map((preset) => {
            const selected = preset.id === value
            return (
              <button
                key={preset.id}
                type="button"
                role="menuitemradio"
                aria-checked={selected}
                onClick={() => {
                  onChange?.(preset.id)
                  setOpen(false)
                }}
                className={`w-full border-b border-ink-800/60 px-3 py-2 text-left last:border-b-0 hover:bg-ink-800 ${
                  selected ? 'bg-kerf-300/10' : ''
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className="w-3 shrink-0">
                    {selected && <Check size={12} className="text-kerf-300" />}
                  </span>
                  <span
                    className={`flex-1 text-xs font-medium ${
                      selected ? 'text-kerf-300' : 'text-ink-200'
                    }`}
                  >
                    {preset.name}
                  </span>
                  <span className="text-[10px] text-ink-500">{preset.hint}</span>
                </div>
                {/* The bindings, so the choice is legible rather than a guess. */}
                <dl className="mt-1 grid grid-cols-[52px_1fr] gap-x-2 gap-y-0.5 pl-5">
                  {preset.rows.map(([action, binding]) => (
                    <div key={action} className="contents">
                      <dt className="text-[10px] text-ink-500">{action}</dt>
                      <dd className="truncate font-mono text-[10px] text-ink-400">{binding}</dd>
                    </div>
                  ))}
                </dl>
              </button>
            )
          })}
        </div>
      )}

      <button
        ref={btnRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        title="Change navigation style"
        className="ml-auto flex items-center gap-1.5 rounded-md border border-ink-700 bg-ink-900/90 px-2.5 py-1.5 text-[11px] text-ink-300 shadow-lg backdrop-blur hover:border-ink-600 hover:text-kerf-300"
      >
        <Mouse size={13} className="opacity-70" />
        <span className="font-medium">{active.name}</span>
        <ChevronDown
          size={12}
          className={`opacity-60 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>
    </div>
  )
}
