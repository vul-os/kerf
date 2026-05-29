/**
 * SpiceRunPanel.jsx
 *
 * Netlist editor + analysis selector for SPICE simulations.
 *
 * - Renders a textarea netlist editor with SPICE syntax hints
 * - Analysis selector: DC Sweep / AC / Transient / PVT Corner Sweep / Monte-Carlo
 * - On "Run Simulation" → POST /api/tools/call → backend silicon SPICE tool
 * - Result is automatically saved as a `.spice.waveform` artifact and opened
 *   in WaveformViewer (via onWaveformResult callback)
 *
 * Props
 * -----
 *   content        {string}  - Raw .spice.net/.cir file content
 *   fileName       {string}  - Filename (for display)
 *   onChange       {fn}      - Called with new netlist string on edit
 *   onWaveformResult {fn}    - Called with { signals, meta } when sim completes
 *   projectId      {string}  - Used to save the waveform artifact
 *   fileId         {string}  - Source file ID
 */

import { useState, useCallback, useRef } from 'react'
import { api } from '../../lib/api.js'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ANALYSIS_TYPES = [
  {
    id: 'transient',
    label: 'Transient',
    description: '.TRAN — time-domain voltage/current vs time',
    params: [
      { id: 't_step_ns', label: 'Step (ns)', type: 'number', default: '1', min: '0.001' },
      { id: 't_stop_ns', label: 'Stop (ns)', type: 'number', default: '1000', min: '1' },
    ],
  },
  {
    id: 'ac',
    label: 'AC',
    description: '.AC — small-signal frequency response',
    params: [
      { id: 'fstart_hz', label: 'F start (Hz)', type: 'number', default: '1', min: '0.001' },
      { id: 'fstop_hz', label: 'F stop (Hz)', type: 'number', default: '1e9', min: '1' },
      { id: 'n_points', label: 'Points/dec', type: 'number', default: '20', min: '5' },
    ],
  },
  {
    id: 'dc_sweep',
    label: 'DC Sweep',
    description: '.DC — operating-point vs swept source',
    params: [
      { id: 'sweep_src', label: 'Source', type: 'text', default: 'VIN' },
      { id: 'vstart', label: 'V start', type: 'number', default: '0' },
      { id: 'vstop', label: 'V stop', type: 'number', default: '1.8' },
      { id: 'vstep', label: 'V step', type: 'number', default: '0.01' },
    ],
  },
  {
    id: 'pvt_corner',
    label: 'PVT Corner Sweep',
    description: '60 corners (5P × 3V × 4T) + Monte-Carlo mismatch per corner',
    params: [
      {
        id: 'cell_name',
        label: 'Cell',
        type: 'select',
        default: 'bandgap_brokaw',
        options: ['bandgap_brokaw', 'comparator_strongarm', 'opamp_2stage'],
      },
      { id: 'n_mc', label: 'MC samples/corner', type: 'number', default: '50', min: '1' },
    ],
  },
  {
    id: 'monte_carlo',
    label: 'Monte-Carlo',
    description: 'Statistical mismatch sampling across a transient run',
    params: [
      { id: 'n_runs', label: 'Runs', type: 'number', default: '100', min: '10' },
      { id: 't_step_ns', label: 'Step (ns)', type: 'number', default: '1', min: '0.001' },
      { id: 't_stop_ns', label: 'Stop (ns)', type: 'number', default: '1000', min: '1' },
    ],
  },
]

// Sample netlist templates
const NETLIST_TEMPLATES = {
  transient: `* RC low-pass filter transient\nV1 in 0 PULSE(0 1.8 0 1n 1n 50n 100n)\nR1 in out 1k\nC1 out 0 100p\n.TRAN 0.5n 500n\n.PROBE V(out) V(in)\n.end`,
  ac: `* Op-amp AC analysis\nV1 in 0 AC 1\nR1 in inv 10k\nR2 inv out 100k\nC1 out 0 10p\n.AC DEC 20 1 1Meg\n.PROBE V(out)\n.end`,
  dc_sweep: `* MOSFET Ids vs Vgs\nM1 d g 0 0 nmos W=4u L=150n\nVgs g 0 DC 0\nVdd d 0 DC 1.8\n.DC Vgs 0 1.8 0.01\n.PROBE I(Vdd)\n.end`,
}

