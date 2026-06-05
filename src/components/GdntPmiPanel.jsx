// GdntPmiPanel.jsx — GD&T / PMI drawing placement panel.
//
// This panel is the right-side inspector for GD&T annotations on 2D drawings.
// It combines three responsibilities:
//
//   1. PLACEMENT — shows GdntToolbar buttons for all ISO 1101 characteristics
//      and datum labels.  Activating a tool transitions the drawing canvas into
//      placement mode.
//
//   2. INSPECTION — lists the FCF and datum-label annotations already placed
//      on the active drawing sheet, shows the rendered FCF text, and lets the
//      user delete individual annotations.
//
//   3. VALIDATION — quick-run shortcuts for the backend GD&T validation tools
//      (gdt_validate_frame, gdt_auto_callouts) wired to /api/tools/call.
//
// Props:
//   drawing          — current drawing document (multi-sheet or flat)
//   tool             — active tool id (string, e.g. 'gdt:fcf:position')
//   onTool(id)       — set the active tool (pass '' to clear)
//   selectedAnnId    — id of the currently selected annotation
//   onDeleteAnn(id)  — delete an annotation from the drawing
//   onAutoCallout()  — trigger auto-callout proposal (optional)
//
// The panel is intentionally framework-agnostic: it renders with plain Tailwind
// utility classes matching the surrounding DrawingsView palette, and avoids any
// global state import.

import { useState, useMemo } from 'react'
import { Shield, Trash2, ChevronDown, ChevronUp, Play, Loader2, CheckCircle, XCircle } from 'lucide-react'
import GdntToolbar from './GdntToolbar.jsx'
import { GDT_SYMBOL_MAP, renderFcf, listFcfs, listDatumLabels } from '../lib/gdntAnnotations.js'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function callTool(toolName, args) {
  const res = await fetch(`${API_URL}/api/tools/call`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tool: toolName, args }),
  })
  if (!res.ok) {
    const txt = await res.text().catch(() => res.statusText)
    throw new Error(`HTTP ${res.status}: ${txt}`)
  }
  return res.json()
}

function PassBadge({ value }) {
  if (value === true) {
    return (
      <span className="inline-flex items-center gap-1 text-emerald-400 font-medium text-[10px]">
        <CheckCircle size={10} />PASS
      </span>
    )
  }
  if (value === false) {
    return (
      <span className="inline-flex items-center gap-1 text-red-400 font-medium text-[10px]">
        <XCircle size={10} />FAIL
      </span>
    )
  }
  return null
}

