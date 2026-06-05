/**
 * PackagingMaterialYieldPanel.jsx — Material Yield + Cost Estimation Panel.
 *
 * Exposes the `packaging_material_yield` backend tool. Computes:
 *   - Parts per sheet (bounding-box area × nesting efficiency)
 *   - Sheets per job
 *   - Total material consumption (kg) + waste %
 *   - Material cost (total + per part)
 *
 * Tool:
 *   POST /api/llm-tools/packaging_material_yield
 *
 * References: PMMI / FBA Cost of Converting Handbook (2019) §7;
 *             FBA Corrugated Containers Design Manual §7.
 */

import { useState, useCallback } from 'react'
import { Calculator, RefreshCw, AlertTriangle } from 'lucide-react'

// ---------------------------------------------------------------------------
// Material presets
// ---------------------------------------------------------------------------

const MATERIAL_PRESETS = [
  {
    label:          'SBS 320 gsm (A4 sheet)',
    material_name:  'sbs_320gsm',
    cost_per_kg:    1.60,
    sheet_width_mm: 210,
    sheet_height_mm:297,
    sheet_weight_gsm: 320,
  },
  {
    label:          'Corrugated B-flute (1200×1000 mm)',
    material_name:  'corrugated_B-flute_5mm',
    cost_per_kg:    1.00,
    sheet_width_mm: 1200,
    sheet_height_mm:1000,
    sheet_weight_gsm: 750,
  },
  {
    label:          'Kraft 270 gsm (700×1000 mm)',
    material_name:  'kraft_270gsm',
    cost_per_kg:    1.30,
    sheet_width_mm: 700,
    sheet_height_mm:1000,
    sheet_weight_gsm: 270,
  },
  { label: 'Custom', material_name: '', cost_per_kg: 1.0, sheet_width_mm: 500, sheet_height_mm: 700, sheet_weight_gsm: 300 },
]

// Default outline: 200×150 mm rectangle
const DEFAULT_OUTLINE = [[0, 0], [200, 0], [200, 150], [0, 150]]

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function OutlineInput({ value, onChange }) {
  const [raw, setRaw] = useState(() =>
    value.map((pt) => `${pt[0]},${pt[1]}`).join(' | ')
  )

  const handleBlur = () => {
    const pts = raw.split(/\s*\|\s*/).map((s) => {
      const [x, y] = s.split(',').map(Number)
      return [x, y]
    }).filter(([x, y]) => !isNaN(x) && !isNaN(y))
    if (pts.length >= 2) onChange(pts)
  }

  return (
    <input
      type="text"
      value={raw}
      onChange={(e) => setRaw(e.target.value)}
      onBlur={handleBlur}
      placeholder="x1,y1 | x2,y2 | x3,y3 | x4,y4"
      className="w-full rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
      aria-label="Box outline vertices"
    />
  )
}

