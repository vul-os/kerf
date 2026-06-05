// SIPanel.jsx — Signal Integrity analysis panel.
//
// Provides Z0 / propagation-delay / crosstalk / IBIS eye-diagram via the kerf-electronics
// backend tools (si_impedance, si_propagation, si_crosstalk, si_report, si_ibis_channel_response).
//
// Backend contracts:
//   POST /api/llm-tools/si_impedance   → {z0_ohms, zdiff_ohms?}
//   POST /api/llm-tools/si_propagation → {td_ps_per_mm, flight_time_ps}
//   POST /api/llm-tools/si_crosstalk   → {NEXT, FEXT}
//   POST /api/llm-tools/si_report      → combined SI summary
//   POST /api/llm-tools/si_ibis_channel_response → {waveform, eye_high_V, eye_low_V}
//
// References: IPC-2141A (2004), Wadell 1991 §3.7/4.3, Hall & Heck 2009 §3.

import { useCallback, useState } from 'react'
import { X, Activity, Zap } from 'lucide-react'

// ── Numeric field helper ──────────────────────────────────────────────────────

function Field({ label, value, unit, type = 'number', step = 'any', min, onChange, testId }) {
  return (
    <label className="flex flex-col gap-0.5">
      <span className="text-gray-500 text-[10px]">{label}</span>
      <div className="flex items-center gap-1">
        <input
          data-testid={testId}
          type={type}
          step={step}
          min={min}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="bg-black/40 border border-white/10 rounded px-2 py-1 text-white w-20 text-xs focus:outline-none focus:border-indigo-600"
        />
        {unit && <span className="text-gray-600 text-[10px]">{unit}</span>}
      </div>
    </label>
  )
}

