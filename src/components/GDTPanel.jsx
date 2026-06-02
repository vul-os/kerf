// GDTPanel.jsx — /gdt route panel for GD&T metrology tools.
//
// Mirrors the GeometryInspect / GdntInspectionPanel inspector pattern but
// presents all wired GDT LLM tools (ASME Y14.5-2018) as a tool-card grid
// with per-tool parameter editors and a live result pane.
//
// Layout:
//   * top     — header bar with Shield icon + title + MBD toggle
//   * left    — scrollable tool-card grid (9 GDT tools grouped by category)
//               + "Drawing Annotation" section
//               + "Tolerance Stackup Workflow" section
//   * right   — ToolInspector: selected tool description, input fields, Run button
//   * bottom  — Result JSON viewer (pass/fail badge, key metrics)
//
// GDT tools wired (9 total):
//   Runout       — gdt_check_runout, gdt_check_circular_runout, gdt_check_axial_runout
//   Tolerance    — gdt_check_composite_position, gdt_validate_composite_frame,
//                  gdt_validate_datum_reference_frame (gdt_validate_frame)
//   Chains       — gdt_compute_dimension_chain (gdt_check_dimension_chain)
//   Frame        — gdt_apply_datum, gdt_apply_tolerance, gdt_callout_report
//
// Drawing Annotation section wires:
//   gdt_apply_datum, gdt_apply_tolerance, gdt_validate_frame,
//   gdt_validate_composite_frame, gdt_compute_dimension_chain
//
// Calls are dispatched as JSON-RPC to /api/llm/tool (chat tool dispatch).

