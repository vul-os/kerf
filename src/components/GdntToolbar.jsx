// GdntToolbar.jsx — ISO 1101 / ASME Y14.5 GD&T annotation toolbar.
//
// Renders a compact floating column of tool buttons for every GD&T
// characteristic defined in ISO 1101:2017 + datum placement. Companion to
// DrawingToolbar (2D) and the 3D PMI overlay (Pmi3DOverlay).
//
// Props:
//   tool          — currently active tool id (string)
//   onTool        — callback(toolId) when a button is pressed
//   activeDatums  — set/array of datum labels already placed (for visual state)
//
// Tool ids follow the pattern:
//   'gdt:datum:A', 'gdt:datum:B', 'gdt:datum:C',
//   'gdt:fcf:position', 'gdt:fcf:perpendicularity', etc.

import { useState, useEffect, useRef } from 'react'
import { GDT_SYMBOLS, GDT_SYMBOL_MAP, DATUM_LABELS } from '../lib/gdntAnnotations.js'

// Icon map — use Unicode symbols to avoid needing custom SVGs. Each symbol
// comes from the ISO 1101 character set already in kerf-gdnt symbols.py.
const SYMBOL_UNICODE = Object.fromEntries(GDT_SYMBOLS.map((s) => [s.code, s.unicode]))

// Group definitions for the toolbar layout.
const GROUPS = [
  {
    label: 'Datum',
    items: DATUM_LABELS.slice(0, 3).map((l) => ({
      id: `gdt:datum:${l}`,
      label: `Datum ${l}`,
      display: l,
      mono: true,
      datumLabel: l,
    })),
  },
  {
    label: 'Form',
    items: GDT_SYMBOLS.filter((s) => s.category === 'form').map((s) => ({
      id: `gdt:fcf:${s.code}`,
      label: s.name,
      display: s.unicode,
      mono: false,
    })),
  },
  {
    label: 'Profile',
    items: GDT_SYMBOLS.filter((s) => s.category === 'profile').map((s) => ({
      id: `gdt:fcf:${s.code}`,
      label: s.name,
      display: s.unicode,
      mono: false,
    })),
  },
  {
    label: 'Orientation',
    items: GDT_SYMBOLS.filter((s) => s.category === 'orientation').map((s) => ({
      id: `gdt:fcf:${s.code}`,
      label: s.name,
      display: s.unicode,
      mono: false,
    })),
  },
  {
    label: 'Location',
    items: GDT_SYMBOLS.filter((s) => s.category === 'location').map((s) => ({
      id: `gdt:fcf:${s.code}`,
      label: s.name,
      display: s.unicode,
      mono: false,
    })),
  },
  {
    label: 'Runout',
    items: GDT_SYMBOLS.filter((s) => s.category === 'runout').map((s) => ({
      id: `gdt:fcf:${s.code}`,
      label: s.name,
      display: s.unicode,
      mono: false,
    })),
  },
]

