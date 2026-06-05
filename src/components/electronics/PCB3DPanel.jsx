// PCB3DPanel.jsx — 3D PCB editor panel: STEP body import + clearance DRC.
//
// Provides: component STEP body import (bounding-box extraction), 3D
// body-clearance DRC (Altium §7.4), and IDF round-trip validation.
//
// Backend contracts:
//   POST /api/llm-tools/pcb_step_import_body    {step_text}
//   POST /api/llm-tools/pcb_3d_clearance_check  {circuit_json, min_clearance_mm}
//   POST /api/llm-tools/validate_idf_roundtrip  {circuit_json}
//   POST /api/llm-tools/export_idf              {circuit_json}
//   POST /api/llm-tools/export_board_step       {circuit_json}
//
// References: Altium 3D PCB Design Guide §7.4; IPC-7351B §4.5; STEP AP214/AP242.
//
// Props:
//   circuitJson — array of CircuitJSON elements (board)
//   onClose     — () => void

import { useCallback, useState } from 'react'
import { Layers3, AlertTriangle, CheckCircle2, X, RefreshCw, Upload, Download } from 'lucide-react'

// ── Demo circuit JSON for offline mode ───────────────────────────────────────

const DEMO_CIRCUIT_JSON = [
  { type: 'pcb_board', width: 100, height: 80, center_x: 50, center_y: 40 },
  { type: 'source_component', source_component_id: 'sc_u1', name: 'U1', footprint: 'TQFP-32' },
  { type: 'source_component', source_component_id: 'sc_r1', name: 'R1', footprint: 'R_0402' },
  { type: 'pcb_component', pcb_component_id: 'cmp_u1', source_component_id: 'sc_u1',
    x: 50, y: 40, rotation: 0, layer: 'top_copper' },
  { type: 'pcb_component', pcb_component_id: 'cmp_r1', source_component_id: 'sc_r1',
    x: 20, y: 20, rotation: 0, layer: 'top_copper' },
]

// ── Helpers ──────────────────────────────────────────────────────────────────