import { useState } from 'react'
import {
  Shield, ChevronRight, CheckCircle, XCircle, AlertTriangle,
  Ruler, RotateCcw, Layers, Activity, Filter, AlignLeft,
  Play, Loader2, FileText, PlusCircle, Trash2,
  Layout, BarChart2, ChevronDown, ChevronUp,
  ToggleLeft, ToggleRight,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Tool catalogue
// ---------------------------------------------------------------------------

const GDT_TOOLS = [
  // ── Runout ─────────────────────────────────────────────────────────────────
  {
    id: 'gdt_check_runout',
    label: 'Check Runout',
    category: 'runout',
    icon: RotateCcw,
    standard: 'ASME Y14.5-2018 §12.5 / §13',
    description:
      'Check circular or total runout tolerance compliance from a set of radial inspection points ' +
      'measured around a datum axis. Full Indicator Movement (FIM) per cross-section for circular; ' +
      'all-points FIM for total runout.',
    fields: [
      { key: 'feature_id',          label: 'Feature ID',              kind: 'text',   default: 'shaft-A' },
      { key: 'runout_tolerance_mm',  label: 'Tolerance (mm)',          kind: 'number', default: 0.05, min: 0 },
      { key: 'runout_type',          label: 'Type',                    kind: 'select', default: 'circular',
        options: [{ value: 'circular', label: 'Circular' }, { value: 'total', label: 'Total' }] },
      { key: 'nominal_radius_mm',    label: 'Nominal radius (mm)',     kind: 'number', default: 10.0, min: 0.001 },
    ],
  },
  {
    id: 'gdt_check_circular_runout',
    label: 'Check Circular Runout',
    category: 'runout',
    icon: RotateCcw,
    standard: 'ASME Y14.5-2018 §12.4',
    description:
      'Evaluate single-plane circular runout compliance. Input is sections of radial measurements ' +
      '(each inner list = one cross-section). FIM = max(R)−min(R) per section; worst section governs.',
    fields: [
      { key: 'tolerance_mm',  label: 'Tolerance (mm)',  kind: 'number', default: 0.05, min: 0 },
      { key: 'datum_axis_id', label: 'Datum axis ID',   kind: 'text',   default: 'A' },
    ],
  },
  {
    id: 'gdt_check_axial_runout',
    label: 'Check Axial Runout',
    category: 'runout',
    icon: Activity,
    standard: 'ASME Y14.5-2018 §12.5 axial',
    description:
      'Check axial face runout — measures axial Z deviation on a face perpendicular to the datum axis. ' +
      'FIM = max(Z)−min(Z) over all measurement points; pass ⟺ FIM ≤ tolerance.',
    fields: [
      { key: 'tolerance_mm',  label: 'Tolerance (mm)',  kind: 'number', default: 0.05, min: 0 },
      { key: 'datum_axis_id', label: 'Datum axis ID',   kind: 'text',   default: 'A' },
    ],
  },

  // ── Composite / Frame ──────────────────────────────────────────────────────
  {
    id: 'gdt_check_composite_position',
    label: 'Check Composite Position',
    category: 'tolerance',
    icon: Layers,
    standard: 'ASME Y14.5-2018 §10.5',
    description:
      'Evaluate composite positional tolerance (PLTZF/FRTZF two-tier) for a feature pattern against ' +
      'measured 3-D points. Upper frame controls pattern location vs full datum frame; lower frame ' +
      'controls relative inter-feature spacing with optional MMC bonus.',
    fields: [
      { key: 'upper_pltzf_tolerance_mm', label: 'PLTZF tolerance (mm)', kind: 'number', default: 0.5, min: 0 },
      { key: 'lower_frtzf_tolerance_mm', label: 'FRTZF tolerance (mm)', kind: 'number', default: 0.2, min: 0 },
      { key: 'mmc_modifier',             label: 'Apply MMC modifier',   kind: 'boolean', default: false },
    ],
  },
  {
    id: 'gdt_validate_composite_frame',
    label: 'Validate Composite Frame',
    category: 'tolerance',
    icon: Shield,
    standard: 'ASME Y14.5-2018 §10.5.2',
    description:
      'Validate stacked PLTZF/FRTZF composite feature control frames: R1 symbol match, ' +
      'R2 FRTZF ≤ PLTZF tolerance, R3 FRTZF datum refs are a subset of PLTZF datum refs. ' +
      'Structural well-formedness check only — no measurement data required.',
    fields: [
      { key: 'feature_id', label: 'Feature ID', kind: 'text', default: 'pattern-1' },
    ],
  },
  {
    id: 'gdt_validate_frame',
    label: 'Validate GD&T Frame',
    category: 'tolerance',
    icon: Filter,
    standard: 'ASME Y14.5-2018 §3.4 / §6 / §9 / §10 / §12',
    description:
      'Structural well-formedness check for a GD&T feature control frame: symbol-modifier ' +
      'compatibility, datum requirements by tolerance category, duplicate-datum detection, ' +
      'bonus tolerance (MMC/LMC §6.3), and canonical string round-trip.',
    fields: [
      { key: 'fcf_string', label: 'FCF string (e.g. ⊕|⌀0.5|A|B|C)', kind: 'text', default: '|⌀0.5|A|B|C' },
    ],
  },

  // ── Dimension chain ────────────────────────────────────────────────────────
  {
    id: 'gdt_compute_dimension_chain',
    label: 'Dimension Chain Stack-Up',
    category: 'chain',
    icon: Ruler,
    standard: 'ASME Y14.5-2018 §5.3 + Bralla §1',
    description:
      'Compute worst-case (WC) and RSS statistical tolerance stack-up for a linear dimension chain. ' +
      'Returns nominal gap, WC min/max, and RSS min/max (3σ, 99.73%). Identifies the dominant link.',
    fields: [
      { key: 'target_gap_min_mm', label: 'Min acceptable gap (mm)', kind: 'number', default: 0.0 },
      { key: 'target_gap_max_mm', label: 'Max acceptable gap (mm)', kind: 'number', default: 1.0, min: 0 },
    ],
  },

  // ── Datum / callout ────────────────────────────────────────────────────────
  {
    id: 'gdt_apply_datum',
    label: 'Apply Datum',
    category: 'datum',
    icon: AlignLeft,
    standard: 'ASME Y14.5-2018 §4',
    description:
      'Attach a datum reference (A / B / C) to a specified feature in the drawing data model. ' +
      'Creates the datum label node and registers it in the drawing\'s datum registry.',
    fields: [
      { key: 'feature_id',   label: 'Feature ID',   kind: 'text',   default: 'face-0' },
      { key: 'datum_letter', label: 'Datum letter',  kind: 'text',   default: 'A' },
    ],
  },
  {
    id: 'gdt_apply_tolerance',
    label: 'Apply Tolerance',
    category: 'datum',
    icon: FileText,
    standard: 'ASME Y14.5-2018 §6',
    description:
      'Attach a feature control frame (FCF) tolerance to a feature. Validates the FCF string, ' +
      'computes bonus tolerance for MMC/LMC modifiers, and writes the node to the drawing model.',
    fields: [
      { key: 'feature_id',   label: 'Feature ID',   kind: 'text',   default: 'hole-0' },
      { key: 'fcf_string',   label: 'FCF string',   kind: 'text',   default: '|⌀0.2|A|B|C' },
    ],
  },
]

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const CATEGORIES = {
  runout:    { label: 'Runout',           color: 'text-blue-400' },
  tolerance: { label: 'Composite / Frame', color: 'text-kerf-400' },
  chain:     { label: 'Dimension Chain',  color: 'text-amber-400' },
  datum:     { label: 'Datum / Callout',  color: 'text-emerald-400' },
}

// GD&T characteristic symbols (Unicode)
const GDT_SYMBOLS = {
  position:        '⊕',
  flatness:        '⏥',
  straightness:    '⏤',
  roundness:       '○',
  cylindricity:    '⌭',
  perpendicularity:'⊥',
  angularity:      '∠',
  parallelism:     '∥',
  profile_line:    '⌒',
  profile_surface: '⌓',
  runout_circular: '↗',
  runout_total:    '⌿',
  concentricity:   '◎',
  symmetry:        '≡',
}

// FCF SVG renderer — builds a simple feature control frame SVG preview
function FcfSvgPreview({ symbol, toleranceMm, datumA, datumB, datumC, modifier }) {
  const sym = GDT_SYMBOLS[symbol] || symbol || '⊕'
  const modSuffix = modifier === 'mmc' ? 'Ⓜ' : modifier === 'lmc' ? 'Ⓛ' : ''
  const tolStr = toleranceMm != null ? `⌀${Number(toleranceMm).toFixed(3)}${modSuffix}` : '⌀0.000'
  const datums = [datumA, datumB, datumC].filter(Boolean)

  // Each cell is 32px wide, 22px tall
  const cellW = 36
  const cellH = 24
  const cells = [sym, tolStr, ...datums]
  const totalW = cells.length * cellW + 2

  return (
    <svg
      viewBox={`0 0 ${totalW} ${cellH + 2}`}
      width={totalW}
      height={cellH + 2}
      className="block"
      style={{ fontFamily: 'monospace' }}
    >
      {cells.map((text, i) => (
        <g key={i}>
          <rect
            x={1 + i * cellW}
            y={1}
            width={cellW}
            height={cellH}
            fill="none"
            stroke="#4ade80"
            strokeWidth="0.8"
          />
          <text
            x={1 + i * cellW + cellW / 2}
            y={1 + cellH / 2 + 5}
            textAnchor="middle"
            fontSize="10"
            fill="#e2e8f0"
          >
            {text}
          </text>
        </g>
      ))}
    </svg>
  )
}

function PassBadge({ value }) {
  const pass = value === true || value === 'PASS'
  const fail = value === false || value === 'FAIL'
  if (pass) return (
    <span className="inline-flex items-center gap-1 text-emerald-400 font-medium text-[11px]">
      <CheckCircle size={11} />PASS
    </span>
  )
  if (fail) return (
    <span className="inline-flex items-center gap-1 text-red-400 font-medium text-[11px]">
      <XCircle size={11} />FAIL
    </span>
  )
  return null
}

function FieldEditor({ field, value, onChange }) {
  if (field.kind === 'boolean') {
    return (
      <label className="flex items-center gap-2 text-[11px] text-ink-300 cursor-pointer">
        <input
          type="checkbox"
          checked={!!value}
          onChange={(e) => onChange(e.target.checked)}
          className="accent-kerf-400"
        />
        {field.label}
      </label>
    )
  }
  if (field.kind === 'select') {
    return (
      <div className="flex flex-col gap-1">
        <label className="text-[10px] text-ink-500 uppercase tracking-wider">{field.label}</label>
        <select
          value={value ?? field.default}
          onChange={(e) => onChange(e.target.value)}
          className="bg-ink-900 border border-ink-700 text-ink-100 text-[11px] rounded px-2 py-1 focus:outline-none focus:border-kerf-500"
        >
          {field.options.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>
    )
  }
  if (field.kind === 'number') {
    return (
      <div className="flex flex-col gap-1">
        <label className="text-[10px] text-ink-500 uppercase tracking-wider">{field.label}</label>
        <input
          type="number"
          value={value ?? field.default}
          min={field.min}
          step={field.step ?? 'any'}
          onChange={(e) => onChange(parseFloat(e.target.value))}
          className="bg-ink-900 border border-ink-700 text-ink-100 text-[11px] rounded px-2 py-1 w-full focus:outline-none focus:border-kerf-500"
        />
      </div>
    )
  }
  // text
  return (
    <div className="flex flex-col gap-1">
      <label className="text-[10px] text-ink-500 uppercase tracking-wider">{field.label}</label>
      <input
        type="text"
        value={value ?? field.default ?? ''}
        onChange={(e) => onChange(e.target.value)}
        className="bg-ink-900 border border-ink-700 text-ink-100 text-[11px] rounded px-2 py-1 w-full focus:outline-none focus:border-kerf-500"
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tool Inspector (right-hand pane)
// ---------------------------------------------------------------------------

function ToolInspector({ tool, params, onParamChange, onRun, running, result }) {
  if (!tool) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-ink-600">
        <Shield size={32} className="opacity-20" />
        <p className="text-[12px]">Select a GD&amp;T tool to configure and run it.</p>
      </div>
    )
  }

  const Icon = tool.icon
  const catInfo = CATEGORIES[tool.category] ?? {}

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Tool header */}
      <div className="px-4 py-3 border-b border-ink-800 bg-ink-950">
        <div className="flex items-center gap-2 mb-1">
          <Icon size={14} className="text-kerf-400 shrink-0" />
          <span className="text-[13px] font-semibold text-ink-100">{tool.label}</span>
          <span className={`ml-auto text-[10px] font-medium ${catInfo.color ?? 'text-ink-500'}`}>
            {catInfo.label}
          </span>
        </div>
        <p className="text-[10px] text-ink-600 font-mono">{tool.standard}</p>
      </div>

      {/* Description */}
      <div className="px-4 py-2 border-b border-ink-800 bg-ink-950/60">
        <p className="text-[11px] text-ink-400 leading-relaxed">{tool.description}</p>
      </div>

      {/* Fields */}
      <div className="flex-1 overflow-auto px-4 py-3 space-y-3">
        {tool.fields.map((field) => (
          <FieldEditor
            key={field.key}
            field={field}
            value={params[field.key]}
            onChange={(v) => onParamChange(field.key, v)}
          />
        ))}
      </div>

      {/* Run button */}
      <div className="px-4 py-3 border-t border-ink-800 bg-ink-950">
        <button
          onClick={onRun}
          disabled={running}
          className="flex items-center justify-center gap-2 w-full bg-kerf-600 hover:bg-kerf-500 disabled:bg-ink-800 disabled:text-ink-600 text-white text-[12px] font-medium rounded-md py-2 transition-colors"
        >
          {running ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
          {running ? 'Running…' : `Run ${tool.id}`}
        </button>
      </div>

      {/* Result */}
      {result && (
        <div className="border-t border-ink-800 bg-ink-950/80 px-4 py-3 max-h-56 overflow-auto">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-[10px] text-ink-500 uppercase tracking-wider font-medium">Result</span>
            {result.compliant != null && <PassBadge value={result.compliant} />}
            {result.pass_fail != null && <PassBadge value={result.pass_fail} />}
            {result.overall_pass != null && <PassBadge value={result.overall_pass} />}
            {result.valid != null && <PassBadge value={result.valid} />}
          </div>
          <pre className="text-[10px] text-ink-300 font-mono whitespace-pre-wrap break-all leading-relaxed">
            {JSON.stringify(result, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tool Card
// ---------------------------------------------------------------------------

function ToolCard({ tool, selected, onClick }) {
  const Icon = tool.icon
  const catInfo = CATEGORIES[tool.category] ?? {}
  return (
    <button
      onClick={onClick}
      className={[
        'flex items-start gap-2 px-3 py-2.5 rounded-lg border text-left transition-colors w-full',
        selected
          ? 'border-kerf-500 bg-kerf-950/40 text-ink-100'
          : 'border-ink-800 hover:border-ink-600 bg-ink-950/60 hover:bg-ink-900/60 text-ink-300',
      ].join(' ')}
    >
      <Icon size={14} className={`mt-0.5 shrink-0 ${catInfo.color ?? 'text-ink-500'}`} />
      <div className="flex-1 min-w-0">
        <div className="text-[12px] font-medium truncate">{tool.label}</div>
        <div className="text-[10px] text-ink-600 font-mono truncate">{tool.id}</div>
      </div>
      {selected && <ChevronRight size={12} className="text-kerf-400 shrink-0 mt-0.5" />}
    </button>
  )
}

// ---------------------------------------------------------------------------
// Section collapse helper
// ---------------------------------------------------------------------------
function CollapsibleSection({ title, icon: Icon, iconClass = 'text-kerf-400', children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border border-ink-800 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 w-full px-3 py-2 bg-ink-900/60 hover:bg-ink-800/60 text-left"
      >
        {Icon && <Icon size={12} className={iconClass} />}
        <span className="text-[11px] font-semibold text-ink-200 flex-1">{title}</span>
        {open
          ? <ChevronUp size={11} className="text-ink-500" />
          : <ChevronDown size={11} className="text-ink-500" />}
      </button>
      {open && <div className="px-3 py-2.5 space-y-3 bg-ink-950/40">{children}</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Drawing Annotation panel
// ---------------------------------------------------------------------------

// Mock drawing list for the selector — in production this comes from the
// project file tree.
const MOCK_DRAWINGS = [
  { id: 'drawing-001', label: 'Sheet 1 — Assembly' },
  { id: 'drawing-002', label: 'Sheet 2 — Part A' },
  { id: 'drawing-003', label: 'Sheet 3 — Part B' },
]

const DATUM_LETTERS = ['A', 'B', 'C', 'D', 'E', 'F']
const DATUM_ROLES = ['primary', 'secondary', 'tertiary']

const TOLERANCE_TYPES = [
  { value: 'position',        label: '⊕ Position' },
  { value: 'flatness',        label: '⏥ Flatness' },
  { value: 'straightness',    label: '⏤ Straightness' },
  { value: 'roundness',       label: '○ Roundness' },
  { value: 'cylindricity',    label: '⌭ Cylindricity' },
  { value: 'perpendicularity',label: '⊥ Perpendicularity' },
  { value: 'angularity',      label: '∠ Angularity' },
  { value: 'parallelism',     label: '∥ Parallelism' },
  { value: 'profile_line',    label: '⌒ Profile of a Line' },
  { value: 'profile_surface', label: '⌓ Profile of a Surface' },
  { value: 'runout_circular', label: '↗ Circular Runout' },
  { value: 'runout_total',    label: '⌿ Total Runout' },
]

function DrawingAnnotationPanel({ mbdMode, onResult }) {
  // Drawing selector
  const [drawingId, setDrawingId] = useState(MOCK_DRAWINGS[0].id)

  // Datum apply state
  const [datumFeatureId, setDatumFeatureId]     = useState('face-0')
  const [datumLetter, setDatumLetter]           = useState('A')
  const [datumRole, setDatumRole]               = useState('primary')

  // FCF builder state
  const [fcfSymbol, setFcfSymbol]               = useState('position')
  const [fcfTolMm, setFcfTolMm]                 = useState(0.1)
  const [fcfDiamZone, setFcfDiamZone]           = useState(true)
  const [fcfModifier, setFcfModifier]           = useState('none')
  const [fcfDatumA, setFcfDatumA]               = useState('A')
  const [fcfDatumB, setFcfDatumB]               = useState('B')
  const [fcfDatumC, setFcfDatumC]               = useState('')

  // Apply tolerance state
  const [tolFeatureId, setTolFeatureId]         = useState('hole-0')

  // Validate frame state
  const [validateResult, setValidateResult]     = useState(null)
  const [validateLoading, setValidateLoading]   = useState(false)

  // Apply datum state
  const [applyDatumResult, setApplyDatumResult] = useState(null)
  const [applyDatumLoading, setApplyDatumLoading] = useState(false)

  // Apply tolerance state
  const [applyTolResult, setApplyTolResult]     = useState(null)
  const [applyTolLoading, setApplyTolLoading]   = useState(false)

  // Build FCF string from builder state
  function buildFcfString() {
    const sym = GDT_SYMBOLS[fcfSymbol] || fcfSymbol
    const zone = fcfDiamZone ? '⌀' : ''
    const modStr = fcfModifier === 'mmc' ? 'Ⓜ' : fcfModifier === 'lmc' ? 'Ⓛ' : ''
    const datums = [fcfDatumA, fcfDatumB, fcfDatumC].filter(Boolean).join('|')
    return `${sym}|${zone}${Number(fcfTolMm).toFixed(3)}${modStr}${datums ? '|' + datums : ''}`
  }

  async function callTool(toolId, params) {
    const res = await fetch('/api/llm/tool', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool: toolId, params }),
    })
    return res.json()
  }

  async function handleApplyDatum() {
    setApplyDatumLoading(true)
    setApplyDatumResult(null)
    try {
      const json = await callTool('gdt_apply_datum', {
        feature_id: datumFeatureId,
        datum_letter: datumLetter,
        datum_role: datumRole,
        drawing_id: mbdMode ? null : drawingId,
        mbd_mode: mbdMode,
      })
      const r = json?.result ?? json
      setApplyDatumResult(r)
      onResult && onResult(r)
    } catch (err) {
      setApplyDatumResult({ error: String(err) })
    } finally {
      setApplyDatumLoading(false)
    }
  }

  async function handleApplyTolerance() {
    setApplyTolLoading(true)
    setApplyTolResult(null)
    try {
      const fcfString = buildFcfString()
      const json = await callTool('gdt_apply_tolerance', {
        feature_id: tolFeatureId,
        fcf_string: fcfString,
        drawing_id: mbdMode ? null : drawingId,
        mbd_mode: mbdMode,
      })
      const r = json?.result ?? json
      setApplyTolResult(r)
      onResult && onResult(r)
    } catch (err) {
      setApplyTolResult({ error: String(err) })
    } finally {
      setApplyTolLoading(false)
    }
  }

  async function handleValidateFrame() {
    setValidateLoading(true)
    setValidateResult(null)
    try {
      const fcfString = buildFcfString()
      const json = await callTool('gdt_validate_frame', { fcf_string: fcfString })
      const r = json?.result ?? json
      setValidateResult(r)
      onResult && onResult(r)
    } catch (err) {
      setValidateResult({ error: String(err) })
    } finally {
      setValidateLoading(false)
    }
  }

  return (
    <div className="space-y-3">
      {/* Drawing / MBD selector */}
      {!mbdMode && (
        <div className="flex flex-col gap-1">
          <label className="text-[10px] text-ink-500 uppercase tracking-wider">Drawing</label>
          <select
            value={drawingId}
            onChange={(e) => setDrawingId(e.target.value)}
            className="bg-ink-900 border border-ink-700 text-ink-100 text-[11px] rounded px-2 py-1 focus:outline-none focus:border-kerf-500"
          >
            {MOCK_DRAWINGS.map((d) => (
              <option key={d.id} value={d.id}>{d.label}</option>
            ))}
          </select>
        </div>
      )}
      {mbdMode && (
        <div className="rounded-md bg-blue-950/30 border border-blue-800/50 px-3 py-2 text-[11px] text-blue-300">
          MBD mode — GD&amp;T will be attached directly to the 3D body (no drawing sheet required).
        </div>
      )}

      {/* ── Datum Apply ──────────────────────────────────────────── */}
      <CollapsibleSection title="Apply Datum" icon={AlignLeft} iconClass="text-emerald-400">
        <div className="flex flex-col gap-2">
          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-ink-500 uppercase tracking-wider">Face / Edge / Point ID</label>
            <input
              type="text"
              value={datumFeatureId}
              onChange={(e) => setDatumFeatureId(e.target.value)}
              placeholder="face-0"
              className="bg-ink-900 border border-ink-700 text-ink-100 text-[11px] rounded px-2 py-1 w-full focus:outline-none focus:border-kerf-500"
            />
          </div>
          <div className="flex gap-2">
            <div className="flex flex-col gap-1 flex-1">
              <label className="text-[10px] text-ink-500 uppercase tracking-wider">Datum Letter</label>
              <select
                value={datumLetter}
                onChange={(e) => setDatumLetter(e.target.value)}
                className="bg-ink-900 border border-ink-700 text-ink-100 text-[11px] rounded px-2 py-1 focus:outline-none focus:border-kerf-500"
              >
                {DATUM_LETTERS.map((l) => <option key={l} value={l}>{l}</option>)}
              </select>
            </div>
            <div className="flex flex-col gap-1 flex-1">
              <label className="text-[10px] text-ink-500 uppercase tracking-wider">Role</label>
              <select
                value={datumRole}
                onChange={(e) => setDatumRole(e.target.value)}
                className="bg-ink-900 border border-ink-700 text-ink-100 text-[11px] rounded px-2 py-1 focus:outline-none focus:border-kerf-500"
              >
                {DATUM_ROLES.map((r) => <option key={r} value={r}>{r.charAt(0).toUpperCase() + r.slice(1)}</option>)}
              </select>
            </div>
          </div>
          <button
            onClick={handleApplyDatum}
            disabled={applyDatumLoading}
            className="flex items-center justify-center gap-2 bg-emerald-700 hover:bg-emerald-600 disabled:bg-ink-800 disabled:text-ink-600 text-white text-[11px] rounded py-1.5 transition-colors"
          >
            {applyDatumLoading ? <Loader2 size={11} className="animate-spin" /> : <Play size={11} />}
            {applyDatumLoading ? 'Applying…' : 'gdt_apply_datum'}
          </button>
          {applyDatumResult && (
            <ResultMini result={applyDatumResult} />
          )}
        </div>
      </CollapsibleSection>

      {/* ── FCF Builder ───────────────────────────────────────────── */}
      <CollapsibleSection title="Feature Control Frame Builder" icon={Shield} iconClass="text-kerf-400">
        <div className="space-y-2">
          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-ink-500 uppercase tracking-wider">Tolerance Type</label>
            <select
              value={fcfSymbol}
              onChange={(e) => setFcfSymbol(e.target.value)}
              className="bg-ink-900 border border-ink-700 text-ink-100 text-[11px] rounded px-2 py-1 focus:outline-none focus:border-kerf-500"
            >
              {TOLERANCE_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>

          <div className="flex gap-2">
            <div className="flex flex-col gap-1 flex-1">
              <label className="text-[10px] text-ink-500 uppercase tracking-wider">Tolerance (mm)</label>
              <input
                type="number"
                value={fcfTolMm}
                min={0}
                step="any"
                onChange={(e) => setFcfTolMm(parseFloat(e.target.value))}
                className="bg-ink-900 border border-ink-700 text-ink-100 text-[11px] rounded px-2 py-1 w-full focus:outline-none focus:border-kerf-500"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-ink-500 uppercase tracking-wider">Zone</label>
              <label className="flex items-center gap-1 mt-1.5 text-[11px] text-ink-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={fcfDiamZone}
                  onChange={(e) => setFcfDiamZone(e.target.checked)}
                  className="accent-kerf-400"
                />
                ⌀
              </label>
            </div>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-ink-500 uppercase tracking-wider">Modifier</label>
            <select
              value={fcfModifier}
              onChange={(e) => setFcfModifier(e.target.value)}
              className="bg-ink-900 border border-ink-700 text-ink-100 text-[11px] rounded px-2 py-1 focus:outline-none focus:border-kerf-500"
            >
              <option value="none">None (RFS)</option>
              <option value="mmc">Ⓜ MMC (Maximum Material Condition)</option>
              <option value="lmc">Ⓛ LMC (Least Material Condition)</option>
            </select>
          </div>

          <div className="grid grid-cols-3 gap-1">
            {[
              { label: 'Datum A', val: fcfDatumA, set: setFcfDatumA },
              { label: 'Datum B', val: fcfDatumB, set: setFcfDatumB },
              { label: 'Datum C', val: fcfDatumC, set: setFcfDatumC },
            ].map(({ label, val, set }) => (
              <div key={label} className="flex flex-col gap-1">
                <label className="text-[10px] text-ink-500 uppercase tracking-wider">{label}</label>
                <input
                  type="text"
                  value={val}
                  maxLength={2}
                  placeholder="—"
                  onChange={(e) => set(e.target.value.toUpperCase())}
                  className="bg-ink-900 border border-ink-700 text-ink-100 text-[11px] rounded px-2 py-1 focus:outline-none focus:border-kerf-500"
                />
              </div>
            ))}
          </div>

          {/* Live FCF SVG preview */}
          <div className="mt-1">
            <p className="text-[10px] text-ink-500 uppercase tracking-wider mb-1">Preview</p>
            <div className="bg-ink-900 border border-ink-700 rounded p-2 overflow-x-auto">
              <FcfSvgPreview
                symbol={fcfSymbol}
                toleranceMm={fcfTolMm}
                datumA={fcfDatumA}
                datumB={fcfDatumB}
                datumC={fcfDatumC}
                modifier={fcfModifier}
              />
              <p className="text-[9px] text-ink-600 font-mono mt-1">{buildFcfString()}</p>
            </div>
          </div>
        </div>
      </CollapsibleSection>

      {/* ── Apply Tolerance ────────────────────────────────────────── */}
      <CollapsibleSection title="Apply Tolerance to Feature" icon={FileText} iconClass="text-amber-400">
        <div className="space-y-2">
          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-ink-500 uppercase tracking-wider">Feature ID</label>
            <input
              type="text"
              value={tolFeatureId}
              onChange={(e) => setTolFeatureId(e.target.value)}
              placeholder="hole-0"
              className="bg-ink-900 border border-ink-700 text-ink-100 text-[11px] rounded px-2 py-1 w-full focus:outline-none focus:border-kerf-500"
            />
          </div>
          <div className="text-[10px] text-ink-500">
            FCF: <span className="font-mono text-ink-300">{buildFcfString()}</span>
          </div>
          <button
            onClick={handleApplyTolerance}
            disabled={applyTolLoading}
            className="flex items-center justify-center gap-2 w-full bg-amber-700 hover:bg-amber-600 disabled:bg-ink-800 disabled:text-ink-600 text-white text-[11px] rounded py-1.5 transition-colors"
          >
            {applyTolLoading ? <Loader2 size={11} className="animate-spin" /> : <Play size={11} />}
            {applyTolLoading ? 'Applying…' : 'gdt_apply_tolerance'}
          </button>
          {applyTolResult && <ResultMini result={applyTolResult} />}
        </div>
      </CollapsibleSection>

      {/* ── Validate Frame ─────────────────────────────────────────── */}
      <CollapsibleSection title="Validate Frame (Y14.5-2018)" icon={Filter} iconClass="text-blue-400">
        <div className="space-y-2">
          <div className="text-[10px] text-ink-500">
            Validates the FCF built above for symbol-modifier compatibility, datum requirements,
            and bonus tolerance (MMC/LMC §6.3).
          </div>
          <div className="text-[10px] text-ink-500">
            FCF: <span className="font-mono text-ink-300">{buildFcfString()}</span>
          </div>
          <button
            onClick={handleValidateFrame}
            disabled={validateLoading}
            className="flex items-center justify-center gap-2 w-full bg-blue-700 hover:bg-blue-600 disabled:bg-ink-800 disabled:text-ink-600 text-white text-[11px] rounded py-1.5 transition-colors"
          >
            {validateLoading ? <Loader2 size={11} className="animate-spin" /> : <Play size={11} />}
            {validateLoading ? 'Validating…' : 'gdt_validate_frame'}
          </button>
          {validateResult && (
            <div className="rounded bg-ink-900 border border-ink-700 p-2">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-[10px] text-ink-500 uppercase tracking-wider font-medium">Validation</span>
                {validateResult.valid != null && <PassBadge value={validateResult.valid} />}
              </div>
              {validateResult.violations?.length > 0 && (
                <ul className="space-y-0.5">
                  {validateResult.violations.map((v, i) => (
                    <li key={i} className="flex items-start gap-1 text-[10px] text-red-400">
                      <AlertTriangle size={9} className="mt-0.5 shrink-0" />
                      {v}
                    </li>
                  ))}
                </ul>
              )}
              {(!validateResult.violations || validateResult.violations.length === 0) && validateResult.valid === true && (
                <p className="text-[10px] text-emerald-400">No violations — frame is well-formed.</p>
              )}
            </div>
          )}
        </div>
      </CollapsibleSection>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tolerance Stackup Workflow panel
// ---------------------------------------------------------------------------

const EMPTY_LINK = () => ({ id: crypto.randomUUID(), link_id: '', nominal_mm: 0, tol_plus_mm: 0.1, tol_minus_mm: 0.1, direction: 'positive' })

function ToleranceStackupPanel({ onResult }) {
  const [links, setLinks]                   = useState([EMPTY_LINK()])
  const [gapMin, setGapMin]                 = useState(0.0)
  const [gapMax, setGapMax]                 = useState(1.0)
  const [loading, setLoading]               = useState(false)
  const [result, setResult]                 = useState(null)

  function addLink() { setLinks((prev) => [...prev, EMPTY_LINK()]) }
  function removeLink(idx) { setLinks((prev) => prev.filter((_, i) => i !== idx)) }
  function updateLink(idx, key, val) {
    setLinks((prev) => prev.map((l, i) => i === idx ? { ...l, [key]: val } : l))
  }

  async function runStackup(method) {
    setLoading(true)
    setResult(null)
    try {
      const chain = links.map(({ id: _id, ...rest }) => rest)
      const res = await fetch('/api/llm/tool', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tool: 'gdt_compute_dimension_chain',
          params: {
            chain,
            target_gap_min_mm: gapMin,
            target_gap_max_mm: gapMax,
            method,
          },
        }),
      })
      const json = await res.json()
      const r = json?.result ?? json
      setResult(r)
      onResult && onResult(r)
    } catch (err) {
      setResult({ error: String(err) })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-3">
      {/* Link editor */}
      <div className="space-y-2">
        {links.map((link, idx) => (
          <div key={link.id} className="rounded-md bg-ink-900/60 border border-ink-800 p-2 space-y-1.5">
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-ink-500 font-mono">#{idx + 1}</span>
              <input
                type="text"
                value={link.link_id}
                onChange={(e) => updateLink(idx, 'link_id', e.target.value)}
                placeholder="link-id"
                className="flex-1 bg-ink-950 border border-ink-700 text-ink-100 text-[10px] rounded px-2 py-0.5 focus:outline-none focus:border-kerf-500"
              />
              <select
                value={link.direction}
                onChange={(e) => updateLink(idx, 'direction', e.target.value)}
                className="bg-ink-950 border border-ink-700 text-ink-100 text-[10px] rounded px-1 py-0.5 focus:outline-none focus:border-kerf-500"
              >
                <option value="positive">+</option>
                <option value="negative">−</option>
              </select>
              <button
                onClick={() => removeLink(idx)}
                className="text-red-500 hover:text-red-400"
                title="Remove link"
              >
                <Trash2 size={11} />
              </button>
            </div>
            <div className="grid grid-cols-3 gap-1">
              {[
                { label: 'Nominal (mm)', key: 'nominal_mm' },
                { label: '+Tol (mm)',    key: 'tol_plus_mm' },
                { label: '−Tol (mm)',    key: 'tol_minus_mm' },
              ].map(({ label, key }) => (
                <div key={key} className="flex flex-col gap-0.5">
                  <label className="text-[9px] text-ink-600">{label}</label>
                  <input
                    type="number"
                    value={link[key]}
                    step="any"
                    onChange={(e) => updateLink(idx, key, parseFloat(e.target.value))}
                    className="bg-ink-950 border border-ink-700 text-ink-100 text-[10px] rounded px-1 py-0.5 focus:outline-none focus:border-kerf-500"
                  />
                </div>
              ))}
            </div>
          </div>
        ))}

        <button
          onClick={addLink}
          className="flex items-center gap-1.5 text-[11px] text-kerf-400 hover:text-kerf-300 w-full py-1 border border-dashed border-ink-700 hover:border-kerf-600 rounded-md justify-center transition-colors"
        >
          <PlusCircle size={12} />Add link
        </button>
      </div>

      {/* Gap bounds */}
      <div className="grid grid-cols-2 gap-2">
        <div className="flex flex-col gap-1">
          <label className="text-[10px] text-ink-500 uppercase tracking-wider">Min gap (mm)</label>
          <input
            type="number"
            value={gapMin}
            step="any"
            onChange={(e) => setGapMin(parseFloat(e.target.value))}
            className="bg-ink-900 border border-ink-700 text-ink-100 text-[11px] rounded px-2 py-1 focus:outline-none focus:border-kerf-500"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] text-ink-500 uppercase tracking-wider">Max gap (mm)</label>
          <input
            type="number"
            value={gapMax}
            step="any"
            onChange={(e) => setGapMax(parseFloat(e.target.value))}
            className="bg-ink-900 border border-ink-700 text-ink-100 text-[11px] rounded px-2 py-1 focus:outline-none focus:border-kerf-500"
          />
        </div>
      </div>

      {/* Run buttons */}
      <div className="flex gap-2">
        <button
          onClick={() => runStackup('worst_case')}
          disabled={loading}
          className="flex-1 flex items-center justify-center gap-1.5 bg-kerf-700 hover:bg-kerf-600 disabled:bg-ink-800 disabled:text-ink-600 text-white text-[11px] rounded py-1.5 transition-colors"
        >
          {loading ? <Loader2 size={11} className="animate-spin" /> : <BarChart2 size={11} />}
          Worst Case
        </button>
        <button
          onClick={() => runStackup('rss')}
          disabled={loading}
          className="flex-1 flex items-center justify-center gap-1.5 bg-blue-700 hover:bg-blue-600 disabled:bg-ink-800 disabled:text-ink-600 text-white text-[11px] rounded py-1.5 transition-colors"
        >
          {loading ? <Loader2 size={11} className="animate-spin" /> : <BarChart2 size={11} />}
          RSS (3σ)
        </button>
      </div>

      {/* Results table */}
      {result && !result.error && (
        <div className="rounded-md bg-ink-900 border border-ink-700 overflow-hidden">
          <table className="w-full text-[10px]">
            <thead>
              <tr className="border-b border-ink-700 bg-ink-800/40">
                <th className="text-left px-2 py-1 text-ink-500 font-medium">Metric</th>
                <th className="text-right px-2 py-1 text-ink-500 font-medium">Value</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-800">
              {[
                ['Nominal gap',    result.nominal_gap_mm != null  ? `${Number(result.nominal_gap_mm).toFixed(4)} mm` : '—'],
                ['WC min',         result.worst_case_min_mm != null ? `${Number(result.worst_case_min_mm).toFixed(4)} mm` : '—'],
                ['WC max',         result.worst_case_max_mm != null ? `${Number(result.worst_case_max_mm).toFixed(4)} mm` : '—'],
                ['RSS min (3σ)',    result.rss_min_mm != null       ? `${Number(result.rss_min_mm).toFixed(4)} mm` : '—'],
                ['RSS max (3σ)',    result.rss_max_mm != null       ? `${Number(result.rss_max_mm).toFixed(4)} mm` : '—'],
                ['Dominant link',  result.dominant_link ?? '—'],
                ['Links count',    result.links_count ?? '—'],
              ].map(([label, val]) => (
                <tr key={label} className="hover:bg-ink-800/30">
                  <td className="px-2 py-1 text-ink-400">{label}</td>
                  <td className="px-2 py-1 text-right font-mono text-ink-200">{val}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {/* WC pass/fail */}
          {result.worst_case_min_mm != null && (
            <div className="px-2 py-1.5 border-t border-ink-700 flex items-center gap-2">
              <span className="text-[10px] text-ink-500">WC within bounds</span>
              <PassBadge value={
                result.worst_case_min_mm >= gapMin && result.worst_case_max_mm <= gapMax
              } />
              <span className="text-[10px] text-ink-500 ml-2">RSS within bounds</span>
              <PassBadge value={
                result.rss_min_mm != null &&
                result.rss_min_mm >= gapMin && result.rss_max_mm <= gapMax
              } />
            </div>
          )}
        </div>
      )}
      {result?.error && (
        <div className="rounded bg-red-950/30 border border-red-800/40 px-2 py-1.5 text-[10px] text-red-400">
          {result.error}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tiny inline result display
// ---------------------------------------------------------------------------
function ResultMini({ result }) {
  if (!result) return null
  const hasPass = result.valid != null || result.compliant != null || result.overall_pass != null
  return (
    <div className="rounded bg-ink-950 border border-ink-800 px-2 py-1.5">
      {hasPass && (
        <div className="mb-1">
          <PassBadge value={result.valid ?? result.compliant ?? result.overall_pass} />
        </div>
      )}
      <pre className="text-[9px] text-ink-400 font-mono whitespace-pre-wrap break-all leading-relaxed max-h-28 overflow-auto">
        {JSON.stringify(result, null, 2)}
      </pre>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export default function GDTPanel() {
  const [selectedId, setSelectedId]   = useState(null)
  const [params, setParams]           = useState({})
  const [running, setRunning]         = useState(false)
  const [result, setResult]           = useState(null)

  // MBD toggle — when on, GD&T attaches to 3D body instead of drawing sheet
  const [mbdMode, setMbdMode]         = useState(false)

  // Active left panel tab: 'tools' | 'annotation' | 'stackup'
  const [leftTab, setLeftTab]         = useState('tools')

  const selected = GDT_TOOLS.find((t) => t.id === selectedId) ?? null

  function handleSelect(tool) {
    if (tool.id === selectedId) return
    setSelectedId(tool.id)
    // Initialise params from field defaults
    const init = {}
    for (const f of tool.fields) init[f.key] = f.default ?? ''
    setParams(init)
    setResult(null)
  }

  function handleParamChange(key, value) {
    setParams((p) => ({ ...p, [key]: value }))
  }

  async function handleRun() {
    if (!selected) return
    setRunning(true)
    setResult(null)
    try {
      const res = await fetch('/api/llm/tool', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tool: selected.id, params }),
      })
      const json = await res.json()
      setResult(json?.result ?? json)
    } catch (err) {
      setResult({ error: String(err) })
    } finally {
      setRunning(false)
    }
  }

  // Group tools by category
  const grouped = {}
  for (const tool of GDT_TOOLS) {
    if (!grouped[tool.category]) grouped[tool.category] = []
    grouped[tool.category].push(tool)
  }

  const LEFT_TABS = [
    { id: 'tools',      label: 'Tools',      icon: Shield },
    { id: 'annotation', label: 'Drawing',    icon: Layout },
    { id: 'stackup',    label: 'Stackup',    icon: BarChart2 },
  ]

  return (
    <div className="flex flex-col h-full bg-ink-950 text-ink-100">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-ink-800 bg-ink-950 shrink-0 flex-wrap gap-y-1">
        <Shield size={15} className="text-kerf-400 shrink-0" />
        <span className="text-[14px] font-semibold text-ink-100">GD&amp;T Metrology</span>
        <span className="ml-2 text-[10px] text-ink-600">ASME Y14.5-2018</span>
        <span className="ml-auto text-[10px] text-ink-600">{GDT_TOOLS.length} tools</span>

        {/* MBD toggle */}
        <button
          onClick={() => setMbdMode((v) => !v)}
          title={mbdMode ? 'MBD mode — click to use drawing sheet' : 'Drawing sheet mode — click for MBD'}
          className={[
            'flex items-center gap-1.5 px-2 py-1 rounded-md border text-[10px] font-medium transition-colors',
            mbdMode
              ? 'border-blue-600 bg-blue-950/40 text-blue-300'
              : 'border-ink-700 bg-ink-900/60 text-ink-500 hover:border-ink-500',
          ].join(' ')}
        >
          {mbdMode ? <ToggleRight size={13} className="text-blue-400" /> : <ToggleLeft size={13} />}
          MBD
        </button>
      </div>

      {/* Body: left panel + right inspector */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left panel */}
        <div className="w-64 shrink-0 border-r border-ink-800 flex flex-col overflow-hidden">
          {/* Tab bar */}
          <div className="flex border-b border-ink-800 bg-ink-950 shrink-0">
            {LEFT_TABS.map((tab) => {
              const Icon = tab.icon
              return (
                <button
                  key={tab.id}
                  onClick={() => setLeftTab(tab.id)}
                  className={[
                    'flex-1 flex items-center justify-center gap-1.5 py-2 text-[10px] font-medium transition-colors border-b-2',
                    leftTab === tab.id
                      ? 'border-kerf-400 text-kerf-300 bg-kerf-950/20'
                      : 'border-transparent text-ink-500 hover:text-ink-300',
                  ].join(' ')}
                >
                  <Icon size={11} />
                  {tab.label}
                </button>
              )
            })}
          </div>

          {/* Tab content */}
          <div className="flex-1 overflow-auto py-3 px-2 space-y-4">
            {/* ── Tools tab ─────────────────────────────────────── */}
            {leftTab === 'tools' && Object.entries(grouped).map(([catId, tools]) => {
              const catInfo = CATEGORIES[catId] ?? { label: catId }
              return (
                <div key={catId}>
                  <p className={`text-[10px] font-semibold uppercase tracking-wider px-1 mb-1.5 ${catInfo.color ?? 'text-ink-500'}`}>
                    {catInfo.label}
                  </p>
                  <div className="space-y-1">
                    {tools.map((tool) => (
                      <ToolCard
                        key={tool.id}
                        tool={tool}
                        selected={tool.id === selectedId}
                        onClick={() => {
                          handleSelect(tool)
                          setLeftTab('tools')
                        }}
                      />
                    ))}
                  </div>
                </div>
              )
            })}

            {/* ── Drawing Annotation tab ─────────────────────────── */}
            {leftTab === 'annotation' && (
              <DrawingAnnotationPanel mbdMode={mbdMode} onResult={setResult} />
            )}

            {/* ── Tolerance Stackup tab ─────────────────────────── */}
            {leftTab === 'stackup' && (
              <ToleranceStackupPanel onResult={setResult} />
            )}
          </div>
        </div>

        {/* Right: inspector (only shown in tools tab; annotation/stackup fill the left) */}
        <div className="flex-1 overflow-hidden">
          {leftTab === 'tools' ? (
            <ToolInspector
              tool={selected}
              params={params}
              onParamChange={handleParamChange}
              onRun={handleRun}
              running={running}
              result={result}
            />
          ) : (
            <div className="flex flex-col items-center justify-center h-full gap-3 text-ink-600 px-6 text-center">
              <Shield size={32} className="opacity-10" />
              <p className="text-[11px] leading-relaxed">
                {leftTab === 'annotation'
                  ? 'Drawing annotation results and FCF previews appear in the left panel. Switch to the Tools tab to run individual GD&T computations.'
                  : 'Stackup results appear in the left panel. Switch to the Tools tab to run individual GD&T computations.'}
              </p>
              {result && (
                <div className="w-full rounded-md bg-ink-900 border border-ink-800 p-3 text-left mt-2">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-[10px] text-ink-500 uppercase tracking-wider font-medium">Last Result</span>
                    {result.compliant != null && <PassBadge value={result.compliant} />}
                    {result.overall_pass != null && <PassBadge value={result.overall_pass} />}
                    {result.valid != null && <PassBadge value={result.valid} />}
                  </div>
                  <pre className="text-[10px] text-ink-300 font-mono whitespace-pre-wrap break-all leading-relaxed max-h-64 overflow-auto">
                    {JSON.stringify(result, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
