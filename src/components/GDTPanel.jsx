// GDTPanel.jsx — /gdt route panel for GD&T metrology tools.
//
// Mirrors the GeometryInspect / GdntInspectionPanel inspector pattern but
// presents all wired GDT LLM tools (ASME Y14.5-2018) as a tool-card grid
// with per-tool parameter editors and a live result pane.
//
// Layout:
//   * top     — header bar with Shield icon + title
//   * left    — scrollable tool-card grid (9 GDT tools grouped by category)
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
// Calls are dispatched as JSON-RPC to /api/llm/tool (chat tool dispatch).

import { useState } from 'react'
import {
  Shield, ChevronRight, CheckCircle, XCircle, AlertTriangle,
  Ruler, RotateCcw, Layers, Activity, Filter, AlignLeft,
  Play, Loader2, FileText,
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
// Main export
// ---------------------------------------------------------------------------

export default function GDTPanel() {
  const [selectedId, setSelectedId]   = useState(null)
  const [params, setParams]           = useState({})
  const [running, setRunning]         = useState(false)
  const [result, setResult]           = useState(null)

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

  return (
    <div className="flex flex-col h-full bg-ink-950 text-ink-100">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-ink-800 bg-ink-950 shrink-0">
        <Shield size={15} className="text-kerf-400 shrink-0" />
        <span className="text-[14px] font-semibold text-ink-100">GD&amp;T Metrology</span>
        <span className="ml-2 text-[10px] text-ink-600">ASME Y14.5-2018</span>
        <span className="ml-auto text-[10px] text-ink-600">{GDT_TOOLS.length} tools</span>
      </div>

      {/* Body: tool list + inspector */}
      <div className="flex flex-1 overflow-hidden">
        {/* Tool list */}
        <div className="w-56 shrink-0 border-r border-ink-800 overflow-auto py-3 px-2 space-y-4">
          {Object.entries(grouped).map(([catId, tools]) => {
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
                      onClick={() => handleSelect(tool)}
                    />
                  ))}
                </div>
              </div>
            )
          })}
        </div>

        {/* Inspector */}
        <div className="flex-1 overflow-hidden">
          <ToolInspector
            tool={selected}
            params={params}
            onParamChange={handleParamChange}
            onRun={handleRun}
            running={running}
            result={result}
          />
        </div>
      </div>
    </div>
  )
}
