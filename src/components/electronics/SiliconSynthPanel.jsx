// SiliconSynthPanel.jsx — Silicon synthesis / P&R status panel.
//
// Minimal UI for triggering a Yosys→OpenLane RTL-to-GDS flow and displaying
// the result status / log path. The external OpenLane binary may not be
// installed; the backend returns status="pending" in that case and we show
// a clear installation guide.
//
// Backend contracts:
//   POST /api/llm-tools/silicon_run_openlane  → {status, gds_path, log_path, returncode, warnings}
//   POST /api/llm-tools/silicon_yosys_synth   → {ok, cells, area, warnings}  (optional)
//
// References:
//   OpenLane 2: https://openlane2.readthedocs.io
//   Yosys: https://yosyshq.net/yosys/

import { useCallback, useState } from 'react'
import { X, Cpu, CheckCircle2, XCircle, AlertTriangle, Loader } from 'lucide-react'

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status }) {
  if (status === 'success')
    return (
      <span data-testid="synth-status-success" className="flex items-center gap-1 text-emerald-400">
        <CheckCircle2 size={12} /> Success
      </span>
    )
  if (status === 'error')
    return (
      <span data-testid="synth-status-error" className="flex items-center gap-1 text-red-400">
        <XCircle size={12} /> Error
      </span>
    )
  if (status === 'running')
    return (
      <span data-testid="synth-status-running" className="flex items-center gap-1 text-indigo-400 animate-pulse">
        <Loader size={12} className="animate-spin" /> Running…
      </span>
    )
  if (status === 'pending')
    return (
      <span data-testid="synth-status-pending" className="flex items-center gap-1 text-yellow-400">
        <AlertTriangle size={12} /> OpenLane not installed
      </span>
    )
  return null
}

// ── Warning list ──────────────────────────────────────────────────────────────

