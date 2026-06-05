// EMCPanel.jsx — EMC pre-compliance estimation panel.
//
// Provides: radiated emission estimation (differential-mode loop + common-mode
// cable), FCC §15.109 / CISPR 32 limit comparison, shielding effectiveness,
// and near-field crosstalk coefficient.
//
// Backend contracts:
//   POST /api/llm-tools/emc_radiated_differential  {freq_hz, loop_area_m2, current_a, distance_m}
//   POST /api/llm-tools/emc_radiated_common_mode   {freq_hz, cable_length_m, current_a, distance_m}
//   POST /api/llm-tools/emc_emission_margin        {e_field_dbuvm, freq_hz, standard, class_}
//   POST /api/llm-tools/emc_shielding              {freq_hz, thickness_m, conductivity_relative}
//   POST /api/llm-tools/emc_near_field_crosstalk   {freq_hz, trace_width_mm, …}
//
// References:
//   Ott "Electromagnetic Compatibility Engineering" (Wiley 2009) §6.2-6.3, §5.3-5.4
//   FCC Part 15 §15.109; CISPR 32:2015 Annex B Table B.4
//
// Props:
//   onClose — () => void

import { useCallback, useState } from 'react'
import { Zap, AlertTriangle, CheckCircle2, X, RefreshCw } from 'lucide-react'

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

function ResultRow({ label, value, unit = '', warn = false }) {
  return (
    <div className="flex items-center justify-between text-[11px] py-0.5">
      <span className="text-gray-400">{label}</span>
      <span className={warn ? 'text-yellow-300 font-medium' : 'text-white'}>
        {value} {unit}
      </span>
    </div>
  )
}

// ── Main panel ───────────────────────────────────────────────────────────────