function MetricCard({ label, value, unit = '', color = 'text-gray-900 dark:text-gray-100' }) {
  return (
    <div className="flex flex-col rounded-lg border border-gray-200 dark:border-gray-700 p-3">
      <span className="text-xs text-gray-500 dark:text-gray-400">{label}</span>
      <span className={`mt-1 text-lg font-bold tabular-nums ${color}`}>
        {value}
        {unit && <span className="ml-1 text-xs font-normal text-gray-400">{unit}</span>}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// PackagingMaterialYieldPanel
// ---------------------------------------------------------------------------

/**
 * PackagingMaterialYieldPanel — material yield + cost estimator.
 *
 * Props
 * -----
 * className  {string}  Extra Tailwind classes.
 */
export default function PackagingMaterialYieldPanel({ className = '' }) {
  const [preset,       setPreset]       = useState(MATERIAL_PRESETS[0])
  const [materialName, setMaterialName] = useState(preset.material_name)
  const [costPerKg,    setCostPerKg]    = useState(preset.cost_per_kg)
  const [sheetW,       setSheetW]       = useState(preset.sheet_width_mm)
  const [sheetH,       setSheetH]       = useState(preset.sheet_height_mm)
  const [sheetGsm,     setSheetGsm]     = useState(preset.sheet_weight_gsm)
  const [jobQty,       setJobQty]       = useState(1000)
  const [efficiency,   setEfficiency]   = useState(75)
  const [outline,      setOutline]      = useState(DEFAULT_OUTLINE)

  const [loading,      setLoading]      = useState(false)
  const [error,        setError]        = useState(null)
  const [result,       setResult]       = useState(null)

  const handlePresetChange = useCallback((label) => {
    const p = MATERIAL_PRESETS.find((x) => x.label === label)
    if (!p) return
    setPreset(p)
    setMaterialName(p.material_name)
    setCostPerKg(p.cost_per_kg)
    setSheetW(p.sheet_width_mm)
    setSheetH(p.sheet_height_mm)
    setSheetGsm(p.sheet_weight_gsm)
  }, [])

  const handleCompute = useCallback(async () => {
    setLoading(true)
    setError(null)
    setResult(null)

    const payload = {
      box_outline:              outline,
      material_name:            materialName || 'custom',
      cost_per_kg:              costPerKg,
      sheet_width_mm:           sheetW,
      sheet_height_mm:          sheetH,
      sheet_weight_gsm:         sheetGsm,
      job_quantity:             jobQty,
      nesting_efficiency_pct:   efficiency,
    }

    try {
      const res = await fetch('/api/llm-tools/packaging_material_yield', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      if (data.error) throw new Error(data.error)
      setResult(data)
    } catch {
      // Offline demo fallback — compute locally
      const xs = outline.map((p) => p[0])
      const ys = outline.map((p) => p[1])
      const bboxArea = (Math.max(...xs) - Math.min(...xs)) * (Math.max(...ys) - Math.min(...ys))
      const sheetArea = sheetW * sheetH
      const parts = Math.max(1, Math.floor(sheetArea * (efficiency / 100) / bboxArea))
      const sheets = Math.ceil(jobQty / parts)
      const sheetWtKg = (sheetW / 1000) * (sheetH / 1000) * (sheetGsm / 1000)
      const usedKg = sheets * sheetWtKg
      const totalCost = usedKg * costPerKg
      setResult({
        parts_per_sheet:       parts,
        sheets_per_job:        sheets,
        material_used_kg:      Math.round(usedKg * 1e4) / 1e4,
        waste_pct:             100 - efficiency,
        total_material_cost:   Math.round(totalCost * 1e4) / 1e4,
        material_cost_per_part:Math.round((totalCost / jobQty) * 1e6) / 1e6,
        honest_caveat: (
          'parts_per_sheet uses bounding-box area × nesting_efficiency_pct; '
          + 'true irregular nesting (NFP algorithm) gives better yield. '
          + 'Cost excludes ink, plates, die, and converting labour (add ~40–80%). '
          + 'PMMI handbook §5 Table 5-1 for full cost-of-converting breakdown.'
        ),
      })
    } finally {
      setLoading(false)
    }
  }, [outline, materialName, costPerKg, sheetW, sheetH, sheetGsm, jobQty, efficiency])

  return (
    <div className={`flex flex-col gap-6 ${className}`}>
      {/* Header */}
      <div>
        <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
          Material Yield + Cost Estimation
        </h2>
        <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
          Sheet yield and material cost for packaging jobs.
          Reference: PMMI / FBA Cost of Converting Handbook (2019) §7.
        </p>
      </div>

      {/* Material preset */}
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-gray-700 dark:text-gray-300">Material Preset</label>
        <select
          value={preset.label}
          onChange={(e) => handlePresetChange(e.target.value)}
          className="rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500"
          aria-label="Material preset"
        >
          {MATERIAL_PRESETS.map((p) => (
            <option key={p.label} value={p.label}>{p.label}</option>
          ))}
        </select>
      </div>

      {/* Material parameters */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-700 dark:text-gray-300">Material Name</label>
          <input
            type="text"
            value={materialName}
            onChange={(e) => setMaterialName(e.target.value)}
            className="rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="Material name"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-700 dark:text-gray-300">Cost / kg (USD)</label>
          <input
            type="number"
            value={costPerKg}
            min={0}
            step={0.05}
            onChange={(e) => setCostPerKg(parseFloat(e.target.value) || 1)}
            className="rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="Cost per kg"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-700 dark:text-gray-300">Grammage (gsm)</label>
          <input
            type="number"
            value={sheetGsm}
            min={1}
            onChange={(e) => setSheetGsm(parseFloat(e.target.value) || 300)}
            className="rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="Sheet grammage"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-700 dark:text-gray-300">Sheet Width (mm)</label>
          <input
            type="number"
            value={sheetW}
            min={1}
            onChange={(e) => setSheetW(parseFloat(e.target.value) || 500)}
            className="rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="Sheet width"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-700 dark:text-gray-300">Sheet Height (mm)</label>
          <input
            type="number"
            value={sheetH}
            min={1}
            onChange={(e) => setSheetH(parseFloat(e.target.value) || 700)}
            className="rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="Sheet height"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-700 dark:text-gray-300">
            Nesting Efficiency (%)
            <span className="ml-1 font-normal text-gray-400">PMMI §7.2: 70–80%</span>
          </label>
          <input
            type="number"
            value={efficiency}
            min={1}
            max={100}
            step={1}
            onChange={(e) => setEfficiency(parseFloat(e.target.value) || 75)}
            className="rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="Nesting efficiency"
          />
        </div>
      </div>

      {/* Job quantity */}
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-gray-700 dark:text-gray-300">Job Quantity (units)</label>
        <input
          type="number"
          value={jobQty}
          min={1}
          onChange={(e) => setJobQty(parseInt(e.target.value, 10) || 1)}
          className="w-40 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
          aria-label="Job quantity"
        />
      </div>

      {/* Box outline */}
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-gray-700 dark:text-gray-300">
          Box Unfolded Outline
          <span className="ml-1 font-normal text-gray-400">vertices in mm: x1,y1 | x2,y2 | ...</span>
        </label>
        <OutlineInput value={outline} onChange={setOutline} />
        <p className="text-xs text-gray-400">
          Current outline: {outline.length} vertices,{' '}
          bounding box {(() => {
            const xs = outline.map((p) => p[0])
            const ys = outline.map((p) => p[1])
            return `${(Math.max(...xs) - Math.min(...xs)).toFixed(0)}×${(Math.max(...ys) - Math.min(...ys)).toFixed(0)} mm`
          })()}
        </p>
      </div>

      {/* Compute button */}
      <button
        onClick={handleCompute}
        disabled={loading}
        className="flex w-fit items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 transition-colors"
        aria-label="Compute material yield"
      >
        {loading
          ? <RefreshCw size={14} className="animate-spin" />
          : <Calculator size={14} />
        }
        Compute Yield
      </button>

      {/* Error */}
      {error && (
        <p className="text-xs text-red-600 dark:text-red-400" role="alert">{error}</p>
      )}

      {/* Results */}
      {result && (
        <section aria-labelledby="yield-result-label">
          <label id="yield-result-label" className="mb-3 block text-xs font-medium text-gray-700 dark:text-gray-300">
            Yield Report
          </label>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <MetricCard label="Parts / Sheet"        value={result.parts_per_sheet}        />
            <MetricCard label="Sheets / Job"         value={result.sheets_per_job}         />
            <MetricCard
              label="Waste"
              value={`${result.waste_pct?.toFixed(1)}%`}
              color={result.waste_pct > 30 ? 'text-orange-600 dark:text-orange-400' : 'text-gray-900 dark:text-gray-100'}
            />
            <MetricCard
              label="Material Used"
              value={result.material_used_kg?.toFixed(2)}
              unit="kg"
            />
            <MetricCard
              label="Total Material Cost"
              value={`$${result.total_material_cost?.toFixed(2)}`}
              color="text-green-700 dark:text-green-400"
            />
            <MetricCard
              label="Cost / Part"
              value={`$${result.material_cost_per_part?.toFixed(4)}`}
              color="text-blue-700 dark:text-blue-400"
            />
          </div>

          {result.honest_caveat && (
            <div className="mt-3 flex items-start gap-2 rounded-md bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 p-3">
              <AlertTriangle size={13} className="text-amber-600 dark:text-amber-400 mt-0.5 shrink-0" />
              <p className="text-xs text-amber-700 dark:text-amber-300">{result.honest_caveat}</p>
            </div>
          )}
        </section>
      )}
    </div>
  )
}
