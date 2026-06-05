// PCBThermalPanel.jsx — Board-level PCB thermal analysis panel.
//
// Provides: 2D finite-difference steady-state thermal map, hotspot
// identification, copper+via recommendation engine, and junction
// temperature derating check.
//
// Backend contracts:
//   POST /api/llm-tools/board_thermal_map       {width_m, height_m, copper_coverage,
//                                                components:[{ref,x_m,y_m,power_w,theta_jc}],
//                                                ambient_c, h_conv, nx, ny}
//   POST /api/llm-tools/board_thermal_recommend {board, target_delta_t_c}
//
// References:
//   IPC-2152 §6: board thermal design guidelines
//   Delphi Thermal Desktop circular spreading resistance approximation
//   Incropera "Fundamentals of Heat and Mass Transfer" 7e §6
//
// Props:
//   onClose — () => void

import { useCallback, useState } from 'react'
import { Thermometer, AlertTriangle, CheckCircle2, X, RefreshCw, Zap } from 'lucide-react'

// ── Helpers ───────────────────────────────────────────────────────────────────

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

const DEFAULT_BOARD = {
  width_m: 0.1,
  height_m: 0.1,
  copper_coverage: 0.4,
  ambient_c: 25,
  h_conv: 10,
  epsilon: 0.9,
  nx: 20,
  ny: 20,
}

const DEFAULT_COMPONENTS = [
  { ref: 'U1', x_m: 0.05, y_m: 0.05, power_w: 2.0, theta_jc: 15.0, tj_max_c: 125.0 },
  { ref: 'U2', x_m: 0.02, y_m: 0.08, power_w: 0.5, theta_jc: 30.0, tj_max_c: 150.0 },
]

function ComponentResult({ comp }) {
  const overLimit = comp.over_limit
  return (
    <div className={`px-3 py-2 rounded-lg text-[11px] ${overLimit ? 'bg-red-900/20 border border-red-700/40' : 'bg-white/5'}`}>
      <div className="flex items-center gap-2">
        <span className="font-medium text-white">{comp.ref}</span>
        {overLimit && <AlertTriangle size={11} className="text-red-400" />}
        <span className="ml-auto text-gray-400">Tj: <span className={overLimit ? 'text-red-400 font-medium' : 'text-white'}>{Number(comp.Tj_c ?? comp.tj_c).toFixed(1)} °C</span></span>
      </div>
      {comp.margin_c != null && (
        <div className="text-[10px] text-gray-500 mt-0.5">
          margin: {Number(comp.margin_c).toFixed(1)} °C
          {comp.T_board_c != null && <span className="ml-2">T_board: {Number(comp.T_board_c).toFixed(1)} °C</span>}
        </div>
      )}
    </div>
  )
}

// ── Mini heat map renderer ────────────────────────────────────────────────────