function WarningList({ warnings }) {
  if (!warnings?.length) return null
  return (
    <div className="mt-2 flex flex-col gap-0.5">
      {warnings.map((w, i) => (
        <div key={i} className="flex items-start gap-1.5 text-[10px] text-yellow-400">
          <AlertTriangle size={11} className="shrink-0 mt-0.5" />
          <span>{w}</span>
        </div>
      ))}
    </div>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

export default function SiliconSynthPanel({ onClose }) {
  const [designName, setDesignName] = useState('my_design')
  const [verilogText, setVerilogText] = useState(
    '// Paste Verilog RTL here\nmodule my_design (input clk, input rst, output reg q);\n  always @(posedge clk) q <= ~q;\nendmodule'
  )
  const [pdk, setPdk]               = useState('sky130A')
  const [clockPeriod, setClockPeriod] = useState('10')
  const [result, setResult]         = useState(null)
  const [status, setStatus]         = useState(null)  // 'running'|'success'|'error'|'pending'
  const [error, setError]           = useState(null)

  const run = useCallback(async () => {
    setStatus('running')
    setError(null)
    setResult(null)

    // The backend expects verilog_files as a list of paths; since we're in-browser
    // we pass the text as a single inline module via a special body key.
    const body = {
      design_name:  designName.trim() || 'my_design',
      verilog_files: ['__inline__'],
      verilog_inline: verilogText,
      pdk,
      clock_period: parseFloat(clockPeriod) || 10.0,
      clock_port:   'clk',
    }

    try {
      const res = await fetch('/api/llm-tools/silicon_run_openlane', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json()
      const r = data?.result ?? data

      setResult(r)
      if (r?.status === 'pending' || r?.status === 'success' || r?.status === 'error') {
        setStatus(r.status)
      } else if (r?.error) {
        setStatus('error')
        setError(r.error)
      } else {
        setStatus('error')
        setError('Unexpected response from backend.')
      }
    } catch (err) {
      // Backend offline or OpenLane not installed
      setStatus('pending')
      setResult({
        status: 'pending',
        gds_path: '',
        log_path: '',
        warnings: [
          'OpenLane CLI not found on server PATH.',
          'Install OpenLane 2: pip install openlane',
          'or follow: https://openlane2.readthedocs.io/en/latest/getting_started/',
        ],
      })
    }
  }, [designName, verilogText, pdk, clockPeriod])

  return (
    <div
      data-testid="silicon-synth-panel"
      className="flex flex-col bg-[#0d1117] border border-white/10 rounded-lg shadow-2xl text-xs font-mono"
      style={{ width: 480, maxHeight: 560 }}
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-white/10 bg-[#161b22] rounded-t-lg">
        <Cpu size={13} className="text-purple-400" />
        <span className="font-semibold text-gray-200 text-[12px]">Silicon Synthesis / P&amp;R</span>
        <span className="text-gray-600 text-[10px] ml-1">Yosys + OpenLane → GDS-II</span>
        {status && <div className="ml-auto mr-2"><StatusBadge status={status} /></div>}
        <button
          data-testid="silicon-synth-close"
          onClick={onClose}
          className="p-1 rounded hover:bg-white/10 text-gray-500 hover:text-white transition-colors ml-auto"
        >
          <X size={12} />
        </button>
      </div>

      {/* Form */}
      <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-3">
        <div className="flex flex-wrap gap-2">
          <label className="flex flex-col gap-0.5">
            <span className="text-gray-500 text-[10px]">Design name</span>
            <input
              data-testid="synth-design-name"
              type="text"
              value={designName}
              onChange={(e) => setDesignName(e.target.value)}
              className="bg-black/40 border border-white/10 rounded px-2 py-1 text-white w-32 focus:outline-none focus:border-purple-600"
            />
          </label>

          <label className="flex flex-col gap-0.5">
            <span className="text-gray-500 text-[10px]">PDK</span>
            <select
              data-testid="synth-pdk"
              value={pdk}
              onChange={(e) => setPdk(e.target.value)}
              className="bg-black/40 border border-white/10 rounded px-2 py-1 text-white focus:outline-none focus:border-purple-600"
            >
              <option value="sky130A">sky130A</option>
              <option value="sky130B">sky130B</option>
              <option value="gf180mcuD">gf180mcuD</option>
              <option value="asap7">ASAP7 (7 nm)</option>
            </select>
          </label>

          <label className="flex flex-col gap-0.5">
            <span className="text-gray-500 text-[10px]">Clock period</span>
            <div className="flex items-center gap-1">
              <input
                data-testid="synth-clock-period"
                type="number"
                min="0.1"
                step="0.5"
                value={clockPeriod}
                onChange={(e) => setClockPeriod(e.target.value)}
                className="bg-black/40 border border-white/10 rounded px-2 py-1 text-white w-16 focus:outline-none focus:border-purple-600"
              />
              <span className="text-gray-600 text-[10px]">ns</span>
            </div>
          </label>
        </div>

        <label className="flex flex-col gap-1">
          <span className="text-gray-500 text-[10px]">Verilog RTL</span>
          <textarea
            data-testid="synth-verilog"
            value={verilogText}
            onChange={(e) => setVerilogText(e.target.value)}
            rows={7}
            className="bg-black/40 border border-white/10 rounded px-2 py-1.5 text-white text-[10px] font-mono resize-y focus:outline-none focus:border-purple-600"
          />
        </label>

        <button
          data-testid="synth-run-btn"
          onClick={run}
          disabled={status === 'running'}
          className="px-3 py-1.5 rounded-md bg-purple-800 hover:bg-purple-700 text-white text-xs font-medium transition-colors disabled:opacity-40 self-start"
        >
          {status === 'running' ? 'Running flow…' : 'Run Synthesis + P&R'}
        </button>

        {error && <p className="text-red-400 text-[11px]">{error}</p>}

        {/* Result card */}
        {result && (
          <div
            data-testid="synth-result"
            className="border border-white/10 rounded-lg p-3 bg-black/30 flex flex-col gap-1.5"
          >
            <div className="flex items-center justify-between">
              <span className="text-gray-500">Status</span>
              <StatusBadge status={result.status ?? status} />
            </div>

            {result.gds_path && (
              <div className="flex items-center justify-between">
                <span className="text-gray-500">GDS</span>
                <span className="text-emerald-300 text-[10px] truncate max-w-[260px]">{result.gds_path}</span>
              </div>
            )}
            {result.log_path && (
              <div className="flex items-center justify-between">
                <span className="text-gray-500">Log</span>
                <span className="text-gray-400 text-[10px] truncate max-w-[260px]">{result.log_path}</span>
              </div>
            )}
            {result.returncode != null && (
              <div className="flex items-center justify-between">
                <span className="text-gray-500">Exit code</span>
                <span className={result.returncode === 0 ? 'text-emerald-400' : 'text-red-400'}>
                  {result.returncode}
                </span>
              </div>
            )}

            <WarningList warnings={result.warnings} />

            {result.status === 'pending' && (
              <div className="mt-2 border border-yellow-800/40 rounded p-2 text-[10px] text-yellow-400/80">
                <p className="font-semibold mb-1">Install OpenLane to enable this flow:</p>
                <code className="block bg-black/30 rounded px-2 py-1 text-[9px]">
                  pip install openlane
                </code>
                <p className="mt-1">
                  Or follow{' '}
                  <a
                    href="https://openlane2.readthedocs.io"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline text-indigo-400"
                  >
                    openlane2.readthedocs.io
                  </a>
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
