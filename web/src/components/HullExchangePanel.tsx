// HullExchangePanel.jsx — DXF / IGES / 3DM hull geometry exchange panel.
//
// Wires the marine_hull_exchange LLM tool:
//   marine_hull_exchange — export hull curves to DXF, IGES, or 3DM
//
// Accepts hull_form from HullFormPanel (via props) or generates one inline.
// Provides format selector + download trigger for each supported format.
//
// Formats
// ───────
//   DXF  — R2004 (AC1018): SPLINE entities (AutoCAD, Maxsurf, FreeCAD)
//   IGES — 5.3 / ASME Y14.26M: Entity 126 B-spline curves
//   3DM  — Rhino openNURBS v7: NurbsCurve objects (Rhino, Maxsurf, ShipConstructor)

import { useState, useCallback } from 'react'
import {
  Download,
  FileText,
  Loader2,
  AlertTriangle,
  CheckCircle,
  ArrowRight,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type HullExchangeFormat = 'dxf' | 'iges' | '3dm'

interface HullSectionPoint {
  waterline_m: number
  half_breadth_m: number
}
interface HullSection {
  station_m: number
  area_coeff: number
  points: HullSectionPoint[]
}
interface HullWaterline {
  draft_m: number
  stations_m: number[]
  half_breadths_m: number[]
}
interface HullButtock {
  half_breadth_m: number
  stations_m: number[]
  drafts_m: number[]
}
export interface HullForm {
  L_m: number
  B_m: number
  T_m: number
  Cb?: number
  Cm?: number
  Cp?: number
  lcb_frac?: number
  lcb_m_from_ap?: number
  volume_m3?: number
  n_sections: number
  n_waterlines?: number
  n_buttocks?: number
  sections: HullSection[]
  waterlines: HullWaterline[]
  buttocks: HullButtock[]
}

interface HullExchangeResult {
  hull_name?: string
  content?: string
  content_base64?: string
  n_bytes?: number
  n_chars?: number
  note?: string
  error?: string
}

export interface HullExchangePanelProps {
  hullForm?: HullForm | null
  content?: string | null
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

const API_URL =
  typeof import.meta !== 'undefined' && import.meta.env
    ? import.meta.env.VITE_API_URL || ''
    : ''

async function callTool<T>(toolName: string, args: Record<string, unknown>): Promise<T> {
  const res = await fetch(`${API_URL}/api/tools/call`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ tool: toolName, args }),
  })
  if (!res.ok) {
    const txt = await res.text().catch(() => res.statusText)
    throw new Error(`HTTP ${res.status}: ${txt}`)
  }
  const data = await res.json()
  if (typeof data.result === 'string') {
    try { return JSON.parse(data.result) } catch { return data.result }
  }
  return data.result ?? data
}

