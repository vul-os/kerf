/**
 * RPDDenturePanel — RPD / full denture with Kennedy classification + Applegate rules.
 *
 * Features:
 *  - Arch selector (mandibular/maxillary) + type (partial/complete)
 *  - FDI tooth selector for teeth to replace
 *  - Kennedy class display (auto-computed)
 *  - Applegate modification count
 *  - Clasp type picker
 *
 * Backend tool: dental_denture_design_v2
 *
 * References:
 *  - Kennedy E (1925) Dental Cosmos 67:1-9
 *  - Applegate OC (1954) J Prosthet Dent 4(3):350-7
 *  - McCracken's RPP 13th ed.
 */

import { useState, useMemo } from 'react'
import { useAuth } from '../../store/auth.js'

const API_URL = import.meta.env.VITE_API_URL || ''

// FDI teeth grouped by arch
const TEETH_MANDIBULAR = [
  { fdi: '31', label: '31' }, { fdi: '32', label: '32' }, { fdi: '33', label: '33' },
  { fdi: '34', label: '34' }, { fdi: '35', label: '35' }, { fdi: '36', label: '36' },
  { fdi: '37', label: '37' }, { fdi: '38', label: '38' },
  { fdi: '41', label: '41' }, { fdi: '42', label: '42' }, { fdi: '43', label: '43' },
  { fdi: '44', label: '44' }, { fdi: '45', label: '45' }, { fdi: '46', label: '46' },
  { fdi: '47', label: '47' }, { fdi: '48', label: '48' },
]
const TEETH_MAXILLARY = [
  { fdi: '11', label: '11' }, { fdi: '12', label: '12' }, { fdi: '13', label: '13' },
  { fdi: '14', label: '14' }, { fdi: '15', label: '15' }, { fdi: '16', label: '16' },
  { fdi: '17', label: '17' }, { fdi: '18', label: '18' },
  { fdi: '21', label: '21' }, { fdi: '22', label: '22' }, { fdi: '23', label: '23' },
  { fdi: '24', label: '24' }, { fdi: '25', label: '25' }, { fdi: '26', label: '26' },
  { fdi: '27', label: '27' }, { fdi: '28', label: '28' },
]

const KENNEDY_COLORS = {
  'Class I': 'bg-red-500/15 border-red-400/50 text-red-200',
  'Class II': 'bg-orange-500/15 border-orange-400/50 text-orange-200',
  'Class III': 'bg-amber-500/15 border-amber-400/50 text-amber-200',
  'Class IV': 'bg-violet-500/15 border-violet-400/50 text-violet-200',
  'complete': 'bg-emerald-500/15 border-emerald-400/50 text-emerald-200',
}

const KENNEDY_DESCRIPTIONS = {
  'Class I': 'Bilateral free-end saddles — both sides, posterior missing',
  'Class II': 'Unilateral free-end saddle — one side, posterior missing',
  'Class III': 'Bounded saddle — teeth present on both sides of gap',
  'Class IV': 'Anterior bounded, crosses midline (no modifications)',
  'complete': 'Complete denture — all teeth replaced',
}

// Client-side Kennedy classification (mirrors denture_v2.py logic)
function classifyKennedy(selectedFdi, arch, type) {
  if (type === 'complete' || selectedFdi.length === 0) return 'complete'

  const quads = new Set(selectedFdi.map((fdi) => fdi[0]))
  const toothNums = selectedFdi.map((fdi) => [parseInt(fdi[0], 10), parseInt(fdi[1], 10)])

  const hasPosterior = toothNums.some(([, n]) => n >= 6)
  const hasBilateral = quads.size >= 2
  const hasAnterior = toothNums.some(([, n]) => n >= 1 && n <= 3)
  const crossesMidline = new Set(selectedFdi.map((fdi) => fdi[0])).size >= 2

  if (hasAnterior && crossesMidline && !hasPosterior) return 'Class IV'
  if (hasPosterior && hasBilateral) return 'Class I'
  if (hasPosterior && !hasBilateral) return 'Class II'
  return 'Class III'
}

