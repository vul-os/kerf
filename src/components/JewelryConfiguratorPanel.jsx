/**
 * JewelryConfiguratorPanel — multi-tab jewelry configurator.
 *
 * Tabs:
 *   1. Gem Picker   — cut + material + carat/mm sizing with GIA ideal proportions
 *   2. Ring Sizer   — multi-system ring size conversion + band volume/weight estimate
 *   3. Setting      — prong / bezel / pavé geometry guide
 *
 * All math is pure-JS (no API calls) via src/lib/jewelryConfig.js.
 * Designed as a sidebar panel alongside the 3D viewport.
 */

import { useState, useMemo } from 'react'
import { Gem, Circle, Settings2, ChevronDown, ChevronUp, Info } from 'lucide-react'

import {
  caratFromMm,
  mmFromCarat,
  ringSizeToDiameter,
  ringDiameterToSize,
  metalWeight,
  castingWeight,
  computeProngParams,
  computeBezelParams,
  computePaveLayout,
  ringBandVolume,
  idealProportions,
  GEM_CATALOG,
  CUT_CATALOG,
  METAL_DENSITY,
  METAL_HALLMARK,
} from '../lib/jewelryConfig.js'

// ---------------------------------------------------------------------------
// Shared constants
// ---------------------------------------------------------------------------

const METAL_OPTIONS = Object.keys(METAL_DENSITY).map((key) => {
  const label = key
    .replace(/_/g, ' ')
    .replace(/(\d+k)/i, '$1')
    .replace(/\b\w/g, (c) => c.toUpperCase())
  return { key, label }
})

const RING_SYSTEMS = [
  { key: 'US', label: 'US',    placeholder: '7' },
  { key: 'UK', label: 'UK/AU', placeholder: 'N' },
  { key: 'EU', label: 'EU',    placeholder: '54' },
  { key: 'JP', label: 'JP',    placeholder: '13' },
]

const SETTING_TYPES = [
  { key: 'prong', label: 'Prong' },
  { key: 'bezel', label: 'Bezel' },
  { key: 'pave',  label: 'Pavé' },
]

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

function fmt(n, decimals = 2) {
  if (n == null || isNaN(n)) return '—'
  return n.toFixed(decimals)
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function TabButton({ active, onClick, icon: Icon, label }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`
        flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium rounded transition-colors
        focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-kerf-300
        ${active
          ? 'bg-kerf-400/20 text-kerf-300 border border-kerf-400/30'
          : 'text-ink-400 hover:text-ink-200 border border-transparent hover:border-ink-700'}
      `}
    >
      {Icon && <Icon size={12} aria-hidden="true" />}
      {label}
    </button>
  )
}

function SectionHeader({ children }) {
  return (
    <div className="text-[10px] uppercase tracking-wider text-ink-500 mt-3 mb-1.5 border-b border-ink-800 pb-0.5">
      {children}
    </div>
  )
}

function FieldRow({ label, hint, children }) {
  return (
    <div className="flex items-start gap-2 mb-2">
      <label className="text-[11px] text-ink-400 w-28 flex-shrink-0 pt-1.5 leading-tight">
        {label}
        {hint && <span className="block text-[10px] text-ink-600 leading-tight">{hint}</span>}
      </label>
      <div className="flex-1 min-w-0">{children}</div>
    </div>
  )
}

function ValRow({ label, value, unit, accent }) {
  return (
    <div className="flex items-center justify-between py-1 border-b border-ink-800/50 last:border-0">
      <span className="text-[11px] text-ink-400">{label}</span>
      <span className={`font-mono tabular-nums text-[11px] ${accent ? 'text-kerf-300 font-semibold' : 'text-ink-200'}`}>
        {value}{unit ? <span className="text-ink-500 ml-0.5">{unit}</span> : null}
      </span>
    </div>
  )
}

const inputCls = [
  'w-full h-8 bg-ink-900 border border-ink-800 rounded px-2 py-1 text-xs text-ink-100',
  'focus:outline-none focus:border-kerf-300 focus-visible:ring-1 focus-visible:ring-kerf-300',
  '[appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none',
].join(' ')