function base64ToBlob(b64: string, mime: string): Blob {
  const binary = atob(b64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return new Blob([bytes], { type: mime })
}

function downloadText(text: string, filename: string, mime = 'text/plain'): void {
  const blob = new Blob([text], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

// ---------------------------------------------------------------------------
// Format cards
// ---------------------------------------------------------------------------

interface FormatDef {
  id: HullExchangeFormat
  label: string
  subtitle: string
  desc: string
  ext: string
  mime: string
  badge: 'text' | 'binary'
  color: string
  borderColor: string
  bgColor: string
}

const FORMATS: FormatDef[] = [
  {
    id: 'dxf',
    label: 'DXF',
    subtitle: 'AutoCAD R2004 (AC1018)',
    desc: 'SPLINE entities for sections, waterlines, buttocks. Compatible with AutoCAD, LibreCAD, FreeCAD, Maxsurf.',
    ext: 'dxf',
    mime: 'application/dxf',
    badge: 'text',
    color: 'text-yellow-400',
    borderColor: 'border-yellow-800',
    bgColor: 'bg-yellow-950/30',
  },
  {
    id: 'iges',
    label: 'IGES',
    subtitle: 'IGES 5.3 / ASME Y14.26M-2012',
    desc: 'Entity 126 Rational B-spline curves. Universal CAD interchange — compatible with Rhino, CATIA, NX, Maxsurf.',
    ext: 'igs',
    mime: 'application/iges',
    badge: 'text',
    color: 'text-blue-400',
    borderColor: 'border-blue-800',
    bgColor: 'bg-blue-950/30',
  },
  {
    id: '3dm',
    label: '3DM',
    subtitle: 'Rhino openNURBS v7',
    desc: 'NurbsCurve objects in binary .3dm format. Open directly in Rhino 7/8, Maxsurf, ShipConstructor.',
    ext: '3dm',
    mime: 'application/octet-stream',
    badge: 'binary',
    color: 'text-purple-400',
    borderColor: 'border-purple-800',
    bgColor: 'bg-purple-950/30',
  },
]

function FormatCard({ fmt, selected, onSelect }: { fmt: FormatDef; selected: boolean; onSelect: (id: HullExchangeFormat) => void }) {
  return (
    <button
      onClick={() => onSelect(fmt.id)}
      className={`flex flex-col gap-1 rounded-lg border p-3 text-left transition-colors w-full ${
        selected
          ? `${fmt.borderColor} ${fmt.bgColor}`
          : 'border-gray-800 bg-gray-900 hover:border-gray-600'
      }`}
    >
      <div className="flex items-center gap-2">
        <span className={`font-mono font-bold text-sm ${fmt.color}`}>{fmt.label}</span>
        <span className="text-[10px] text-gray-500">{fmt.subtitle}</span>
        {fmt.badge === 'binary' && (
          <span className="ml-auto rounded text-[9px] px-1 py-0.5 bg-gray-800 text-gray-400">binary</span>
        )}
      </div>
      <p className="text-[10px] text-gray-500 leading-snug">{fmt.desc}</p>
    </button>
  )
}

// ---------------------------------------------------------------------------
// Export result display
// ---------------------------------------------------------------------------

function ExportResult({ result, format }: { result: HullExchangeResult | null | undefined; format: HullExchangeFormat }) {
  if (!result) return null

  const fmt = FORMATS.find(f => f.id === format)

  const handleDownload = () => {
    const suffix = result.hull_name || 'hull'
    if (format === '3dm') {
      const blob = base64ToBlob(result.content_base64 || '', 'application/octet-stream')
      downloadBlob(blob, `${suffix}.3dm`)
    } else if (format === 'dxf') {
      downloadText(result.content || '', `${suffix}.dxf`, 'application/dxf')
    } else if (format === 'iges') {
      downloadText(result.content || '', `${suffix}.igs`, 'application/iges')
    }
  }

  const sizeLabel = format === '3dm'
    ? `${result.n_bytes?.toLocaleString()} bytes`
    : `${result.n_chars?.toLocaleString()} chars`

  return (
    <div className={`rounded-lg border ${fmt?.borderColor || 'border-gray-700'} ${fmt?.bgColor || 'bg-gray-900'} p-3`}>
      <div className="flex items-center gap-2 mb-2">
        <CheckCircle size={13} className="text-green-400" />
        <span className="text-xs text-gray-200 font-medium">{fmt?.label} export ready</span>
        <span className="text-[10px] text-gray-500 ml-2">{sizeLabel}</span>
        <button
          onClick={handleDownload}
          className="ml-auto flex items-center gap-1 rounded border border-gray-600 bg-gray-800 hover:bg-gray-700 px-2 py-1 text-xs text-gray-200 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70"
        >
          <Download size={11} />
          Download .{fmt?.ext}
        </button>
      </div>
      {result.note && (
        <p className="text-[10px] text-gray-500 mt-1">{result.note}</p>
      )}
      {/* Preview for text formats */}
      {(format === 'dxf' || format === 'iges') && result.content && (
        <details className="mt-2">
          <summary className="text-[10px] text-gray-600 cursor-pointer hover:text-gray-400">
            Preview (first 500 chars)
          </summary>
          <pre className="mt-1 rounded bg-gray-950 p-2 text-[10px] text-gray-400 overflow-x-auto max-h-32">
            {result.content.slice(0, 500)}{result.content.length > 500 ? '\n…' : ''}
          </pre>
        </details>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export default function HullExchangePanel({ hullForm: hullFormProp, content }: HullExchangePanelProps) {
  // Backward-compatible content string: JSON.parse it and merge into hullForm.
  let _parsed: (HullForm & { hullForm?: HullForm }) | null = null
  if (content != null) {
    try { _parsed = JSON.parse(content) } catch { /* ignore */ }
  }
  const hullForm: HullForm | null | undefined = (_parsed && _parsed.sections) ? _parsed
    : (_parsed && _parsed.hullForm) ? _parsed.hullForm
    : hullFormProp
  const [format, setFormat] = useState<HullExchangeFormat>('dxf')
  const [useSplines, setUseSplines] = useState(true)
  const [results, setResults] = useState<Partial<Record<HullExchangeFormat, HullExchangeResult>>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const hasHullForm = Boolean(hullForm && hullForm.sections && hullForm.sections.length > 0)

  const handleExport = useCallback(async () => {
    if (!hasHullForm || !hullForm) return
    setLoading(true)
    setError(null)
    try {
      const args = {
        hull_form: hullForm,
        format,
        use_splines: useSplines,
      }
      const result = await callTool<HullExchangeResult>('marine_hull_exchange', args)
      if (result?.error) throw new Error(result.error)
      setResults(prev => ({ ...prev, [format]: result }))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [hullForm, format, useSplines, hasHullForm])

  return (
    <div className="flex flex-col gap-4 p-4 bg-gray-950 text-gray-200 rounded-xl min-w-[540px]">
      {/* Header */}
      <div className="flex items-center gap-2">
        <FileText size={18} className="text-green-400" />
        <span className="font-semibold text-gray-100">DXF / IGES / 3DM Exchange</span>
        <span className="text-xs text-gray-500 ml-auto">Hull curve export for Maxsurf / Rhino</span>
      </div>

      {/* Hull form status */}
      {!hasHullForm ? (
        <div className="flex items-center gap-2 rounded-lg border border-gray-700 bg-gray-900 p-3 text-sm text-gray-400">
          <ArrowRight size={13} className="text-gray-600" />
          Generate a hull form first using the Hull Form panel, then export here.
        </div>
      ) : (
        <div className="flex items-center gap-2 text-xs text-green-400 rounded-lg border border-green-900 bg-green-950/30 p-2">
          <CheckCircle size={12} />
          Hull form loaded: L={hullForm.L_m}m × B={hullForm.B_m}m × T={hullForm.T_m}m
          — {hullForm.n_sections} sections, Cb={hullForm.Cb?.toFixed(3)}
        </div>
      )}

      {/* Format selection */}
      <div className="flex flex-col gap-2">
        <p className="text-xs font-medium text-gray-400">Export format</p>
        {FORMATS.map(fmt => (
          <FormatCard
            key={fmt.id}
            fmt={fmt}
            selected={format === fmt.id}
            onSelect={setFormat}
          />
        ))}
      </div>

      {/* IGES options */}
      {format === 'iges' && (
        <label className="flex items-center gap-2 text-xs text-gray-400">
          <input
            type="checkbox"
            checked={useSplines}
            onChange={e => setUseSplines(e.target.checked)}
            className="rounded border-gray-600 bg-gray-800"
          />
          Use Entity 126 (Rational B-spline) curves
          <span className="text-gray-600 text-[10px]">uncheck for Entity 106 polylines (simpler, wider compat.)</span>
        </label>
      )}

      {/* Export button */}
      <button
        onClick={handleExport}
        disabled={loading || !hasHullForm}
        className="flex items-center justify-center gap-2 rounded-lg bg-green-800 hover:bg-green-700 disabled:opacity-40 px-4 py-2 text-sm font-medium text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70"
      >
        {loading ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
        {loading ? 'Exporting…' : `Export as ${format.toUpperCase()}`}
      </button>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-800 bg-red-950/40 p-3 text-sm text-red-300">
          <AlertTriangle size={14} />
          {error}
        </div>
      )}

      {/* Results for each format */}
      {Object.entries(results).map(([fmt, result]) => (
        <ExportResult key={fmt} result={result} format={fmt as HullExchangeFormat} />
      ))}

      {/* Standards note */}
      <div className="rounded border border-gray-800 bg-gray-900/50 p-3 text-[10px] text-gray-500 leading-relaxed">
        <span className="text-gray-400 font-semibold">Standards: </span>
        DXF — AutoCAD R2004 (AC1018) SPLINE entities.
        IGES — ASME Y14.26M-2012 / IGES 5.3 §4.126 (Rational B-spline curves).
        3DM — Rhino openNURBS v7 public specification.
        All formats include body-plan sections, design waterlines, and buttock lines.
      </div>
    </div>
  )
}