function Select({ label, value, options, onChange, testId }) {
  return (
    <label className="flex flex-col gap-0.5">
      <span className="text-gray-500 text-[10px]">{label}</span>
      <select
        data-testid={testId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-black/40 border border-white/10 rounded px-2 py-1 text-white text-xs focus:outline-none focus:border-indigo-600"
      >
        {options.map(({ value: v, label: l }) => (
          <option key={v} value={v}>{l}</option>
        ))}
      </select>
    </label>
  )
}

// ── Result value display ──────────────────────────────────────────────────────

function ResultVal({ label, value, unit, highlight = false }) {
  if (value == null) return null
  return (
    <div className="flex items-baseline justify-between gap-2 text-[11px]">
      <span className="text-gray-500">{label}</span>
      <span className={highlight ? 'text-indigo-300 font-medium' : 'text-gray-200'}>
        {typeof value === 'number' ? value.toFixed(2) : value}
        {unit && <span className="text-gray-500 ml-0.5 text-[10px]">{unit}</span>}
      </span>
    </div>
  )
}

// ── SI Report tab ─────────────────────────────────────────────────────────────

function SIReportTab() {
  const [structure, setStructure]  = useState('microstrip')
  const [width, setWidth]          = useState('0.15')
  const [height, setHeight]        = useState('0.1')
  const [er, setEr]                = useState('4.3')
  const [length, setLength]        = useState('50')
  const [driverZ, setDriverZ]      = useState('50')
  const [topology, setTopology]    = useState('point_to_point')
  const [spacing, setSpacing]      = useState('')
  const [aggLen, setAggLen]        = useState('')
  const [result, setResult]        = useState(null)
  const [loading, setLoading]      = useState(false)
  const [error, setError]          = useState(null)

  const run = useCallback(async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    const body = {
      structure,
      trace_width_mm:      parseFloat(width),
      dielectric_height_mm: parseFloat(height),
      er:                  parseFloat(er),
      length_mm:           parseFloat(length),
      driver_z_ohms:       parseFloat(driverZ),
      topology,
    }
    if (spacing && parseFloat(spacing) > 0) body.spacing_mm = parseFloat(spacing)
    if (aggLen && parseFloat(aggLen) > 0) body.aggressor_parallel_length_mm = parseFloat(aggLen)

    try {
      const res = await fetch('/api/llm-tools/si_report', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json()
      if (data?.ok) {
        setResult(data.result)
      } else {
        setError(data?.message ?? 'SI analysis failed.')
      }
    } catch {
      // Demo fallback
      const w = parseFloat(width) || 0.15
      const h = parseFloat(height) || 0.1
      const erV = parseFloat(er) || 4.3
      const z0 = (87 / Math.sqrt(erV + 1.41)) * Math.log(5.98 * h / (0.8 * w + 0.000035))
      const td = 3.336 * Math.sqrt(erV)
      setResult({
        _demo: true,
        z0_ohms:         Math.round(z0 * 100) / 100,
        td_ps_per_mm:    Math.round(td * 1000) / 1000,
        flight_time_ps:  Math.round(td * (parseFloat(length) || 50) * 100) / 100,
        formulas:        'IPC-2141A (2004)',
      })
    } finally {
      setLoading(false)
    }
  }, [structure, width, height, er, length, driverZ, topology, spacing, aggLen])

  return (
    <div className="flex flex-col gap-3 p-3">
      <div className="flex flex-wrap gap-2">
        <Select
          label="Structure"
          value={structure}
          options={[
            { value: 'microstrip', label: 'Microstrip' },
            { value: 'stripline',  label: 'Stripline'  },
          ]}
          onChange={setStructure}
          testId="si-structure"
        />
        <Field label="Width"  value={width}  unit="mm" onChange={setWidth}  testId="si-width"  min="0.01" />
        <Field label="H (diel)" value={height} unit="mm" onChange={setHeight} testId="si-height" min="0.01" />
        <Field label="εr"     value={er}     onChange={setEr}     testId="si-er"     min="1" />
        <Field label="Length" value={length} unit="mm" onChange={setLength} testId="si-length" min="0.1" />
        <Field label="Driver Z" value={driverZ} unit="Ω" onChange={setDriverZ} testId="si-driver-z" min="1" />
        <Select
          label="Topology"
          value={topology}
          options={[
            { value: 'point_to_point', label: 'Point-to-point' },
            { value: 'bus',            label: 'Bus' },
            { value: 'clock',          label: 'Clock' },
          ]}
          onChange={setTopology}
          testId="si-topology"
        />
        <Field label="Aggressor spacing" value={spacing} unit="mm" onChange={setSpacing} testId="si-spacing" min="0" />
        <Field label="Aggressor run"     value={aggLen}  unit="mm" onChange={setAggLen}  testId="si-agg-len" min="0" />
      </div>

      <button
        data-testid="si-run-btn"
        onClick={run}
        disabled={loading}
        className="px-3 py-1.5 rounded-md bg-indigo-700 hover:bg-indigo-600 text-white text-xs font-medium transition-colors disabled:opacity-40 self-start"
      >
        {loading ? 'Running…' : 'Analyse'}
      </button>

      {error && <p className="text-red-400 text-[11px]">{error}</p>}

      {result && (
        <div
          data-testid="si-results"
          className="border border-white/10 rounded-lg p-3 bg-black/30 flex flex-col gap-1"
        >
          {result._demo && (
            <p className="text-yellow-500 text-[10px] mb-1">Demo mode (offline) — IPC-2141A formula</p>
          )}
          <ResultVal label="Z0" value={result.z0_ohms} unit="Ω" highlight />
          <ResultVal label="Zdiff" value={result.zdiff_ohms} unit="Ω" highlight />
          <ResultVal label="Prop. delay" value={result.td_ps_per_mm} unit="ps/mm" />
          <ResultVal label="Flight time" value={result.flight_time_ps} unit="ps" />
          {result.crosstalk && (
            <>
              <div className="border-t border-white/5 my-1" />
              <ResultVal
                label="NEXT"
                value={result.crosstalk.NEXT?.next_mv != null ? result.crosstalk.NEXT.next_mv.toFixed(2) : null}
                unit="mV"
              />
              <ResultVal
                label="FEXT"
                value={result.crosstalk.FEXT?.fext_mv != null ? result.crosstalk.FEXT.fext_mv.toFixed(2) : null}
                unit="mV"
              />
            </>
          )}
          {result.termination && (
            <>
              <div className="border-t border-white/5 my-1" />
              <ResultVal label="Γ (load)" value={result.gamma_open_load} />
              <div className="text-[11px] text-indigo-300 mt-0.5">
                {result.termination.scheme}
                {result.termination.r_ohms != null && (
                  <span className="text-gray-400 ml-1">R={result.termination.r_ohms} Ω</span>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ── IBIS Eye tab ──────────────────────────────────────────────────────────────

function IBISEyeTab() {
  const [ibsText, setIbsText]     = useState('')
  const [z0, setZ0]               = useState('50')
  const [length, setLength]       = useState('100')
  const [bitrate, setBitrate]     = useState('1e9')
  const [result, setResult]       = useState(null)
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState(null)

  const run = useCallback(async () => {
    if (!ibsText.trim()) {
      setError('Paste IBIS (.ibs) text above.')
      return
    }
    setLoading(true)
    setError(null)
    setResult(null)

    try {
      // Step 1: parse IBIS
      const parseRes = await fetch('/api/llm-tools/si_ibis_parse', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ ibs_text: ibsText }),
      })
      const parseData = await parseRes.json()
      const deck = parseData?.result ?? parseData
      if (!deck?.models?.length) throw new Error('No models in IBIS file.')

      const model = deck.models[0]

      // Step 2: channel sim
      const chanRes = await fetch('/api/llm-tools/si_ibis_channel_response', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          ibis_model_dict: model,
          z0_ohms:         parseFloat(z0) || 50,
          length_mm:       parseFloat(length) || 100,
          bitrate_bps:     parseFloat(bitrate) || 1e9,
        }),
      })
      const chanData = await chanRes.json()
      if (chanData?.ok) {
        setResult(chanData.result)
      } else {
        setError(chanData?.message ?? 'Channel simulation failed.')
      }
    } catch (err) {
      setError(`Backend error: ${err.message}`)
    } finally {
      setLoading(false)
    }
  }, [ibsText, z0, length, bitrate])

  return (
    <div className="flex flex-col gap-3 p-3">
      <label className="flex flex-col gap-1">
        <span className="text-gray-500 text-[10px]">IBIS (.ibs) file text</span>
        <textarea
          data-testid="ibis-text-input"
          value={ibsText}
          onChange={(e) => setIbsText(e.target.value)}
          rows={5}
          placeholder="[IBIS Ver] 5.1&#10;[File name] example.ibs&#10;…"
          className="bg-black/40 border border-white/10 rounded px-2 py-1.5 text-white text-[10px] font-mono resize-y focus:outline-none focus:border-indigo-600 placeholder-gray-700"
        />
      </label>

      <div className="flex flex-wrap gap-2">
        <Field label="Z0" value={z0} unit="Ω" onChange={setZ0} testId="ibis-z0" min="1" />
        <Field label="Length" value={length} unit="mm" onChange={setLength} testId="ibis-length" min="1" />
        <Field label="Bit rate" value={bitrate} unit="bps" onChange={setBitrate} testId="ibis-bitrate" min="1e6" />
      </div>

      <button
        data-testid="ibis-run-btn"
        onClick={run}
        disabled={loading}
        className="px-3 py-1.5 rounded-md bg-purple-700 hover:bg-purple-600 text-white text-xs font-medium transition-colors disabled:opacity-40 self-start"
      >
        {loading ? 'Simulating…' : 'Simulate Channel'}
      </button>

      {error && <p className="text-red-400 text-[11px]">{error}</p>}

      {result && (
        <div
          data-testid="ibis-results"
          className="border border-white/10 rounded-lg p-3 bg-black/30 flex flex-col gap-1"
        >
          <ResultVal label="Eye high" value={result.eye_high_V} unit="V" highlight />
          <ResultVal label="Eye low"  value={result.eye_low_V}  unit="V" />
          <ResultVal label="Eye height" value={result.eye_height_V} unit="V" highlight />
          {result.waveform?.length > 0 && (
            <div className="mt-2">
              <span className="text-[10px] text-gray-500">
                Waveform: {result.waveform.length} points
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

export default function SIPanel({ onClose }) {
  const [tab, setTab] = useState('si')

  return (
    <div
      data-testid="si-panel"
      className="flex flex-col bg-[#0d1117] border border-white/10 rounded-lg shadow-2xl text-xs font-mono"
      style={{ width: 480, maxHeight: 540 }}
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-white/10 bg-[#161b22] rounded-t-lg">
        <Activity size={13} className="text-indigo-400" />
        <span className="font-semibold text-gray-200 text-[12px]">Signal Integrity</span>
        <span className="text-gray-600 text-[10px] ml-1">
          IPC-2141A / Wadell 1991 / IBIS 5.x
        </span>
        <button
          data-testid="si-panel-close"
          onClick={onClose}
          className="ml-auto p-1 rounded hover:bg-white/10 text-gray-500 hover:text-white transition-colors"
        >
          <X size={12} />
        </button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-white/10">
        {[
          { key: 'si',   label: 'Z0 / Delay / Crosstalk', Icon: Zap },
          { key: 'ibis', label: 'IBIS Eye Diagram',        Icon: Activity },
        ].map(({ key, label, Icon }) => (
          <button
            key={key}
            data-testid={`si-tab-${key}`}
            onClick={() => setTab(key)}
            className={[
              'flex items-center gap-1.5 px-4 py-1.5 text-xs font-medium transition-colors border-b-2',
              tab === key
                ? 'border-indigo-500 text-indigo-300'
                : 'border-transparent text-gray-500 hover:text-gray-300',
            ].join(' ')}
          >
            <Icon size={11} />
            {label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {tab === 'si'   && <SIReportTab />}
        {tab === 'ibis' && <IBISEyeTab />}
      </div>
    </div>
  )
}