function HeatMap({ T_field, nx, ny, peak_ij }) {
  if (!T_field) return null
  const all = T_field.flatMap((row) => row)
  const tMin = Math.min(...all)
  const tMax = Math.max(...all)
  const range = tMax - tMin || 1

  return (
    <div
      data-testid="thermal-heatmap"
      className="relative"
      style={{ width: '100%', aspectRatio: `${nx}/${ny}` }}
    >
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${nx}, 1fr)`,
          gap: 0,
          width: '100%',
          height: '100%',
        }}
      >
        {T_field.map((row, j) =>
          row.map((t, i) => {
            const norm = (t - tMin) / range  // 0..1
            // Blue→Yellow→Red gradient
            const r = Math.round(255 * Math.min(1, norm * 2))
            const g = Math.round(255 * (norm < 0.5 ? norm * 2 : (1 - norm) * 2))
            const b = Math.round(255 * Math.max(0, (0.5 - norm) * 2))
            const isPeak = peak_ij && peak_ij[0] === j && peak_ij[1] === i
            return (
              <div
                key={`${j}-${i}`}
                style={{
                  backgroundColor: `rgb(${r},${g},${b})`,
                  outline: isPeak ? '1px solid white' : 'none',
                }}
                title={`(${i},${j}): ${t.toFixed(1)} °C`}
              />
            )
          })
        )}
      </div>
      <div className="absolute bottom-1 right-1 text-[9px] text-white/70 bg-black/50 px-1 rounded">
        {tMin.toFixed(0)}–{tMax.toFixed(0)} °C
      </div>
    </div>
  )
}

// ── Main panel ───────────────────────────────────────────────────────────────

export default function PCBThermalPanel({ onClose }) {
  const [tab, setTab]         = useState('map')
  const [loading, setLoading] = useState(false)
  const [offline, setOffline] = useState(false)
  const [mapResult, setMapResult]   = useState(null)
  const [recResult, setRecResult]   = useState(null)

  // Board parameters (editable)
  const [copperCoverage, setCopperCoverage] = useState('0.4')
  const [hConv, setHConv]                   = useState('10')
  const [ambientC, setAmbientC]             = useState('25')
  const [targetDt, setTargetDt]             = useState('30')

  const buildBoard = useCallback(() => ({
    ...DEFAULT_BOARD,
    copper_coverage: parseFloat(copperCoverage) || 0.4,
    h_conv: parseFloat(hConv) || 10,
    ambient_c: parseFloat(ambientC) || 25,
  }), [copperCoverage, hConv, ambientC])

  const runMap = useCallback(async () => {
    setLoading(true)
    const board = buildBoard()
    const r = await apiPost('board_thermal_map', {
      ...board,
      components: DEFAULT_COMPONENTS,
    })
    setLoading(false)
    if (!r || r.error) { setOffline(true); return }
    setMapResult(r)
  }, [buildBoard])

  const runRecommend = useCallback(async () => {
    setLoading(true)
    const board = buildBoard()
    const r = await apiPost('board_thermal_recommend', {
      board: { ...board, components: DEFAULT_COMPONENTS },
      target_delta_t_c: parseFloat(targetDt) || 30,
    })
    setLoading(false)
    if (!r || r.error) { setOffline(true); return }
    setRecResult(r)
  }, [buildBoard, targetDt])

  const TABS = [
    { id: 'map', label: 'Thermal Map' },
    { id: 'recommend', label: 'Recommend' },
  ]

  return (
    <div
      data-testid="pcb-thermal-panel"
      className="absolute top-12 right-4 w-96 bg-[#12122a] border border-white/10 rounded-xl shadow-2xl z-50 flex flex-col max-h-[80vh] overflow-hidden"
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-white/10">
        <Thermometer size={15} className="text-orange-400" />
        <span className="text-sm font-semibold text-white">PCB Thermal Analysis</span>
        <button
          data-testid="pcb-thermal-close"
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
            data-testid={`thermal-tab-${id}`}
            onClick={() => setTab(id)}
            className={[
              'px-3 py-1.5 rounded-md text-[11px] font-medium transition-colors',
              tab === id ? 'bg-orange-700 text-white' : 'text-gray-400 hover:text-white hover:bg-white/10',
            ].join(' ')}
          >
            {label}
          </button>
        ))}
      </div>

      {offline && (
        <div className="mx-3 mt-2 px-3 py-2 bg-yellow-900/30 border border-yellow-700/40 rounded-lg text-[11px] text-yellow-300">
          Backend offline — thermal tools wired (2D FD steady-state, IPC-2152, Incropera)
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3" data-testid="thermal-content">
        {/* ── Board parameters ─────────────────────────────────────────── */}
        <div className="grid grid-cols-3 gap-2">
          {[
            { id: 'thermal-copper', label: 'Copper frac', val: copperCoverage, set: setCopperCoverage },
            { id: 'thermal-hconv', label: 'h_conv (W/m²K)', val: hConv, set: setHConv },
            { id: 'thermal-ambient', label: 'Ambient (°C)', val: ambientC, set: setAmbientC },
          ].map(({ id, label, val, set }) => (
            <div key={id}>
              <label className="block text-[10px] text-gray-500 mb-0.5">{label}</label>
              <input
                data-testid={id}
                type="text"
                value={val}
                onChange={(e) => set(e.target.value)}
                className="w-full px-2 py-1 bg-black/30 border border-white/10 rounded text-[11px] text-white"
              />
            </div>
          ))}
        </div>

        {/* ── Thermal Map tab ───────────────────────────────────────────── */}
        {tab === 'map' && (
          <div className="space-y-3">
            <div className="text-[11px] text-gray-400 px-1">
              2D FD steady-state thermal map (IPC-2152). k_eff = f_cu·k_Cu + (1−f_cu)·k_FR4.
            </div>

            <button
              data-testid="thermal-run-btn"
              onClick={runMap}
              disabled={loading}
              className="w-full py-2 rounded-lg bg-orange-700 hover:bg-orange-600 disabled:opacity-50 text-white text-xs font-medium flex items-center justify-center gap-2 transition-colors"
            >
              {loading ? <RefreshCw size={12} className="animate-spin" /> : <Thermometer size={12} />}
              Run Thermal Map
            </button>

            {mapResult && mapResult.ok && (
              <div data-testid="thermal-map-result" className="space-y-3">
                <div className="flex items-center gap-3 text-[11px]">
                  <span className="text-gray-400">Peak:</span>
                  <span className={`font-medium ${mapResult.any_over_limit ? 'text-red-400' : 'text-white'}`}>
                    {Number(mapResult.peak_T_c).toFixed(1)} °C
                  </span>
                  {mapResult.any_over_limit && (
                    <span className="flex items-center gap-1 text-red-400">
                      <AlertTriangle size={11} /> Over limit
                    </span>
                  )}
                </div>

                {/* Heat map */}
                {mapResult.T_field && (
                  <HeatMap
                    T_field={mapResult.T_field}
                    nx={mapResult.nx}
                    ny={mapResult.ny}
                    peak_ij={mapResult.peak_ij}
                  />
                )}

                {/* Component results */}
                <div className="space-y-1.5">
                  {(mapResult.components ?? []).map((comp) => (
                    <ComponentResult key={comp.ref} comp={comp} />
                  ))}
                </div>

                <div className="text-[10px] text-gray-600 px-1">
                  Energy balance error: {(mapResult.energy_balance_err * 100).toFixed(2)}%
                  · Total power: {Number(mapResult.total_power_w ?? 0).toFixed(2)} W
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Recommend tab ─────────────────────────────────────────────── */}
        {tab === 'recommend' && (
          <div className="space-y-3">
            <div className="text-[11px] text-gray-400 px-1">
              Recommend copper coverage + thermal via count to meet a ΔT target.
            </div>

            <div>
              <label className="block text-[10px] text-gray-500 mb-0.5">Target ΔT (°C above ambient)</label>
              <input
                data-testid="thermal-target-dt"
                type="text"
                value={targetDt}
                onChange={(e) => setTargetDt(e.target.value)}
                className="w-full px-2 py-1 bg-black/30 border border-white/10 rounded text-[11px] text-white"
              />
            </div>

            <button
              data-testid="thermal-recommend-btn"
              onClick={runRecommend}
              disabled={loading}
              className="w-full py-2 rounded-lg bg-orange-700 hover:bg-orange-600 disabled:opacity-50 text-white text-xs font-medium flex items-center justify-center gap-2 transition-colors"
            >
              {loading ? <RefreshCw size={12} className="animate-spin" /> : <Zap size={12} />}
              Get Recommendations
            </button>

            {recResult && recResult.ok && (
              <div data-testid="thermal-recommend-result" className="space-y-2">
                {recResult.already_ok ? (
                  <div className="flex items-center gap-2 text-[11px] text-emerald-400">
                    <CheckCircle2 size={12} />
                    Already meets ΔT ≤ {targetDt} °C target
                  </div>
                ) : (
                  <>
                    {recResult.copper_recommendation && (
                      <div className="px-3 py-2 bg-white/5 rounded-lg text-[11px]">
                        <div className="text-gray-400 mb-1">Copper recommendation:</div>
                        <div className="text-white">
                          Min coverage: {recResult.copper_recommendation.min_coverage != null
                            ? `${(recResult.copper_recommendation.min_coverage * 100).toFixed(0)}%`
                            : 'not achievable with copper alone'}
                        </div>
                      </div>
                    )}
                    <div className="text-[11px] text-gray-400 px-1">Via options:</div>
                    {(recResult.via_options ?? []).map((opt, idx) => (
                      <div key={idx} className="px-3 py-1 bg-white/5 rounded text-[11px]">
                        {opt.n_vias} vias → ΔT = {Number(opt.delta_t_c).toFixed(1)} °C
                        {opt.meets_target && <span className="ml-2 text-emerald-400">✓</span>}
                      </div>
                    ))}
                  </>
                )}
              </div>
            )}

            <div className="text-[10px] text-gray-600 px-1">
              IPC-2152 §6 board thermal guidelines; Delphi spreading resistance;
              Incropera (7e §6) forced convection correlation.
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