const selectCls = [
  'w-full h-8 bg-ink-900 border border-ink-800 rounded px-2 py-1 text-xs text-ink-100',
  'focus:outline-none focus:border-kerf-300 focus-visible:ring-1 focus-visible:ring-kerf-300',
].join(' ')

// ---------------------------------------------------------------------------
// Tab 1 — Gem Picker
// ---------------------------------------------------------------------------

function GemPickerTab() {
  const [cut, setCut]           = useState('round_brilliant')
  const [gemName, setGemName]   = useState('diamond')
  const [inputMode, setInputMode] = useState('mm') // 'mm' | 'carat'
  const [dimMm, setDimMm]       = useState('6.5')
  const [carat, setCarat]       = useState('1.0')
  const [showProportions, setShowProportions] = useState(false)

  const selectedGem = GEM_CATALOG.find(g => g.name === gemName) ?? GEM_CATALOG[0]
  const density = selectedGem ? (
    // GEM_CATALOG entries don't carry density; import from GEM_DENSITIES
    METAL_DENSITY[gemName] ?? null
  ) : null

  // Compute results
  const results = useMemo(() => {
    if (inputMode === 'mm') {
      const d = parseFloat(dimMm)
      if (!(d > 0)) return null
      const ct = caratFromMm(d, cut, gemName)
      return { dimMm: d, carat: ct }
    } else {
      const ct = parseFloat(carat)
      if (!(ct > 0)) return null
      const d = mmFromCarat(ct, cut, gemName)
      return { dimMm: d, carat: ct }
    }
  }, [inputMode, dimMm, carat, cut, gemName])

  const proportions = useMemo(() => idealProportions(cut), [cut])

  return (
    <div className="space-y-1">
      <SectionHeader>Gem Material</SectionHeader>

      <FieldRow label="Species">
        <select
          value={gemName}
          onChange={(e) => setGemName(e.target.value)}
          aria-label="Select gem species"
          className={selectCls}
        >
          {GEM_CATALOG.map((g) => (
            <option key={g.name} value={g.name}>
              {g.label}
            </option>
          ))}
        </select>
        {selectedGem && (
          <div className="flex gap-2 mt-1 text-[10px] text-ink-500 flex-wrap">
            {selectedGem.mohs && (
              <span>Mohs <span className="text-ink-300">{selectedGem.mohs[0]}–{selectedGem.mohs[1]}</span></span>
            )}
            {selectedGem.ri && (
              <span>RI <span className="text-ink-300">{selectedGem.ri[0].toFixed(3)}–{selectedGem.ri[1].toFixed(3)}</span></span>
            )}
            {selectedGem.months && selectedGem.months.length > 0 && (
              <span>Birthstone <span className="text-ink-300">month {selectedGem.months.join(', ')}</span></span>
            )}
          </div>
        )}
      </FieldRow>

      <SectionHeader>Cut</SectionHeader>

      <FieldRow label="Cut style">
        <select
          value={cut}
          onChange={(e) => setCut(e.target.value)}
          aria-label="Select cut style"
          className={selectCls}
        >
          {CUT_CATALOG.map((c) => (
            <option key={c.name} value={c.name}>
              {c.label} — {c.facets} facets
            </option>
          ))}
        </select>
        {(() => {
          const entry = CUT_CATALOG.find(c => c.name === cut)
          return entry ? (
            <div className="mt-1 text-[10px] text-ink-600">{entry.note}</div>
          ) : null
        })()}
      </FieldRow>

      <SectionHeader>Carat ↔ mm Sizing</SectionHeader>

      {/* Input mode toggle */}
      <div className="flex items-center gap-2 mb-2">
        <div
          className="flex rounded overflow-hidden border border-ink-700 text-[10px]"
          role="group"
          aria-label="Size input mode"
        >
          {['mm', 'carat'].map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => setInputMode(mode)}
              aria-pressed={inputMode === mode}
              className={`px-3 py-1 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-kerf-300 transition-colors ${
                inputMode === mode ? 'bg-kerf-400/20 text-kerf-300' : 'text-ink-500 hover:text-ink-300'
              } ${mode === 'carat' ? 'border-l border-ink-700' : ''}`}
            >
              {mode === 'mm' ? 'mm → ct' : 'ct → mm'}
            </button>
          ))}
        </div>
      </div>

      {inputMode === 'mm' ? (
        <FieldRow label="Diameter (mm)" hint="principal dimension">
          <input
            type="number"
            value={dimMm}
            onChange={(e) => setDimMm(e.target.value)}
            placeholder="e.g. 6.5"
            min={0}
            step="any"
            aria-label="Stone diameter in mm"
            className={inputCls}
          />
        </FieldRow>
      ) : (
        <FieldRow label="Weight (ct)">
          <input
            type="number"
            value={carat}
            onChange={(e) => setCarat(e.target.value)}
            placeholder="e.g. 1.0"
            min={0}
            step="any"
            aria-label="Stone weight in carats"
            className={inputCls}
          />
        </FieldRow>
      )}

      {/* Results */}
      {results && (
        <div className="bg-ink-900 rounded-md px-3 py-1 mt-2">
          <ValRow
            label={inputMode === 'mm' ? 'Carat weight' : 'Diameter'}
            value={inputMode === 'mm' ? fmt(results.carat, 3) : fmt(results.dimMm, 2)}
            unit={inputMode === 'mm' ? 'ct' : 'mm'}
            accent
          />
          <ValRow
            label={inputMode === 'mm' ? 'Diameter' : 'Carat weight'}
            value={inputMode === 'mm' ? fmt(results.dimMm, 2) : fmt(results.carat, 3)}
            unit={inputMode === 'mm' ? 'mm' : 'ct'}
          />
          <div className="text-[10px] text-ink-600 py-1">
            Formula: carat = (dim / ref_mm)<sup>3</sup> — GIA/Liddicoat vol. scaling
          </div>
        </div>
      )}

      {/* GIA Ideal Proportions */}
      {proportions && (
        <div className="mt-2">
          <button
            type="button"
            onClick={() => setShowProportions(v => !v)}
            aria-expanded={showProportions}
            className="flex items-center gap-1 text-[11px] text-ink-500 hover:text-ink-300 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-kerf-300 rounded"
          >
            <Info size={11} aria-hidden="true" />
            GIA ideal proportions
            {showProportions ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
          </button>
          {showProportions && (
            <div className="bg-ink-900 rounded-md px-3 py-1 mt-1">
              {proportions.note && (
                <div className="text-[10px] text-ink-600 mb-1">{proportions.note}</div>
              )}
              {proportions.table_pct && (
                <ValRow label="Table %" value={`${proportions.table_pct[0]}–${proportions.table_pct[1]}`} />
              )}
              {proportions.crown_angle_deg && (
                <ValRow label="Crown angle" value={`${proportions.crown_angle_deg[0]}°–${proportions.crown_angle_deg[1]}°`} />
              )}
              {proportions.pavilion_angle_deg && (
                <ValRow label="Pavilion angle" value={`${proportions.pavilion_angle_deg[0]}°–${proportions.pavilion_angle_deg[1]}°`} />
              )}
              {proportions.total_depth_pct && (
                <ValRow label="Total depth %" value={`${proportions.total_depth_pct[0]}–${proportions.total_depth_pct[1]}`} />
              )}
              {proportions.length_width_ratio && (
                <ValRow label="L:W ratio" value={`${proportions.length_width_ratio[0]}–${proportions.length_width_ratio[1]}`} />
              )}
              {proportions.step_rows && (
                <ValRow label="Step rows" value={`${proportions.step_rows[0]}`} />
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab 2 — Ring Sizer
// ---------------------------------------------------------------------------

function RingSizerTab() {
  const [activeSystem, setActiveSystem] = useState('US')
  const [sizeInput, setSizeInput]       = useState('7')
  const [sizeError, setSizeError]       = useState(null)
  const [metal, setMetal]               = useState('18k_yellow')
  const [bandWidth, setBandWidth]       = useState('4.0')
  const [thickness, setThickness]       = useState('1.5')
  const [allowancePct, setAllowancePct] = useState('15')
  const [showConvertAll, setShowConvertAll] = useState(false)

  // Compute diameter from size input
  const diameter = useMemo(() => {
    try {
      setSizeError(null)
      const sys = activeSystem
      const val = sys === 'US' || sys === 'EU' || sys === 'JP'
        ? parseFloat(sizeInput)
        : sizeInput.trim()
      return ringSizeToDiameter(sys, val)
    } catch (e) {
      setSizeError(e.message)
      return null
    }
  }, [activeSystem, sizeInput])

  // Compute weight from band params + diameter
  const weight = useMemo(() => {
    if (!diameter) return null
    const bw = parseFloat(bandWidth)
    const t  = parseFloat(thickness)
    const ap = parseFloat(allowancePct) || 15
    if (!(bw > 0) || !(t > 0)) return null
    const vol = ringBandVolume(diameter, bw, t)
    return castingWeight(vol, metal, ap)
  }, [diameter, bandWidth, thickness, metal, allowancePct])

  // Cross-system conversions
  const conversions = useMemo(() => {
    if (!diameter) return []
    return RING_SYSTEMS.map(sys => {
      try {
        const s = ringDiameterToSize(sys.key, diameter)
        return { ...sys, size: s }
      } catch {
        return { ...sys, size: null }
      }
    })
  }, [diameter])

  const placeholder = RING_SYSTEMS.find(s => s.key === activeSystem)?.placeholder ?? ''

  return (
    <div className="space-y-1">
      <SectionHeader>Ring Size System</SectionHeader>

      {/* System selector */}
      <div
        className="flex gap-1 flex-wrap mb-2"
        role="group"
        aria-label="Ring size system"
      >
        {RING_SYSTEMS.map(sys => (
          <button
            key={sys.key}
            type="button"
            onClick={() => { setActiveSystem(sys.key); setSizeInput(sys.placeholder) }}
            aria-pressed={activeSystem === sys.key}
            className={`px-2.5 py-1 rounded text-[11px] border focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-kerf-300 transition-colors ${
              activeSystem === sys.key
                ? 'bg-kerf-400/20 text-kerf-300 border-kerf-400/30'
                : 'text-ink-400 border-ink-700 hover:text-ink-200 hover:border-ink-600'
            }`}
          >
            {sys.label}
          </button>
        ))}
      </div>

      <FieldRow label={`${RING_SYSTEMS.find(s => s.key === activeSystem)?.label} size`}>
        <input
          type={activeSystem === 'UK' || activeSystem === 'AU' ? 'text' : 'number'}
          value={sizeInput}
          onChange={(e) => setSizeInput(e.target.value)}
          placeholder={placeholder}
          min={0}
          step={activeSystem === 'US' ? 0.5 : 1}
          aria-label={`Ring size in ${activeSystem} system`}
          className={inputCls}
        />
      </FieldRow>

      {sizeError && (
        <div className="text-[11px] text-amber-400 px-1 pb-1">{sizeError}</div>
      )}

      {diameter && (
        <>
          <div className="bg-ink-900 rounded-md px-3 py-1 mt-1">
            <ValRow label="Inner diameter" value={fmt(diameter)} unit="mm" accent />
            <ValRow label="Circumference"  value={fmt(Math.PI * diameter)} unit="mm" />
          </div>

          {/* Cross-system conversions */}
          <div className="mt-2">
            <button
              type="button"
              onClick={() => setShowConvertAll(v => !v)}
              aria-expanded={showConvertAll}
              className="flex items-center gap-1 text-[11px] text-ink-500 hover:text-ink-300 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-kerf-300 rounded"
            >
              Cross-system sizes
              {showConvertAll ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
            </button>
            {showConvertAll && (
              <div className="bg-ink-900 rounded-md px-3 py-1 mt-1">
                {conversions.map(c => (
                  <ValRow
                    key={c.key}
                    label={c.label}
                    value={c.size == null ? '—' : String(c.size)}
                  />
                ))}
              </div>
            )}
          </div>
        </>
      )}

      <SectionHeader>Band Weight Estimate</SectionHeader>

      <FieldRow label="Metal">
        <select
          value={metal}
          onChange={(e) => setMetal(e.target.value)}
          aria-label="Select metal"
          className={selectCls}
        >
          {METAL_OPTIONS.map(m => (
            <option key={m.key} value={m.key}>{m.label}</option>
          ))}
        </select>
        {METAL_HALLMARK[metal] != null && (
          <div className="mt-0.5 text-[10px] text-ink-600">
            Hallmark {METAL_HALLMARK[metal]} · {METAL_DENSITY[metal]} g/cm³
          </div>
        )}
      </FieldRow>

      <div className="grid grid-cols-2 gap-x-3">
        <FieldRow label="Width (mm)">
          <input
            type="number"
            value={bandWidth}
            onChange={(e) => setBandWidth(e.target.value)}
            placeholder="4.0"
            min={0}
            step="any"
            aria-label="Band width in mm"
            className={inputCls}
          />
        </FieldRow>
        <FieldRow label="Wall (mm)">
          <input
            type="number"
            value={thickness}
            onChange={(e) => setThickness(e.target.value)}
            placeholder="1.5"
            min={0}
            step="any"
            aria-label="Band wall thickness in mm"
            className={inputCls}
          />
        </FieldRow>
      </div>

      <FieldRow label="Cast allow. %">
        <input
          type="number"
          value={allowancePct}
          onChange={(e) => setAllowancePct(e.target.value)}
          placeholder="15"
          min={0}
          step="any"
          aria-label="Casting allowance percentage"
          className={inputCls}
        />
      </FieldRow>

      {weight && (
        <div className="bg-ink-900 rounded-md px-3 py-1 mt-1">
          <div className="text-[10px] text-ink-600 pb-1">
            Pappus approximation — rectangular cross-section
          </div>
          <ValRow label="Net weight"    value={fmt(weight.netGrams, 3)}   unit="g"   accent />
          <ValRow label="Net weight"    value={fmt(weight.netDwt, 3)}     unit="dwt" />
          <ValRow label="Net weight"    value={fmt(weight.netOzt, 4)}     unit="ozt" />
          <ValRow label={`Gross (+${allowancePct}%)`} value={fmt(weight.grossGrams, 3)} unit="g" />
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab 3 — Setting Builder
// ---------------------------------------------------------------------------

function SettingBuilderTab() {
  const [settingType, setSettingType] = useState('prong')
  const [stoneDiam, setStoneDiam]     = useState('6.5')
  const [stoneDepth, setStoneDepth]   = useState('')
  const [prongCount, setProngCount]   = useState('4')
  const [wallRatio, setWallRatio]     = useState('0.10')
  const [bandLength, setBandLength]   = useState('30.0')
  const [rowCount, setRowCount]       = useState('1')

  const diam = parseFloat(stoneDiam) || 0
  const depth = parseFloat(stoneDepth) || undefined
  const pc    = parseInt(prongCount, 10) || 4
  const wr    = parseFloat(wallRatio) || 0.10
  const bl    = parseFloat(bandLength) || 0
  const rc    = parseInt(rowCount, 10) || 1

  const prongResult = useMemo(() => {
    if (settingType !== 'prong' || !(diam > 0)) return null
    try { return computeProngParams(diam, pc) } catch { return null }
  }, [settingType, diam, pc])

  const bezelResult = useMemo(() => {
    if (settingType !== 'bezel' || !(diam > 0)) return null
    try { return computeBezelParams(diam, depth, wr) } catch { return null }
  }, [settingType, diam, depth, wr])

  const paveResult = useMemo(() => {
    if (settingType !== 'pave' || !(diam > 0) || !(bl > 0)) return null
    try { return computePaveLayout(diam, bl, rc) } catch { return null }
  }, [settingType, diam, bl, rc])

  return (
    <div className="space-y-1">
      <SectionHeader>Setting Type</SectionHeader>

      <div
        className="flex gap-1 mb-2"
        role="group"
        aria-label="Setting type"
      >
        {SETTING_TYPES.map(st => (
          <button
            key={st.key}
            type="button"
            onClick={() => setSettingType(st.key)}
            aria-pressed={settingType === st.key}
            className={`px-3 py-1 rounded text-[11px] border focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-kerf-300 transition-colors ${
              settingType === st.key
                ? 'bg-kerf-400/20 text-kerf-300 border-kerf-400/30'
                : 'text-ink-400 border-ink-700 hover:text-ink-200 hover:border-ink-600'
            }`}
          >
            {st.label}
          </button>
        ))}
      </div>

      <SectionHeader>Stone Size</SectionHeader>

      <FieldRow label="Diameter (mm)" hint="girdle diameter">
        <input
          type="number"
          value={stoneDiam}
          onChange={(e) => setStoneDiam(e.target.value)}
          placeholder="6.5"
          min={0}
          step="any"
          aria-label="Stone girdle diameter in mm"
          className={inputCls}
        />
      </FieldRow>

      {/* Prong-specific inputs */}
      {settingType === 'prong' && (
        <>
          <SectionHeader>Prong Options</SectionHeader>
          <FieldRow label="Prong count" hint="3–6 typical">
            <input
              type="number"
              value={prongCount}
              onChange={(e) => setProngCount(e.target.value)}
              placeholder="4"
              min={3}
              max={8}
              step={1}
              aria-label="Number of prongs"
              className={inputCls}
            />
          </FieldRow>
          {prongResult && (
            <>
              <SectionHeader>Prong Geometry</SectionHeader>
              <div className="bg-ink-900 rounded-md px-3 py-1">
                <div className="text-[10px] text-ink-600 pb-1">
                  GIA / Blaine Lewis ratios — prong_d = 18%, prong_h = 40% of stone
                </div>
                <ValRow label="Prong diameter"    value={fmt(prongResult.prong_diameter_mm)}  unit="mm" accent />
                <ValRow label="Prong height"       value={fmt(prongResult.prong_height_mm)}    unit="mm" />
                <ValRow label="Prong count"        value={prongResult.prong_count} />
                <ValRow label="Seat depth"         value={fmt(prongResult.seat_depth_mm)}      unit="mm" />
                <ValRow label="Girdle clearance"   value={fmt(prongResult.girdle_clearance_mm)} unit="mm" />
              </div>
            </>
          )}
        </>
      )}

      {/* Bezel-specific inputs */}
      {settingType === 'bezel' && (
        <>
          <SectionHeader>Bezel Options</SectionHeader>
          <FieldRow label="Stone depth (mm)" hint="blank = auto (61% of diam)">
            <input
              type="number"
              value={stoneDepth}
              onChange={(e) => setStoneDepth(e.target.value)}
              placeholder="auto"
              min={0}
              step="any"
              aria-label="Stone depth in mm (optional)"
              className={inputCls}
            />
          </FieldRow>
          <FieldRow label="Wall ratio" hint="0.08–0.12 typical">
            <input
              type="number"
              value={wallRatio}
              onChange={(e) => setWallRatio(e.target.value)}
              placeholder="0.10"
              min={0.05}
              max={0.25}
              step="0.01"
              aria-label="Bezel wall thickness ratio"
              className={inputCls}
            />
          </FieldRow>
          {bezelResult && (
            <>
              <SectionHeader>Bezel Geometry</SectionHeader>
              <div className="bg-ink-900 rounded-md px-3 py-1">
                <div className="text-[10px] text-ink-600 pb-1">
                  GIA Stone Setting I (2020) — wall = {(wr * 100).toFixed(0)}% of stone
                </div>
                <ValRow label="Bezel wall"         value={fmt(bezelResult.bezel_wall_mm)}           unit="mm" accent />
                <ValRow label="Inner diameter"     value={fmt(bezelResult.bezel_inner_diameter_mm)}  unit="mm" />
                <ValRow label="Outer diameter"     value={fmt(bezelResult.bezel_outer_diameter_mm)}  unit="mm" />
                <ValRow label="Bezel height"       value={fmt(bezelResult.bezel_height_mm)}          unit="mm" />
                <ValRow label="Seat depth"         value={fmt(bezelResult.seat_depth_mm)}            unit="mm" />
              </div>
            </>
          )}
        </>
      )}

      {/* Pavé-specific inputs */}
      {settingType === 'pave' && (
        <>
          <SectionHeader>Pavé Options</SectionHeader>
          <FieldRow label="Band length (mm)">
            <input
              type="number"
              value={bandLength}
              onChange={(e) => setBandLength(e.target.value)}
              placeholder="30.0"
              min={0}
              step="any"
              aria-label="Pavé band length in mm"
              className={inputCls}
            />
          </FieldRow>
          <FieldRow label="Row count">
            <input
              type="number"
              value={rowCount}
              onChange={(e) => setRowCount(e.target.value)}
              placeholder="1"
              min={1}
              max={5}
              step={1}
              aria-label="Number of stone rows"
              className={inputCls}
            />
          </FieldRow>
          {paveResult && (
            <>
              <SectionHeader>Pavé Layout</SectionHeader>
              <div className="bg-ink-900 rounded-md px-3 py-1">
                <div className="text-[10px] text-ink-600 pb-1">
                  GIA Stone Setting I — 5% gap (spacing = 1.05 × stone)
                </div>
                <ValRow label="Stone count"      value={paveResult.stone_count}                          accent />
                <ValRow label="Stones / row"     value={paveResult.stones_per_row} />
                <ValRow label="Stone spacing"    value={fmt(paveResult.stone_spacing_mm)}    unit="mm" />
                <ValRow label="Bead diameter"    value={fmt(paveResult.bead_diameter_mm)}    unit="mm" />
                <ValRow label="Drill depth"      value={fmt(paveResult.drill_depth_mm)}      unit="mm" />
                <ValRow label="Row count"        value={paveResult.row_count} />
                <ValRow label="Strip width"      value={fmt(paveResult.total_strip_width_mm)} unit="mm" />
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

const TABS = [
  { key: 'gem',     label: 'Gem Picker',  icon: Gem },
  { key: 'ring',    label: 'Ring Sizer',  icon: Circle },
  { key: 'setting', label: 'Setting',     icon: Settings2 },
]

export default function JewelryConfiguratorPanel({ onClose, content }) {
  // Parse content string (from panelRegistry) to seed defaults (not yet used but accepted for compat)
  // eslint-disable-next-line no-unused-vars
  const _defaults = (() => { try { return content ? JSON.parse(content) : {} } catch { return {} } })()
  const [activeTab, setActiveTab] = useState('gem')

  return (
    <div
      role="region"
      aria-label="Jewelry configurator"
      className="h-full flex flex-col min-h-0 bg-ink-950 text-ink-100"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-ink-800 flex-shrink-0">
        <div className="flex items-center gap-2">
          <Gem size={14} className="text-kerf-300" aria-hidden="true" />
          <span className="text-xs font-semibold uppercase tracking-wider text-ink-300">
            Jewelry Configurator
          </span>
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Close configurator"
            className="text-[11px] text-ink-400 hover:text-ink-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-kerf-300 rounded"
          >
            Close
          </button>
        )}
      </div>

      {/* Tab bar */}
      <div className="flex items-center gap-1 px-3 py-2 border-b border-ink-800 flex-shrink-0 flex-wrap">
        {TABS.map(tab => (
          <TabButton
            key={tab.key}
            active={activeTab === tab.key}
            onClick={() => setActiveTab(tab.key)}
            icon={tab.icon}
            label={tab.label}
          />
        ))}
      </div>

      {/* Body */}
      <div className="flex-1 overflow-auto min-h-0 px-4 py-3">
        {activeTab === 'gem'     && <GemPickerTab />}
        {activeTab === 'ring'    && <RingSizerTab />}
        {activeTab === 'setting' && <SettingBuilderTab />}
      </div>
    </div>
  )
}