export default function GdntToolbar({ tool = '', onTool }) {
  return (
    <div
      className="absolute top-3 right-3 z-10 flex flex-col gap-1 p-1 rounded-md bg-ink-900/85 border border-ink-700 backdrop-blur shadow-lg"
      role="toolbar"
      aria-label="GD&T annotation tools (ISO 1101)"
      data-testid="gdnt-toolbar"
    >
      {/* Section header */}
      <div className="px-1 pt-0.5 pb-1 text-[9px] uppercase tracking-wider font-semibold text-ink-500 select-none">
        GD&T
      </div>

      {GROUPS.map((group, gi) => (
        <div key={gi} className="flex flex-col gap-0.5">
          {gi > 0 && <div className="h-px bg-ink-700/70 mx-0.5 my-0.5" />}
          {/* Category label */}
          <div className="px-1 text-[8px] uppercase tracking-wider text-ink-600 select-none leading-none mb-0.5">
            {group.label}
          </div>
          {group.items.map(({ id, label, display, mono }) => {
            const active = id === tool
            return (
              <button
                key={id}
                type="button"
                title={label}
                aria-label={label}
                aria-pressed={active}
                data-testid={`gdnt-tool-${id}`}
                onClick={() => onTool?.(id)}
                className={`w-8 h-7 rounded transition-colors flex items-center justify-center text-[13px] leading-none ${
                  active
                    ? 'bg-kerf-300 text-ink-950'
                    : 'bg-ink-900/60 text-ink-300 hover:text-kerf-300 hover:bg-ink-800 border border-ink-700/50'
                } ${mono ? 'font-bold font-mono' : ''}`}
              >
                {display}
              </button>
            )
          })}
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// FcfPlacementModal — shown when the user clicks in the viewport after
// selecting a gdt:fcf:* tool. Lets them enter tolerance value, modifiers and
// datum references before the FCF is committed.
//
// Props:
//   symbolCode    — e.g. 'perpendicularity'
//   position      — {x, y} anchor in page-mm
//   onCommit(opts) — called with the full FCF options when user confirms
//   onCancel()    — called when ESC / Cancel pressed
//
// Rendered as an absolutely-positioned popover over the drawing canvas.

export function FcfPlacementModal({ symbolCode, position, onCommit, onCancel }) {
  const sym = GDT_SYMBOL_MAP[symbolCode]
  const [toleranceValue, setToleranceValue] = useState('0.1')
  const [diameterZone, setDiameterZone] = useState(false)
  const [toleranceMod, setToleranceMod] = useState('')
  const [datumA, setDatumA] = useState('')
  const [datumB, setDatumB] = useState('')
  const [datumC, setDatumC] = useState('')
  const inputRef = useRef(null)

  useEffect(() => {
    inputRef.current?.select()
  }, [])

  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape') onCancel?.()
      if (e.key === 'Enter') handleCommit()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  function handleCommit() {
    const tol = parseFloat(toleranceValue)
    if (!Number.isFinite(tol) || tol < 0) return
    const datumRefs = [
      datumA ? { label: datumA, modifier: null } : null,
      datumB ? { label: datumB, modifier: null } : null,
      datumC ? { label: datumC, modifier: null } : null,
    ].filter(Boolean)
    onCommit?.({
      x: position.x,
      y: position.y,
      symbol_code: symbolCode,
      tolerance_value: tol,
      diameter_zone: diameterZone,
      tolerance_modifier: toleranceMod || null,
      datum_refs: datumRefs,
    })
  }

  if (!sym) return null

  // Preview text
  const diaStr = diameterZone ? '⌀' : ''
  const modMap = { M: 'Ⓜ', L: 'Ⓛ', S: 'Ⓢ', F: 'Ⓕ', P: 'Ⓟ', T: 'Ⓣ' }
  const modStr = toleranceMod ? ` ${modMap[toleranceMod] || toleranceMod}` : ''
  const datumsStr = [datumA, datumB, datumC].filter(Boolean).map((d) => `⏐${d}`).join('') + ([datumA, datumB, datumC].filter(Boolean).length ? '⏐' : '')
  const preview = `⏐${sym.unicode}⏐${diaStr}${toleranceValue || '?'}${modStr}${datumsStr}`

  return (
    <div
      className="absolute z-50 w-72 rounded-lg border border-ink-700 bg-ink-900 shadow-2xl shadow-black/60 overflow-hidden"
      style={{ left: 16, top: 16 }}
      data-testid="fcf-placement-modal"
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-ink-800">
        <span className="text-[18px] leading-none">{sym.unicode}</span>
        <div className="flex-1 min-w-0">
          <div className="text-[12px] font-semibold text-ink-100">{sym.name}</div>
          <div className="text-[10px] text-ink-500 font-mono">{sym.category}</div>
        </div>
      </div>

      {/* FCF preview */}
      <div className="px-3 py-2 border-b border-ink-800 bg-ink-950">
        <div className="text-[11px] text-ink-500 uppercase tracking-wider mb-1">Preview</div>
        <div className="font-mono text-kerf-300 text-[13px] tracking-wide">{preview}</div>
      </div>

      {/* Fields */}
      <div className="px-3 py-2 flex flex-col gap-2">
        {/* Tolerance */}
        <div className="flex items-center gap-2">
          <label className="text-[11px] text-ink-400 w-20 shrink-0">Tolerance</label>
          <div className="flex items-center gap-1 flex-1">
            <button
              type="button"
              title="Diameter zone (cylindrical)"
              onClick={() => setDiameterZone((v) => !v)}
              className={`w-6 h-6 rounded text-[11px] font-mono shrink-0 border ${
                diameterZone
                  ? 'bg-kerf-300 text-ink-950 border-kerf-300'
                  : 'bg-ink-800 text-ink-400 border-ink-700 hover:text-kerf-300'
              }`}
            >⌀</button>
            <input
              ref={inputRef}
              type="number"
              min="0"
              step="0.01"
              value={toleranceValue}
              onChange={(e) => setToleranceValue(e.target.value)}
              className="flex-1 min-w-0 h-6 px-2 rounded bg-ink-800 border border-ink-700 text-[11px] font-mono text-ink-200 focus:ring-1 focus:ring-kerf-300 focus:outline-none"
              placeholder="0.1"
            />
          </div>
        </div>

        {/* Material condition modifier */}
        <div className="flex items-center gap-2">
          <label className="text-[11px] text-ink-400 w-20 shrink-0">Modifier</label>
          <div className="flex gap-1 flex-wrap">
            {[
              { code: '', label: 'None' },
              { code: 'M', label: 'Ⓜ MMC' },
              { code: 'L', label: 'Ⓛ LMC' },
              { code: 'S', label: 'Ⓢ RFS' },
              { code: 'P', label: 'Ⓟ Proj' },
            ].map(({ code, label }) => (
              <button
                key={code}
                type="button"
                title={label}
                onClick={() => setToleranceMod(code)}
                className={`h-5 px-1.5 rounded text-[10px] font-mono border transition-colors ${
                  toleranceMod === code
                    ? 'bg-kerf-300 text-ink-950 border-kerf-300'
                    : 'bg-ink-800 text-ink-400 border-ink-700 hover:text-kerf-300'
                }`}
              >{code || '—'}</button>
            ))}
          </div>
        </div>

        {/* Datum references */}
        <div className="flex items-center gap-2">
          <label className="text-[11px] text-ink-400 w-20 shrink-0">Datums</label>
          <div className="flex gap-1">
            {[
              { val: datumA, set: setDatumA, ph: 'A' },
              { val: datumB, set: setDatumB, ph: 'B' },
              { val: datumC, set: setDatumC, ph: 'C' },
            ].map(({ val, set, ph }) => (
              <input
                key={ph}
                type="text"
                maxLength={3}
                value={val}
                onChange={(e) => set(e.target.value.toUpperCase())}
                placeholder={ph}
                className="w-10 h-6 px-1 rounded bg-ink-800 border border-ink-700 text-[11px] font-mono text-ink-200 text-center focus:ring-1 focus:ring-kerf-300 focus:outline-none"
                aria-label={`Datum ${ph}`}
              />
            ))}
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="flex gap-2 px-3 py-2 border-t border-ink-800">
        <button
          type="button"
          onClick={handleCommit}
          className="flex-1 h-7 rounded bg-kerf-300 text-ink-950 text-[11px] font-semibold hover:bg-kerf-200 transition-colors"
        >
          Place FCF
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="h-7 px-3 rounded bg-ink-800 text-ink-400 text-[11px] hover:text-ink-200 border border-ink-700 transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}