// Collapsible section — matches GDTPanel.jsx CollapsibleSection pattern.
function Section({ title, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border border-ink-800 rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 w-full px-3 py-2 bg-ink-900/60 hover:bg-ink-800/60 text-left"
        aria-expanded={open}
      >
        <Shield size={11} className="text-kerf-400 shrink-0" />
        <span className="text-[11px] font-semibold text-ink-200 flex-1">{title}</span>
        {open
          ? <ChevronUp size={11} className="text-ink-500" />
          : <ChevronDown size={11} className="text-ink-500" />}
      </button>
      {open && <div className="px-3 py-2 space-y-2 bg-ink-950/40">{children}</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// FCF list entry
// ---------------------------------------------------------------------------

function FcfListEntry({ ann, selected, onDelete }) {
  const sym = GDT_SYMBOL_MAP[ann.symbol_code]
  const rendered = ann.rendered || renderFcf(ann)
  return (
    <div
      className={`flex items-start gap-2 rounded px-2 py-1.5 text-[11px] ${
        selected ? 'bg-kerf-950/40 border border-kerf-700' : 'bg-ink-900/40 border border-ink-800'
      }`}
      data-testid={`pmi-fcf-entry-${ann.id}`}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="text-[13px]">{sym?.unicode || '?'}</span>
          <span className="font-mono text-kerf-300 text-[10px] truncate">{rendered}</span>
        </div>
        <div className="text-[9px] text-ink-600 font-mono mt-0.5">
          {`x:${ann.x?.toFixed(1)} y:${ann.y?.toFixed(1)}`}
          {ann.view_id && ` · view:${ann.view_id.slice(0, 8)}`}
        </div>
      </div>
      <button
        type="button"
        aria-label="Delete FCF"
        title="Delete"
        onClick={() => onDelete?.(ann.id)}
        className="shrink-0 text-ink-600 hover:text-red-400 transition-colors"
      >
        <Trash2 size={11} />
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Datum list entry
// ---------------------------------------------------------------------------

function DatumListEntry({ ann, selected, onDelete }) {
  const label = ann.label || ann.params?.label || '?'
  return (
    <div
      className={`flex items-center gap-2 rounded px-2 py-1.5 text-[11px] ${
        selected ? 'bg-kerf-950/40 border border-kerf-700' : 'bg-ink-900/40 border border-ink-800'
      }`}
      data-testid={`pmi-datum-entry-${ann.id}`}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="font-mono font-bold text-emerald-300 text-[11px]">{label}</span>
          <span className="text-ink-500 text-[9px]">datum</span>
        </div>
        <div className="text-[9px] text-ink-600 font-mono">
          {`x:${ann.x?.toFixed(1)} y:${ann.y?.toFixed(1)}`}
        </div>
      </div>
      <button
        type="button"
        aria-label={`Delete datum ${label}`}
        title="Delete"
        onClick={() => onDelete?.(ann.id)}
        className="shrink-0 text-ink-600 hover:text-red-400 transition-colors"
      >
        <Trash2 size={11} />
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Quick-validate panel — runs gdt_validate_frame against a user-typed FCF string
// ---------------------------------------------------------------------------

function QuickValidatePanel() {
  const [fcfString, setFcfString] = useState('⌖|⌀0.5|A|B|C')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)

  async function handleValidate() {
    setLoading(true)
    setResult(null)
    try {
      const json = await callTool('gdt_validate_frame', { fcf_string: fcfString })
      setResult(json?.result ?? json)
    } catch (err) {
      setResult({ error: String(err) })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-2" data-testid="pmi-quick-validate">
      <div className="flex flex-col gap-1">
        <label className="text-[9px] text-ink-500 uppercase tracking-wider">FCF string</label>
        <input
          type="text"
          value={fcfString}
          onChange={(e) => setFcfString(e.target.value)}
          placeholder="⌖|⌀0.5|A|B|C"
          className="bg-ink-900 border border-ink-700 text-ink-100 text-[11px] font-mono rounded px-2 py-1 focus:outline-none focus:border-kerf-500"
          aria-label="FCF string input"
        />
      </div>
      <button
        type="button"
        onClick={handleValidate}
        disabled={loading}
        className="flex items-center justify-center gap-1.5 w-full bg-kerf-700 hover:bg-kerf-600 disabled:bg-ink-800 disabled:text-ink-600 text-white text-[11px] rounded py-1.5 transition-colors"
      >
        {loading ? <Loader2 size={11} className="animate-spin" /> : <Play size={11} />}
        {loading ? 'Validating…' : 'gdt_validate_frame'}
      </button>
      {result && (
        <div className="rounded bg-ink-900 border border-ink-800 px-2 py-1.5">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[9px] text-ink-500 uppercase tracking-wider">Result</span>
            {result.valid != null && <PassBadge value={result.valid} />}
          </div>
          {result.violations?.length > 0 && (
            <ul className="space-y-0.5 text-[9px] text-red-400">
              {result.violations.map((v, i) => <li key={i}>• {v}</li>)}
            </ul>
          )}
          {result.error && (
            <div className="text-[9px] text-red-400">{result.error}</div>
          )}
          {!result.error && result.valid === true && (
            <div className="text-[9px] text-emerald-400">Frame is well-formed.</div>
          )}
          {result.canonical_string && (
            <div className="text-[9px] text-ink-400 font-mono mt-1">
              Canonical: <span className="text-ink-200">{result.canonical_string}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export default function GdntPmiPanel({
  drawing = null,
  tool = '',
  onTool,
  selectedAnnId = null,
  onDeleteAnn,
  onAutoCallout,
}) {
  // Derive placed FCF and datum annotations from the drawing document.
  const fcfs = useMemo(() => {
    if (!drawing) return []
    try { return listFcfs(drawing) } catch { return [] }
  }, [drawing])

  const datums = useMemo(() => {
    if (!drawing) return []
    try { return listDatumLabels(drawing) } catch { return [] }
  }, [drawing])

  const totalAnnotations = fcfs.length + datums.length

  return (
    <div
      className="flex flex-col h-full overflow-hidden bg-ink-950 text-ink-100"
      data-testid="gdnt-pmi-panel"
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-ink-800 shrink-0">
        <Shield size={14} className="text-kerf-400 shrink-0" />
        <span className="text-[13px] font-semibold text-ink-100">GD&amp;T / PMI</span>
        <span className="ml-auto text-[10px] text-ink-600 font-mono">
          {totalAnnotations} placed
        </span>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-auto py-2 px-2 space-y-2">

        {/* ── Toolbar section ─────────────────────────────────────── */}
        <Section title="Placement Tools" defaultOpen>
          <div className="text-[9px] text-ink-500 leading-relaxed mb-1">
            Select a characteristic, then click on the drawing canvas to place it.
            Datum labels (A/B/C) place immediately; FCF symbols open a tolerance editor.
          </div>
          {/* Embed the GdntToolbar inline — it normally floats over the canvas;
              here it is inlined without the absolute positioning so it sits in
              the panel flow. The onTool callback is shared with the canvas. */}
          <div className="relative">
            <GdntToolbar
              tool={tool}
              onTool={onTool}
            />
          </div>
        </Section>

        {/* ── Placed annotations ──────────────────────────────────── */}
        <Section title={`Placed FCFs (${fcfs.length})`} defaultOpen={fcfs.length > 0}>
          {fcfs.length === 0 ? (
            <div className="text-[10px] text-ink-600 py-1">
              No FCFs placed yet. Select a characteristic above and click on the drawing.
            </div>
          ) : (
            <div className="space-y-1">
              {fcfs.map((ann) => (
                <FcfListEntry
                  key={ann.id}
                  ann={ann}
                  selected={ann.id === selectedAnnId}
                  onDelete={onDeleteAnn}
                />
              ))}
            </div>
          )}
        </Section>

        <Section title={`Placed Datums (${datums.length})`} defaultOpen={datums.length > 0}>
          {datums.length === 0 ? (
            <div className="text-[10px] text-ink-600 py-1">
              No datums placed yet. Select Datum A/B/C and click on the drawing.
            </div>
          ) : (
            <div className="space-y-1">
              {datums.map((ann) => (
                <DatumListEntry
                  key={ann.id}
                  ann={ann}
                  selected={ann.id === selectedAnnId}
                  onDelete={onDeleteAnn}
                />
              ))}
            </div>
          )}
        </Section>

        {/* ── Quick validation ────────────────────────────────────── */}
        <Section title="Validate Frame (Y14.5)" defaultOpen={true}>
          <QuickValidatePanel />
        </Section>

        {/* ── Auto-callout ────────────────────────────────────────── */}
        {onAutoCallout && (
          <Section title="Auto-Propose GD&T" defaultOpen={false}>
            <div className="text-[9px] text-ink-500 leading-relaxed mb-1">
              Automatically propose GD&T feature control frames for the current part
              (requires feature classification data). Uses ISO 286-1 IT grades.
            </div>
            <button
              type="button"
              onClick={onAutoCallout}
              className="flex items-center justify-center gap-1.5 w-full bg-ink-800 hover:bg-ink-700 text-ink-200 text-[11px] border border-ink-700 rounded py-1.5 transition-colors"
              data-testid="pmi-auto-callout-btn"
            >
              <Play size={11} />
              gdt_auto_callouts
            </button>
          </Section>
        )}
      </div>
    </div>
  )
}