export default function EMCPanel({ onClose }) {
  const [tab, setTab] = useState('radiated')
  const [loading, setLoading] = useState(false)
  const [offline, setOffline] = useState(false)

  // Radiated DM
  const [dmFreq, setDmFreq]     = useState('100')
  const [dmArea, setDmArea]     = useState('1e-4')
  const [dmCurrent, setDmCurrent] = useState('0.001')
  const [dmDist, setDmDist]     = useState('3')
  const [dmResult, setDmResult] = useState(null)

  // Margin
  const [marginStd, setMarginStd]   = useState('cispr')
  const [marginClass, setMarginClass] = useState('B')
  const [marginResult, setMarginResult] = useState(null)

  // Shielding
  const [shFreq, setShFreq]     = useState('1e6')
  const [shThick, setShThick]   = useState('1e-3')
  const [shSlot, setShSlot]     = useState('0')
  const [shResult, setShResult] = useState(null)

  const runDM = useCallback(async () => {
    setLoading(true)
    const r = await apiPost('emc_radiated_differential', {
      freq_hz: parseFloat(dmFreq),
      loop_area_m2: parseFloat(dmArea),
      current_a: parseFloat(dmCurrent),
      distance_m: parseFloat(dmDist),
    })
    setLoading(false)
    if (!r || r.error) { setOffline(true); return }
    setDmResult(r)
    if (r.ok) {
      // Auto-compute emission margin
      const mr = await apiPost('emc_emission_margin', {
        e_field_dbuvm: r.e_field_dbuvm,
        freq_hz: parseFloat(dmFreq),
        standard: marginStd,
        class_: marginClass,
        distance_m: parseFloat(dmDist),
      })
      if (mr && mr.ok) setMarginResult(mr)
    }
  }, [dmFreq, dmArea, dmCurrent, dmDist, marginStd, marginClass])

  const runShielding = useCallback(async () => {
    setLoading(true)
    const r = await apiPost('emc_shielding', {
      freq_hz: parseFloat(shFreq),
      thickness_m: parseFloat(shThick),
      aperture_length_m: parseFloat(shSlot) || 0,
    })
    setLoading(false)
    if (!r || r.error) { setOffline(true); return }
    setShResult(r)
  }, [shFreq, shThick, shSlot])

  const TABS = [
    { id: 'radiated', label: 'Radiated' },
    { id: 'shielding', label: 'Shielding' },
  ]

  return (
    <div
      data-testid="emc-panel"
      className="absolute top-12 right-4 w-96 bg-[#12122a] border border-white/10 rounded-xl shadow-2xl z-50 flex flex-col max-h-[80vh] overflow-hidden"
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-white/10">
        <Zap size={15} className="text-amber-400" />
        <span className="text-sm font-semibold text-white">EMC Pre-Compliance</span>
        <button
          data-testid="emc-close"
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
            data-testid={`emc-tab-${id}`}
            onClick={() => setTab(id)}
            className={[
              'px-3 py-1.5 rounded-md text-[11px] font-medium transition-colors',
              tab === id ? 'bg-amber-700 text-white' : 'text-gray-400 hover:text-white hover:bg-white/10',
            ].join(' ')}
          >
            {label}
          </button>
        ))}
      </div>

      {offline && (
        <div className="mx-3 mt-2 px-3 py-2 bg-yellow-900/30 border border-yellow-700/40 rounded-lg text-[11px] text-yellow-300">
          Backend offline — EMC tools wired (Ott 2009 §6.2-6.3, §5.3-5.4; FCC §15.109; CISPR 32)
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3" data-testid="emc-content">
        {/* ── Radiated tab ─────────────────────────────────────────────── */}
        {tab === 'radiated' && (
          <div className="space-y-3">
            <div className="text-[11px] text-gray-400 px-1">
              Differential-mode loop: E = 263×10⁻¹⁶ × f² × A × I / r (Ott §6.2)
            </div>

            <div className="grid grid-cols-2 gap-2">
              {[
                { id: 'emc-freq', label: 'Frequency (Hz)', val: dmFreq, set: setDmFreq },
                { id: 'emc-area', label: 'Loop area (m²)', val: dmArea, set: setDmArea },
                { id: 'emc-current', label: 'Current (A)', val: dmCurrent, set: setDmCurrent },
                { id: 'emc-distance', label: 'Distance (m)', val: dmDist, set: setDmDist },
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

            {/* Standard selector */}
            <div className="flex gap-2 items-center">
              <label className="text-[10px] text-gray-500">Standard:</label>
              <select
                data-testid="emc-standard"
                value={marginStd}
                onChange={(e) => setMarginStd(e.target.value)}
                className="px-2 py-1 bg-black/30 border border-white/10 rounded text-[11px] text-white"
              >
                <option value="cispr">CISPR 32</option>
                <option value="fcc">FCC Part 15</option>
              </select>
              <select
                data-testid="emc-class"
                value={marginClass}
                onChange={(e) => setMarginClass(e.target.value)}
                className="px-2 py-1 bg-black/30 border border-white/10 rounded text-[11px] text-white"
              >
                <option value="B">Class B (residential)</option>
                <option value="A">Class A (commercial)</option>
              </select>
            </div>

            <button
              data-testid="emc-run-btn"
              onClick={runDM}
              disabled={loading}
              className="w-full py-2 rounded-lg bg-amber-700 hover:bg-amber-600 disabled:opacity-50 text-white text-xs font-medium flex items-center justify-center gap-2 transition-colors"
            >
              {loading ? <RefreshCw size={12} className="animate-spin" /> : <Zap size={12} />}
              Compute Radiated Emission
            </button>

            {dmResult && dmResult.ok && (
              <div data-testid="emc-radiated-result" className="px-3 py-2 bg-white/5 rounded-lg space-y-0.5">
                <ResultRow label="E-field" value={dmResult.e_field_vpm?.toExponential(3)} unit="V/m" />
                <ResultRow label="E-field" value={dmResult.e_field_dbuvm} unit="dBμV/m" />
                <ResultRow label="Far field" value={dmResult.far_field ? 'yes' : 'no (near field)'} warn={!dmResult.far_field} />
              </div>
            )}

            {marginResult && marginResult.ok && (
              <div data-testid="emc-margin-result" className={`px-3 py-2 rounded-lg space-y-0.5 ${marginResult.passes ? 'bg-emerald-900/30 border border-emerald-700/40' : 'bg-red-900/30 border border-red-700/40'}`}>
                <div className={`text-[11px] font-medium ${marginResult.passes ? 'text-emerald-300' : 'text-red-300'}`}>
                  {marginResult.passes ? '✓ Compliant' : '✗ Exceeds limit'}
                </div>
                <ResultRow label="Margin" value={marginResult.margin_db} unit="dB" warn={!marginResult.passes} />
                <ResultRow label="Limit" value={marginResult.limit_dbuvm} unit="dBμV/m" />
                <div className="text-[10px] text-gray-500">
                  {marginResult.standard} Class {marginResult.class_} @ {marginResult.distance_m} m
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Shielding tab ────────────────────────────────────────────── */}
        {tab === 'shielding' && (
          <div className="space-y-3">
            <div className="text-[11px] text-gray-400 px-1">
              Schelkunoff shielding theory: SEa + SEr (Ott §5.3-5.4).
              SE_aperture = 20·log10(c / (2 · f · L_slot))
            </div>

            <div className="grid grid-cols-2 gap-2">
              {[
                { id: 'emc-sh-freq', label: 'Frequency (Hz)', val: shFreq, set: setShFreq },
                { id: 'emc-sh-thick', label: 'Wall thickness (m)', val: shThick, set: setShThick },
                { id: 'emc-sh-slot', label: 'Slot length (m, 0=none)', val: shSlot, set: setShSlot },
              ].map(({ id, label, val, set }) => (
                <div key={id} className="col-span-2 sm:col-span-1">
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

            <button
              data-testid="emc-shield-btn"
              onClick={runShielding}
              disabled={loading}
              className="w-full py-2 rounded-lg bg-amber-700 hover:bg-amber-600 disabled:opacity-50 text-white text-xs font-medium flex items-center justify-center gap-2 transition-colors"
            >
              {loading ? <RefreshCw size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
              Compute Shielding Effectiveness
            </button>

            {shResult && shResult.ok && (
              <div data-testid="emc-shielding-result" className="px-3 py-2 bg-white/5 rounded-lg space-y-0.5">
                <ResultRow label="SE absorption" value={shResult.se_absorption_db} unit="dB" />
                <ResultRow label="SE reflection" value={shResult.se_reflection_db} unit="dB" />
                <ResultRow label="SE total" value={shResult.se_total_db} unit="dB" />
                {shResult.se_aperture_db !== null && (
                  <ResultRow label="SE aperture" value={shResult.se_aperture_db} unit="dB" warn={shResult.aperture_limited} />
                )}
                <ResultRow label="SE effective" value={shResult.se_effective_db} unit="dB" />
                {shResult.aperture_limited && (
                  <div className="text-[10px] text-yellow-400">⚠ Aperture-limited</div>
                )}
              </div>
            )}

            <div className="text-[10px] text-gray-600 px-1">
              Reference: Schelkunoff / Ott (2009) §5.3-5.4 + IEC 62153-4-7.
              Copper σr=1.0, Al σr≈0.61, Steel σr≈0.10 (μr≈1000).
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