// ---------------------------------------------------------------------------
// Parameter input row
// ---------------------------------------------------------------------------

function ParamRow({ param, value, onChange }) {
  if (param.type === 'select') {
    return (
      <label className="flex items-center gap-2">
        <span className="text-[11px] text-ink-400 w-32 flex-shrink-0">{param.label}</span>
        <select
          value={value}
          onChange={e => onChange(param.id, e.target.value)}
          className="bg-ink-800 border border-ink-700 rounded px-2 py-1 text-xs text-ink-100 outline-none focus:border-kerf-300/60 flex-1"
        >
          {param.options.map(opt => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
      </label>
    )
  }
  return (
    <label className="flex items-center gap-2">
      <span className="text-[11px] text-ink-400 w-32 flex-shrink-0">{param.label}</span>
      <input
        type={param.type}
        value={value}
        min={param.min}
        onChange={e => onChange(param.id, e.target.value)}
        className="bg-ink-800 border border-ink-700 rounded px-2 py-1 text-xs font-mono text-ink-100 outline-none focus:border-kerf-300/60 flex-1"
      />
    </label>
  )
}

// ---------------------------------------------------------------------------
// Error / warning display
// ---------------------------------------------------------------------------

function SimError({ errors, warnings }) {
  if (!errors?.length && !warnings?.length) return null
  return (
    <div className="flex flex-col gap-1 px-4 pb-3">
      {errors?.map((e, i) => (
        <div key={i} className="flex items-start gap-1.5 text-red-400 text-[11px] font-mono bg-red-950/40 border border-red-800/50 rounded px-2 py-1">
          <span className="flex-shrink-0">✗</span>
          <span className="break-all">{e}</span>
        </div>
      ))}
      {warnings?.map((w, i) => (
        <div key={i} className="flex items-start gap-1.5 text-amber-400 text-[11px] font-mono bg-amber-950/40 border border-amber-800/50 rounded px-2 py-1">
          <span className="flex-shrink-0">⚠</span>
          <span className="break-all">{w}</span>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function SpiceRunPanel({
  content = '',
  fileName = '',
  onChange,
  onWaveformResult,
  projectId,
  fileId,
}) {
  const [analysisId, setAnalysisId] = useState('transient')
  const [params, setParams] = useState(() => {
    const defaults = {}
    ANALYSIS_TYPES.forEach(a => {
      a.params.forEach(p => { defaults[`${a.id}__${p.id}`] = p.default })
    })
    return defaults
  })
  const [running, setRunning] = useState(false)
  const [lastResult, setLastResult] = useState(null)
  const [errors, setErrors] = useState([])
  const [warnings, setWarnings] = useState([])

  const analysis = ANALYSIS_TYPES.find(a => a.id === analysisId)

  const handleParamChange = useCallback((paramId, value) => {
    setParams(prev => ({ ...prev, [`${analysisId}__${paramId}`]: value }))
  }, [analysisId])

  const getParamValue = useCallback((aId, pId) => {
    const key = `${aId}__${pId}`
    return params[key] ?? ANALYSIS_TYPES.find(a => a.id === aId)?.params.find(p => p.id === pId)?.default ?? ''
  }, [params])

  const handleLoadTemplate = useCallback(() => {
    const tmpl = NETLIST_TEMPLATES[analysisId]
    if (tmpl && onChange) onChange(tmpl)
  }, [analysisId, onChange])

  // Build tool call payload
  const buildPayload = useCallback(() => {
    const ap = {}
    analysis.params.forEach(p => {
      ap[p.id] = getParamValue(analysisId, p.id)
    })

    if (analysisId === 'pvt_corner') {
      return {
        tool: 'silicon_pvt_sweep',
        params: {
          cell_name: ap.cell_name,
          n_mc_per_corner: parseInt(ap.n_mc, 10) || 50,
        },
      }
    }

    if (analysisId === 'transient') {
      return {
        tool: 'silicon_spice_transient',
        params: {
          netlist: content,
          t_step_ns: parseFloat(ap.t_step_ns) || 1,
          t_stop_ns: parseFloat(ap.t_stop_ns) || 1000,
        },
      }
    }

    if (analysisId === 'ac') {
      return {
        tool: 'silicon_spice_ac',
        params: {
          netlist: content,
          fstart_hz: parseFloat(ap.fstart_hz) || 1,
          fstop_hz: parseFloat(ap.fstop_hz) || 1e9,
          n_points: parseInt(ap.n_points, 10) || 20,
        },
      }
    }

    if (analysisId === 'dc_sweep') {
      return {
        tool: 'silicon_spice_dc',
        params: {
          netlist: content,
          sweep_src: ap.sweep_src || 'VIN',
          vstart: parseFloat(ap.vstart) ?? 0,
          vstop: parseFloat(ap.vstop) ?? 1.8,
          vstep: parseFloat(ap.vstep) ?? 0.01,
        },
      }
    }

    if (analysisId === 'monte_carlo') {
      return {
        tool: 'silicon_spice_monte_carlo',
        params: {
          netlist: content,
          n_runs: parseInt(ap.n_runs, 10) || 100,
          t_step_ns: parseFloat(ap.t_step_ns) || 1,
          t_stop_ns: parseFloat(ap.t_stop_ns) || 1000,
        },
      }
    }

    return { tool: 'silicon_spice_transient', params: { netlist: content } }
  }, [analysisId, analysis, getParamValue, content])

  // Convert backend response → .spice.waveform signals array
  const toSignals = useCallback((toolResult, analysisType) => {
    if (analysisType === 'pvt_corner') {
      // PVT result: corners × metrics → signals keyed by corner name
      const result = toolResult?.result
      if (!result?.results) return []
      const byMetric = {}
      result.results.forEach(r => {
        if (!byMetric[r.metric]) byMetric[r.metric] = { t: [], y: [] }
        byMetric[r.metric].t.push(parseFloat(r.temp_c))
        byMetric[r.metric].y.push(r.mean)
      })
      return Object.entries(byMetric).map(([name, d]) => ({
        name,
        units: result.results.find(r => r.metric === name)?.unit || '',
        t: d.t,
        y: d.y,
      }))
    }

    // Standard SPICE waveform result: { waveforms: { time: [], v(out): [], ... } }
    const waveforms = toolResult?.waveforms || {}
    const time = waveforms.time || waveforms.t || []
    return Object.entries(waveforms)
      .filter(([k]) => k !== 'time' && k !== 't')
      .map(([name, y]) => ({
        name,
        units: name.toLowerCase().startsWith('i(') ? 'A' : 'V',
        t: time,
        y: Array.isArray(y) ? y : [],
      }))
  }, [])

  const handleRun = useCallback(async () => {
    setRunning(true)
    setErrors([])
    setWarnings([])
    setLastResult(null)

    try {
      const payload = buildPayload()

      const resp = await api.callTool(payload.tool, payload.params)

      const toolResult = resp?.result || resp

      if (resp?.error || toolResult?.error) {
        setErrors([resp?.error || toolResult?.error || 'Simulation failed'])
        return
      }

      const signals = toSignals(toolResult, analysisId)
      const meta = {
        title: `${analysis.label} — ${fileName || 'netlist'}`,
        analysis: analysisId,
        source: fileName || '',
        ran_at: new Date().toISOString(),
      }
      const waveformData = { signals, meta }

      setLastResult({ ok: true, n_signals: signals.length })

      if (toolResult?.warnings?.length) setWarnings(toolResult.warnings)

      if (onWaveformResult) onWaveformResult(waveformData)
    } catch (err) {
      setErrors([err?.message || String(err)])
    } finally {
      setRunning(false)
    }
  }, [buildPayload, toSignals, analysisId, analysis, fileName, onWaveformResult])

  return (
    <div className="flex-1 min-h-0 flex flex-col bg-ink-950 overflow-hidden" data-testid="spice-run-panel">
      {/* Top: analysis selector + params */}
      <div className="flex-shrink-0 border-b border-ink-800 bg-ink-900/40">
        {/* Analysis type tabs */}
        <div className="flex items-center gap-px px-3 pt-2 pb-0 overflow-x-auto">
          {ANALYSIS_TYPES.map(a => (
            <button
              key={a.id}
              type="button"
              data-testid={`analysis-${a.id}`}
              onClick={() => setAnalysisId(a.id)}
              className={`px-3 py-1.5 text-[11px] font-mono rounded-t border-b-2 transition-colors flex-shrink-0 ${
                analysisId === a.id
                  ? 'border-kerf-300 text-kerf-300 bg-ink-800/60'
                  : 'border-transparent text-ink-400 hover:text-ink-200 hover:border-ink-600'
              }`}
            >
              {a.label}
            </button>
          ))}
        </div>

        {/* Analysis description */}
        <div className="px-4 pt-2 pb-1">
          <span className="text-[10px] text-ink-500 font-mono">{analysis.description}</span>
        </div>

        {/* Params */}
        <div className="px-4 pb-3 flex flex-wrap gap-3">
          {analysis.params.map(p => (
            <ParamRow
              key={p.id}
              param={p}
              value={getParamValue(analysisId, p.id)}
              onChange={handleParamChange}
            />
          ))}
        </div>

        {/* Run bar */}
        <div className="flex items-center gap-3 px-4 pb-3">
          <button
            type="button"
            data-testid="run-simulation-btn"
            onClick={handleRun}
            disabled={running}
            className="flex items-center gap-2 px-4 py-1.5 rounded bg-kerf-300/15 border border-kerf-300/40 text-kerf-200 text-xs font-medium hover:bg-kerf-300/25 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {running ? (
              <>
                <span className="w-3 h-3 rounded-full border-2 border-kerf-300 border-t-transparent animate-spin" />
                Running…
              </>
            ) : (
              <>
                <span>▶</span>
                Run Simulation
              </>
            )}
          </button>
          <button
            type="button"
            onClick={handleLoadTemplate}
            className="px-3 py-1.5 rounded border border-ink-700 text-ink-400 text-xs hover:bg-ink-800 hover:text-ink-100"
            title={`Load a sample ${analysis.label} netlist`}
          >
            Load template
          </button>
          {lastResult?.ok && (
            <span className="text-[11px] text-emerald-400 font-mono">
              ✓ {lastResult.n_signals} signal{lastResult.n_signals !== 1 ? 's' : ''}
            </span>
          )}
        </div>
      </div>

      {/* Errors / warnings */}
      <SimError errors={errors} warnings={warnings} />

      {/* Netlist editor */}
      <div className="flex-1 min-h-0 flex flex-col">
        <div className="flex items-center justify-between px-3 py-1 border-b border-ink-800 bg-ink-900/20 flex-shrink-0">
          <span className="text-[10px] text-ink-500 font-mono">
            {fileName || 'netlist'} — SPICE netlist
          </span>
          <span className="text-[10px] text-ink-600">
            {content ? `${content.length.toLocaleString()} chars` : 'empty'}
          </span>
        </div>
        <textarea
          data-testid="netlist-editor"
          value={content}
          onChange={e => onChange && onChange(e.target.value)}
          spellCheck={false}
          className="flex-1 min-h-0 w-full bg-ink-950 text-ink-100 font-mono text-xs p-3 resize-none outline-none border-0 leading-relaxed"
          placeholder={`* SPICE netlist\n* Use analysis panel above to configure and run\n.end`}
        />
      </div>
    </div>
  )
}