export default function RPDDenturePanel({ projectId, content }) {
  const { accessToken } = useAuth()
  // Parse content string (from panelRegistry) to seed defaults
  const _defaults = (() => { try { return content ? JSON.parse(content) : {} } catch { return {} } })()

  const [arch, setArch]               = useState('mandibular')
  const [type, setType]               = useState('partial')
  const [selectedFdi, setSelectedFdi] = useState(['36', '46'])
  const [claspType, setClaspType]     = useState('circumferential')
  const [running, setRunning]         = useState(false)
  const [result, setResult]           = useState(null)
  const [error, setError]             = useState(null)

  const teethList = arch === 'mandibular' ? TEETH_MANDIBULAR : TEETH_MAXILLARY
  const kennedyClass = useMemo(() => classifyKennedy(selectedFdi, arch, type), [selectedFdi, arch, type])
  const kennedyColor = KENNEDY_COLORS[kennedyClass] || KENNEDY_COLORS.complete

  function toggleTooth(fdi) {
    setSelectedFdi((prev) =>
      prev.includes(fdi) ? prev.filter((f) => f !== fdi) : [...prev, fdi]
    )
    setResult(null)
  }

  async function handleRun() {
    if (selectedFdi.length === 0) { setError('Select at least one tooth to replace.'); return }
    setRunning(true)
    setResult(null)
    setError(null)
    try {
      const body = {
        tool: 'dental_denture_design_v2',
        args: {
          arch,
          type,
          teeth_to_replace_fdi: selectedFdi,
          clasp_type: type === 'partial' ? claspType : 'circumferential',
        },
      }
      const res = await fetch(`${API_URL}/api/tools/call`, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          ...(accessToken ? { authorization: `Bearer ${accessToken}` } : {}),
        },
        body: JSON.stringify(body),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) setError(data?.error || `HTTP ${res.status}`)
      else setResult(data)
    } catch (err) {
      setError(err?.message || String(err))
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="flex flex-col gap-4 p-4 text-ink-100" data-testid="rpd-denture-panel">
      {/* Header */}
      <div className="flex items-center gap-2">
        <span className="text-[11px] font-mono uppercase tracking-widest text-ink-400">RPD / Denture</span>
        <span className="ml-auto text-[10px] text-ink-600 font-mono">dental_denture_design_v2</span>
      </div>

      {/* Arch + type */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-[11px] text-ink-400 mb-1.5">Arch</label>
          <div className="flex gap-1">
            {['mandibular', 'maxillary'].map((a) => (
              <button
                key={a}
                type="button"
                onClick={() => { setArch(a); setSelectedFdi([]); setResult(null) }}
                className={`flex-1 py-1.5 rounded text-xs font-medium border transition-colors ${
                  arch === a
                    ? 'bg-rose-500/20 border-rose-400/60 text-rose-200'
                    : 'bg-ink-800 border-ink-700 text-ink-300 hover:bg-ink-700'
                }`}
              >
                {a}
              </button>
            ))}
          </div>
        </div>
        <div>
          <label className="block text-[11px] text-ink-400 mb-1.5">Type</label>
          <div className="flex gap-1">
            {['partial', 'complete'].map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => { setType(t); setResult(null) }}
                className={`flex-1 py-1.5 rounded text-xs font-medium border transition-colors ${
                  type === t
                    ? 'bg-rose-500/20 border-rose-400/60 text-rose-200'
                    : 'bg-ink-800 border-ink-700 text-ink-300 hover:bg-ink-700'
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Kennedy class display */}
      <div className={`rounded border px-3 py-2 text-xs ${kennedyColor}`}>
        <div className="font-semibold">{kennedyClass}</div>
        <div className="text-[10px] opacity-80 mt-0.5">{KENNEDY_DESCRIPTIONS[kennedyClass]}</div>
        {kennedyClass === 'Class IV' && (
          <div className="text-[9px] mt-0.5 opacity-60">Applegate Rule 8: no modifications apply</div>
        )}
      </div>

      {/* Tooth selector */}
      <div>
        <label className="block text-[11px] text-ink-400 mb-1.5">
          Teeth to replace ({selectedFdi.length} selected)
        </label>
        <div className="grid grid-cols-8 gap-1">
          {teethList.map(({ fdi, label }) => (
            <button
              key={fdi}
              type="button"
              onClick={() => toggleTooth(fdi)}
              className={`py-1 rounded text-[10px] font-mono border transition-colors ${
                selectedFdi.includes(fdi)
                  ? 'bg-rose-500/25 border-rose-400/60 text-rose-200'
                  : 'bg-ink-800 border-ink-700 text-ink-500 hover:bg-ink-700'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Clasp type (RPD only) */}
      {type === 'partial' && (
        <div>
          <label className="block text-[11px] text-ink-400 mb-1.5">Clasp type</label>
          <div className="flex gap-1">
            {['circumferential', 'I_bar', 'T_bar'].map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => setClaspType(c)}
                className={`flex-1 py-1.5 rounded text-[10px] font-medium border transition-colors ${
                  claspType === c
                    ? 'bg-rose-500/20 border-rose-400/60 text-rose-200'
                    : 'bg-ink-800 border-ink-700 text-ink-400 hover:bg-ink-700'
                }`}
              >
                {c.replace('_', '-')}
              </button>
            ))}
          </div>
          <p className="mt-0.5 text-[9px] text-ink-600">McCracken 13e Ch 7 — direct retainer types</p>
        </div>
      )}

      {/* Run */}
      <button
        type="button"
        onClick={handleRun}
        disabled={running || selectedFdi.length === 0}
        className="flex items-center justify-center gap-2 px-4 py-2 rounded bg-rose-500/20 border border-rose-400/50 text-rose-200 text-xs font-medium hover:bg-rose-500/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {running ? (
          <>
            <span className="w-3 h-3 border-2 border-rose-400 border-t-transparent rounded-full animate-spin" />
            Designing…
          </>
        ) : (
          `Design ${type} ${arch} denture`
        )}
      </button>

      {/* Result */}
      {result && (
        <div className="rounded border border-rose-700/50 bg-rose-950/30 p-3 text-[11px] font-mono text-rose-300 space-y-1" data-testid="rpd-denture-result">
          <div className="text-rose-400 font-semibold mb-1">
            {result.kennedy_class !== 'complete' ? `Kennedy ${result.kennedy_class}` : 'Complete denture'} designed
          </div>
          {result.kennedy_class && <div>class: <span className="text-rose-200">{result.kennedy_class}</span></div>}
          {result.modification_count != null && result.modification_count > 0 && (
            <div>modifications: <span className="text-rose-200">{result.modification_count}</span>
              <span className="text-ink-500 ml-1">(Applegate Rule 6)</span>
            </div>
          )}
          {result.teeth_replaced != null && <div>teeth replaced: <span className="text-rose-200">{result.teeth_replaced}</span></div>}
          {result.clasp_count != null && <div>clasps: <span className="text-rose-200">{result.clasp_count}</span></div>}
          {result.bite_height_mm != null && <div>OVD: <span className="text-rose-200">{result.bite_height_mm} mm</span></div>}
          {result.base_vertices != null && (
            <div>base: <span className="text-rose-200">{result.base_vertices} V / {result.base_triangles} F</span></div>
          )}
          {result.honest_caveat && <div className="text-amber-500/80 text-[10px] mt-1">{result.honest_caveat}</div>}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="rounded border border-red-700/50 bg-red-950/30 p-3 text-[11px] font-mono text-red-300" data-testid="rpd-denture-error">
          {error}
        </div>
      )}

      <p className="text-[10px] text-ink-600">
        Kennedy classification + Applegate (1954) 8 rules. NOT FDA-cleared.
        Clinical fitting and prosthodontist approval required.
      </p>
    </div>
  )
}