async function apiPost(endpoint, body) {
  try {
    const r = await fetch(`/api/llm-tools/${endpoint}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    })
    return r.ok ? r.json() : { ok: false, error: `HTTP ${r.status}` }
  } catch (e) {
    return { ok: false, error: e.message }
  }
}

function ViolationRow({ v }) {
  const isError = v.violation_type === 'body_intersection' || v.severity === 'error'
  return (
    <div className="flex items-start gap-2 px-2 py-1.5 text-[11px]">
      <AlertTriangle size={12} className={isError ? 'text-red-400 mt-0.5 shrink-0' : 'text-yellow-400 mt-0.5 shrink-0'} />
      <div className="min-w-0">
        <span className="text-gray-300">{v.comp_a} ↔ {v.comp_b}</span>
        <span className="ml-2 text-gray-500">gap: {Number(v.gap_mm).toFixed(3)} mm (min: {v.required_mm} mm)</span>
        <div className="text-[10px] text-gray-600">{v.violation_type}</div>
      </div>
    </div>
  )
}

// ── Main panel ───────────────────────────────────────────────────────────────

export default function PCB3DPanel({ circuitJson, onClose }) {
  const [tab, setTab] = useState('clearance')
  const [loading, setLoading] = useState(false)
  const [clearanceResult, setClearanceResult] = useState(null)
  const [idfResult, setIdfResult]             = useState(null)
  const [stepImportResult, setStepImportResult] = useState(null)
  const [stepText, setStepText]               = useState('')
  const [minClearance, setMinClearance]       = useState('0.2')
  const [offline, setOffline]                 = useState(false)

  const cj = circuitJson ?? DEMO_CIRCUIT_JSON

  const runClearanceCheck = useCallback(async () => {
    setLoading(true)
    const r = await apiPost('pcb_3d_clearance_check', {
      circuit_json: cj,
      min_clearance_mm: parseFloat(minClearance) || 0.2,
    })
    setLoading(false)
    if (!r || r.error) { setOffline(true); return }
    setClearanceResult(r)
  }, [cj, minClearance])

  const runIdfRoundtrip = useCallback(async () => {
    setLoading(true)
    const r = await apiPost('validate_idf_roundtrip', { circuit_json: cj })
    setLoading(false)
    if (!r || r.error) { setOffline(true); return }
    setIdfResult(r)
  }, [cj])

  const runStepImport = useCallback(async () => {
    if (!stepText.trim()) return
    setLoading(true)
    const r = await apiPost('pcb_step_import_body', { step_text: stepText })
    setLoading(false)
    if (!r || r.error) { setOffline(true); return }
    setStepImportResult(r)
  }, [stepText])

  const TABS = [
    { id: 'clearance', label: '3D Clearance' },
    { id: 'step', label: 'STEP Import' },
    { id: 'idf', label: 'IDF Bridge' },
  ]

  return (
    <div
      data-testid="pcb-3d-panel"
      className="absolute top-12 right-4 w-96 bg-[#12122a] border border-white/10 rounded-xl shadow-2xl z-50 flex flex-col max-h-[80vh] overflow-hidden"
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-white/10">
        <Layers3 size={15} className="text-violet-400" />
        <span className="text-sm font-semibold text-white">3D PCB Editor</span>
        <button
          data-testid="pcb-3d-close"
          onClick={onClose}
          className="ml-auto p-1 rounded hover:bg-white/10 text-gray-500 hover:text-white transition-colors"
        >
          <X size={14} />
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 px-3 pt-2">
        {TABS.map(({ id, label }) => (
          <button
            key={id}
            data-testid={`pcb3d-tab-${id}`}
            onClick={() => setTab(id)}
            className={[
              'px-3 py-1.5 rounded-md text-[11px] font-medium transition-colors',
              tab === id ? 'bg-violet-600 text-white' : 'text-gray-400 hover:text-white hover:bg-white/10',
            ].join(' ')}
          >
            {label}
          </button>
        ))}
      </div>

      {offline && (
        <div className="mx-3 mt-2 px-3 py-2 bg-yellow-900/30 border border-yellow-700/40 rounded-lg text-[11px] text-yellow-300">
          Backend offline — demo mode (3D clearance + STEP import tools wired)
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3" data-testid="pcb3d-content">
        {/* ── 3D Clearance tab ────────────────────────────────────────── */}
        {tab === 'clearance' && (
          <div className="space-y-3">
            <div className="text-[11px] text-gray-400 px-1">
              3D body-to-body clearance DRC (Altium §7.4 + IPC-7351B §4.5).
              Component bodies are approximated as axis-aligned bounding boxes.
            </div>

            <div className="flex items-center gap-2">
              <label className="text-[11px] text-gray-400 shrink-0">Min clearance (mm):</label>
              <input
                data-testid="pcb3d-min-clearance"
                type="number"
                value={minClearance}
                onChange={(e) => setMinClearance(e.target.value)}
                step="0.05"
                min="0"
                className="w-20 px-2 py-1 bg-black/30 border border-white/10 rounded text-[11px] text-white"
              />
            </div>

            <button
              data-testid="pcb3d-clearance-btn"
              onClick={runClearanceCheck}
              disabled={loading}
              className="w-full py-2 rounded-lg bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white text-xs font-medium flex items-center justify-center gap-2 transition-colors"
            >
              {loading ? <RefreshCw size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
              Run 3D Clearance DRC
            </button>

            {clearanceResult && (
              <div data-testid="pcb3d-clearance-result" className="space-y-1">
                <div className={`text-[11px] font-medium ${clearanceResult.violation_count === 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {clearanceResult.violation_count === 0
                    ? `✓ No violations — ${clearanceResult.component_count} components checked`
                    : `✗ ${clearanceResult.violation_count} violation(s) — ${clearanceResult.pairs_checked} pairs checked`}
                </div>
                {(clearanceResult.violations ?? []).map((v, idx) => (
                  <ViolationRow key={idx} v={v} />
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── STEP import tab ──────────────────────────────────────────── */}
        {tab === 'step' && (
          <div className="space-y-3">
            <div className="text-[11px] text-gray-400 px-1">
              Import a vendor STEP model (AP214/AP242) and extract its bounding-box
              dimensions for use in clearance DRC.
            </div>

            <textarea
              data-testid="pcb3d-step-text"
              value={stepText}
              onChange={(e) => setStepText(e.target.value)}
              placeholder="Paste STEP file content here (ISO-10303-21 format)…"
              className="w-full h-28 px-3 py-2 bg-black/30 border border-white/10 rounded-lg text-[11px] text-gray-300 placeholder-gray-600 resize-none font-mono"
            />

            <button
              data-testid="pcb3d-step-import-btn"
              onClick={runStepImport}
              disabled={loading || !stepText.trim()}
              className="w-full py-2 rounded-lg bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white text-xs font-medium flex items-center justify-center gap-2 transition-colors"
            >
              {loading ? <RefreshCw size={12} className="animate-spin" /> : <Upload size={12} />}
              Extract Body Dimensions
            </button>

            {stepImportResult && (
              <div data-testid="pcb3d-step-import-result" className="px-3 py-2 bg-violet-900/30 border border-violet-700/40 rounded-lg space-y-1 text-[11px]">
                <div className="font-medium text-violet-300">Body extracted</div>
                <div className="text-gray-300">
                  X: {stepImportResult.x_mm} mm · Y: {stepImportResult.y_mm} mm · Z: {stepImportResult.z_mm} mm
                </div>
                <div className="text-gray-500">method: {stepImportResult.method}</div>
              </div>
            )}

            <div className="text-[10px] text-gray-600 px-1">
              STEP AP214 ISO 10303-214 / AP242 ISO 10303-242 §4.3.
              pythonOCC required for accurate solid geometry; CARTESIAN_POINT
              scan used as fallback.
            </div>
          </div>
        )}

        {/* ── IDF Bridge tab ───────────────────────────────────────────── */}
        {tab === 'idf' && (
          <div className="space-y-3">
            <div className="text-[11px] text-gray-400 px-1">
              IDF 3.0 ECAD↔MCAD round-trip validation (Altium MCAD CoDesigner §6).
              Export board to IDF, re-import, and verify structural consistency.
            </div>

            <button
              data-testid="pcb3d-idf-roundtrip-btn"
              onClick={runIdfRoundtrip}
              disabled={loading}
              className="w-full py-2 rounded-lg bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white text-xs font-medium flex items-center justify-center gap-2 transition-colors"
            >
              {loading ? <RefreshCw size={12} className="animate-spin" /> : <Download size={12} />}
              Validate IDF Round-Trip
            </button>

            {idfResult && (
              <div data-testid="pcb3d-idf-result" className="space-y-1">
                <div className={`text-[11px] font-medium ${idfResult.pass ? 'text-emerald-400' : 'text-red-400'}`}>
                  {idfResult.pass ? '✓ IDF round-trip valid' : `✗ ${idfResult.violations?.length ?? 0} violation(s)`}
                </div>
                <div className="text-[10px] text-gray-500 px-1">
                  Outline: {idfResult.outline_vertex_count} verts ·
                  Holes: {idfResult.hole_count} ·
                  Components: {idfResult.placement_count} ·
                  Packages: {idfResult.package_count}
                </div>
                {(idfResult.violations ?? []).map((v, idx) => (
                  <div key={idx} className="flex items-start gap-2 px-2 py-1 text-[11px]">
                    <AlertTriangle size={12} className="text-yellow-400 mt-0.5 shrink-0" />
                    <span className="text-gray-300">{v}</span>
                  </div>
                ))}
              </div>
            )}

            <div className="text-[10px] text-gray-600 px-1">
              ProSTEP IDF 3.0 §4.3-5.2. Re-import validates: board outline ≥3 verts,
              package heights &gt;0, PLACEMENT packages in .emp library.
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
