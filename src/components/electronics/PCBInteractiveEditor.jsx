// PCBInteractiveEditor.jsx — Interactive PCB canvas with push-shove routing.
//
// Wires the Toolbar and Canvas sub-components together.
// Backend contract:
//   POST /api/llm-tools/electronics_route_trace           {start_pad, end_pad, layer, width}
//   POST /api/llm-tools/electronics_delete_object         {id, type}
//   POST /api/llm-tools/pcb_shove_trace                   {circuit_json, layer, points, clearance_mm}
//   POST /api/llm-tools/electronics_tune_diff_pair_lengths {path_a, path_b, target_length_mm, …}
//   GET  /api/llm-tools/pcb_drc                           → {ok, violations:[]}
//   GET  /api/projects/:id/pcb                            → {pads, traces, keepouts}
//
// Mock fixture is used when no project_id is provided or the load fails.

import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import Toolbar from './pcb-editor/Toolbar.jsx'
import Canvas from './pcb-editor/Canvas.jsx'
import DrcErcPanel from './DrcErcPanel.jsx'
import SIPanel from './SIPanel.jsx'
import SiliconSynthPanel from './SiliconSynthPanel.jsx'

// ─── Mock fixture ─────────────────────────────────────────────────────────────

const MOCK_PADS = [
  { id: 'pad_u1_1', x: 150, y: 200, layer: 'top', net: 'VCC',  drill: 12, size: 24 },
  { id: 'pad_u1_2', x: 200, y: 200, layer: 'top', net: 'GND',  drill: 12, size: 24 },
  { id: 'pad_u1_3', x: 250, y: 200, layer: 'top', net: 'SDA',  drill: 12, size: 24 },
  { id: 'pad_r1_1', x: 150, y: 400, layer: 'top', net: 'SDA',  drill: 10, size: 20 },
  { id: 'pad_r1_2', x: 225, y: 400, layer: 'top', net: 'SCL',  drill: 10, size: 20 },
  { id: 'pad_c1_1', x: 500, y: 300, layer: 'top', net: 'GND',  drill: 10, size: 20 },
]

const MOCK_TRACES = [
  {
    id: 'tr_vcc',
    points: [{ x: 150, y: 200 }, { x: 150, y: 100 }, { x: 600, y: 100 }],
    layer: 'top',
    width: 12,
    net: 'VCC',
  },
  {
    id: 'tr_gnd',
    points: [{ x: 200, y: 200 }, { x: 200, y: 450 }, { x: 500, y: 450 }, { x: 500, y: 300 }],
    layer: 'top',
    width: 12,
    net: 'GND',
  },
  {
    id: 'tr_sda',
    points: [{ x: 250, y: 200 }, { x: 250, y: 350 }, { x: 150, y: 350 }, { x: 150, y: 400 }],
    layer: 'top',
    width: 8,
    net: 'SDA',
  },
]

const MOCK_KEEPOUTS = [
  { id: 'ko_mounting', x: 75, y: 75, w: 50, h: 50 },
]

// ─── State machine ────────────────────────────────────────────────────────────

function initialState() {
  return {
    pads: MOCK_PADS,
    traces: MOCK_TRACES,
    keepouts: MOCK_KEEPOUTS,
    past: [],   // undo stack (snapshots of {pads,traces,keepouts})
    future: [], // redo stack
  }
}

function snapshot(state) {
  return { pads: state.pads, traces: state.traces, keepouts: state.keepouts }
}

function reducer(state, action) {
  switch (action.type) {
    case 'LOAD_BOARD':
      return {
        ...state,
        pads: action.pads ?? state.pads,
        traces: action.traces ?? state.traces,
        keepouts: action.keepouts ?? state.keepouts,
        past: [],
        future: [],
      }

    case 'ADD_TRACE': {
      const snap = snapshot(state)
      return {
        ...state,
        traces: [...state.traces, action.trace],
        past: [...state.past, snap],
        future: [],
      }
    }

    case 'SHOVE_TRACES': {
      const snap = snapshot(state)
      // Replace updated traces returned by the server (or apply local delta)
      const updatedMap = new Map(action.updatedTraces.map((t) => [t.id, t]))
      const next = state.traces.map((t) => updatedMap.get(t.id) ?? t)
      // Append the new routed trace if provided
      if (action.newTrace) next.push(action.newTrace)
      return { ...state, traces: next, past: [...state.past, snap], future: [] }
    }

    case 'DELETE_OBJECT': {
      const snap = snapshot(state)
      const { id, objType } = action
      return {
        ...state,
        traces: objType === 'trace' ? state.traces.filter((t) => t.id !== id) : state.traces,
        pads:   objType === 'pad'   ? state.pads.filter((p) => p.id !== id)   : state.pads,
        past: [...state.past, snap],
        future: [],
      }
    }

    case 'UNDO': {
      if (state.past.length === 0) return state
      const prev = state.past[state.past.length - 1]
      return {
        ...state,
        ...prev,
        past: state.past.slice(0, -1),
        future: [snapshot(state), ...state.future],
      }
    }

    case 'REDO': {
      if (state.future.length === 0) return state
      const next = state.future[0]
      return {
        ...state,
        ...next,
        past: [...state.past, snapshot(state)],
        future: state.future.slice(1),
      }
    }

    default:
      return state
  }
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function PCBInteractiveEditor() {
  const [searchParams] = useSearchParams()
  const projectId = searchParams.get('project_id')

  const [boardState, dispatch] = useReducer(reducer, undefined, initialState)
  const [tool, setTool] = useState('select')
  const [layer, setLayer] = useState('top')
  const [selectedId, setSelectedId] = useState(null)
  const [drcOk, setDrcOk] = useState(null)
  const [pushedTraceIds, setPushedTraceIds] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // ── Panel visibility state ─────────────────────────────────────────────────
  const [showDrcPanel, setShowDrcPanel]         = useState(false)
  const [showSIPanel, setShowSIPanel]           = useState(false)
  const [showSiliconPanel, setShowSiliconPanel] = useState(false)

  // ── Tune-Length mode state ─────────────────────────────────────────────────
  const [tuneNetA, setTuneNetA] = useState('')
  const [tuneNetB, setTuneNetB] = useState('')
  const [tuneTargetMm, setTuneTargetMm] = useState('100')
  const [tunePattern, setTunePattern] = useState('arc')
  const [tuneResult, setTuneResult] = useState(null)
  const [tuneLoading, setTuneLoading] = useState(false)

  const drcTimerRef = useRef(null)

  // ── Load board from project ────────────────────────────────────────────────

  useEffect(() => {
    if (!projectId) return
    setLoading(true)
    setError(null)
    fetch(`/api/projects/${projectId}/pcb`, {
      headers: { 'content-type': 'application/json' },
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data) => {
        dispatch({
          type: 'LOAD_BOARD',
          pads: data?.pads,
          traces: data?.traces,
          keepouts: data?.keepouts,
        })
      })
      .catch((err) => {
        console.warn('PCB load failed, using mock fixture:', err.message)
        // silently fall back to mock — the mock is already loaded
      })
      .finally(() => setLoading(false))
  }, [projectId])

  // ── DRC polling (every 2s) ─────────────────────────────────────────────────

  useEffect(() => {
    function runDrc() {
      fetch('/api/llm-tools/pcb_drc', {
        method: 'GET',
        headers: { 'content-type': 'application/json' },
      })
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (data != null) setDrcOk(data.ok !== false)
        })
        .catch(() => { /* no backend in demo */ })
    }
    runDrc()
    drcTimerRef.current = setInterval(runDrc, 2000)
    return () => clearInterval(drcTimerRef.current)
  }, [])

  // ── Keyboard shortcuts ─────────────────────────────────────────────────────

  useEffect(() => {
    function onKey(e) {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'z') {
        dispatch({ type: 'REDO' })
      } else if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
        dispatch({ type: 'UNDO' })
      } else if (e.key === 'Escape') {
        setTool('select')
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // ── Route commit ──────────────────────────────────────────────────────────

  const handleRouteCommit = useCallback(async ({ start_pad, end_pad, layer: routeLayer, width }) => {
    const startPad = boardState.pads.find((p) => p.id === start_pad)
    const endPad   = boardState.pads.find((p) => p.id === end_pad)
    if (!startPad || !endPad) return

    // Build a provisional local trace immediately for responsiveness
    const provisionalTrace = {
      id: `tr_${Date.now()}`,
      points: [
        { x: startPad.x, y: startPad.y },
        { x: endPad.x,   y: endPad.y   },
      ],
      layer: routeLayer,
      width,
      net: startPad.net ?? 'new',
    }

    // POST to backend with push-shove
    const circuitJson = {
      pcb_board: {
        pcb_trace: boardState.traces.map((t) => ({
          id: t.id,
          net_id: t.net,
          layer: t.layer,
          width_mm: t.width * 0.0254,  // mil → mm
          points: t.points.map((p) => [p.x * 0.0254, p.y * 0.0254]),
        })),
      },
    }

    try {
      const res = await fetch('/api/llm-tools/electronics_route_trace', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ start_pad, end_pad, layer: routeLayer, width }),
      })
      if (res.ok) {
        const data = await res.json()
        const shoveRes = await fetch('/api/llm-tools/pcb_shove_trace', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            circuit_json: circuitJson,
            layer: routeLayer,
            points: provisionalTrace.points.map((p) => [p.x, p.y]),
            clearance_mm: 0.25,
          }),
        })
        if (shoveRes.ok) {
          const shoveData = await shoveRes.json()
          const updatedTraces = (shoveData.circuit_json?.pcb_board?.pcb_trace ?? [])
            .filter((t) => shoveData.shoved_traces?.includes(t.id))
            .map((t) => ({
              id: t.id,
              points: (t.points ?? []).map(([x, y]) => ({ x: x / 0.0254, y: y / 0.0254 })),
              layer: t.layer,
              width: (t.width_mm ?? 0.25) / 0.0254,
              net: t.net_id,
            }))
          setPushedTraceIds(shoveData.shoved_traces ?? [])
          setTimeout(() => setPushedTraceIds([]), 1500)
          dispatch({ type: 'SHOVE_TRACES', updatedTraces, newTrace: provisionalTrace })
          return
        }
      }
    } catch {
      // backend unavailable — apply provisionally
    }

    dispatch({ type: 'ADD_TRACE', trace: provisionalTrace })
  }, [boardState.pads, boardState.traces])

  // ── Shove commit ──────────────────────────────────────────────────────────

  const handleShoveCommit = useCallback(async ({ trace_id, push_vector }) => {
    const trace = boardState.traces.find((t) => t.id === trace_id)
    if (!trace) return

    // Apply locally
    const [dx, dy] = push_vector
    const movedTrace = {
      ...trace,
      points: trace.points.map((p) => ({ x: p.x + dx, y: p.y + dy })),
    }

    try {
      await fetch('/api/llm-tools/pcb_shove_trace', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          circuit_json: { pcb_board: { pcb_trace: [] } },
          layer: trace.layer,
          points: movedTrace.points.map((p) => [p.x, p.y]),
          clearance_mm: 0.25,
        }),
      })
    } catch {
      /* offline-friendly */
    }

    dispatch({ type: 'SHOVE_TRACES', updatedTraces: [movedTrace], newTrace: null })
  }, [boardState.traces])

  // ── Delete ────────────────────────────────────────────────────────────────

  const handleDeleteObject = useCallback(async (id, objType) => {
    dispatch({ type: 'DELETE_OBJECT', id, objType })
    setSelectedId(null)

    try {
      await fetch('/api/llm-tools/electronics_delete_object', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ id, type: objType }),
      })
    } catch {
      /* offline-friendly */
    }
  }, [])

  // ── Selection ─────────────────────────────────────────────────────────────

  const handleSelectObject = useCallback((id) => {
    setSelectedId(id)
  }, [])

  // ── Tune-Length: diff-pair serpentine insertion ────────────────────────────
  // Sends path_a and path_b polylines (traces by net name) to the backend
  // electronics_tune_diff_pair_lengths tool and stores the result.
  // Reference: Hall & Heck 2009 §3.6; IPC-2141A §6; Wittwer 2012 DesignCon.

  const handleTuneDiffPair = useCallback(async () => {
    const tracesA = boardState.traces.filter((t) => t.net === tuneNetA)
    const tracesB = boardState.traces.filter((t) => t.net === tuneNetB)

    if (tracesA.length === 0 || tracesB.length === 0) {
      setTuneResult({ error: 'No traces found for one or both net names.' })
      return
    }

    // Flatten all points from each net's traces (simple concatenation)
    const toPath = (traces) => traces.flatMap((t) => t.points.map((p) => [p.x * 0.0254, p.y * 0.0254]))
    const path_a = toPath(tracesA)
    const path_b = toPath(tracesB)

    const target = parseFloat(tuneTargetMm)
    if (isNaN(target) || target <= 0) {
      setTuneResult({ error: 'Target length must be a positive number.' })
      return
    }

    setTuneLoading(true)
    setTuneResult(null)

    try {
      const res = await fetch('/api/llm-tools/electronics_tune_diff_pair_lengths', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          path_a,
          path_b,
          target_length_mm: target,
          skew_tolerance_mm: 0.025,
          pattern: tunePattern,
          segment_length_mm: 0.5,
          spacing_mm: 0.3,
          corner_radius_mm: 0.15,
        }),
      })
      const data = await res.json()
      if (data?.ok) {
        setTuneResult(data.result)
      } else {
        setTuneResult({ error: data?.message ?? 'Tuner backend error.' })
      }
    } catch {
      // Backend unavailable in demo mode — show mock result
      setTuneResult({
        _demo: true,
        message: 'Backend offline — demo mode. In production this posts to /api/llm-tools/electronics_tune_diff_pair_lengths.',
      })
    } finally {
      setTuneLoading(false)
    }
  }, [boardState.traces, tuneNetA, tuneNetB, tuneTargetMm, tunePattern])

  // ─────────────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-full bg-[#0f172a] text-white font-mono relative">
      {/* Toolbar */}
      <Toolbar
        tool={tool}
        onToolChange={setTool}
        layer={layer}
        onLayerChange={setLayer}
        drcOk={drcOk}
        canUndo={boardState.past.length > 0}
        canRedo={boardState.future.length > 0}
        onUndo={() => dispatch({ type: 'UNDO' })}
        onRedo={() => dispatch({ type: 'REDO' })}
        onToggleDrcPanel={() => setShowDrcPanel((v) => !v)}
        onToggleSIPanel={() => setShowSIPanel((v) => !v)}
        onToggleSiliconPanel={() => setShowSiliconPanel((v) => !v)}
      />

      {/* Status bar */}
      <div className="flex items-center gap-4 px-3 py-1 bg-[#1e293b] text-xs text-gray-500 border-b border-white/5">
        <span>{boardState.pads.length} pads</span>
        <span>{boardState.traces.length} traces</span>
        {loading && <span className="text-indigo-400 animate-pulse">Loading board…</span>}
        {error && <span className="text-red-400">{error}</span>}
        {tool === 'route' && (
          <span className="text-indigo-300">Click a pad to start routing · click target pad to finish · Esc to cancel</span>
        )}
        {tool === 'push-shove' && (
          <span className="text-yellow-300">Click a trace and drag to push-shove</span>
        )}
        {tool === 'delete' && (
          <span className="text-red-300">Click a trace or pad to delete</span>
        )}
        {tool === 'tune-length' && (
          <span className="text-teal-300">Select nets P + N, set target length, click Tune — serpentine meanders inserted (Wittwer 2012)</span>
        )}
        <span className="ml-auto text-gray-600">
          {projectId ? `project: ${projectId}` : 'demo fixture'}
        </span>
      </div>

      {/* Canvas */}
      <div className="flex-1 overflow-hidden" data-testid="pcb-canvas-container">
        <Canvas
          pads={boardState.pads}
          traces={boardState.traces}
          keepouts={boardState.keepouts}
          activeTool={tool}
          activeLayer={layer}
          selectedId={selectedId}
          onSelectObject={handleSelectObject}
          onRouteCommit={handleRouteCommit}
          onShoveCommit={handleShoveCommit}
          onDeleteObject={handleDeleteObject}
          pushedTraceIds={pushedTraceIds}
        />
      </div>

      {/* Selection info strip */}
      {selectedId && (
        <div className="px-3 py-1.5 bg-[#1e293b] border-t border-white/5 text-xs text-gray-400 flex items-center gap-3">
          <span>Selected: <code className="text-indigo-300">{selectedId}</code></span>
          <button
            className="ml-auto text-red-400 hover:text-red-300 transition-colors"
            onClick={() => { handleDeleteObject(selectedId, 'trace'); }}
          >
            Delete
          </button>
          <button
            className="text-gray-500 hover:text-white transition-colors"
            onClick={() => setSelectedId(null)}
          >
            Deselect
          </button>
        </div>
      )}

      {/* ── Floating overlay panels ───────────────────────────────────────── */}
      {(showDrcPanel || showSIPanel || showSiliconPanel) && (
        <div
          data-testid="panel-overlay"
          className="absolute inset-0 pointer-events-none z-20 flex items-start justify-end p-4 gap-3 flex-wrap"
          style={{ top: 0, right: 0 }}
        >
          {showDrcPanel && (
            <div className="pointer-events-auto">
              <DrcErcPanel
                circuitJson={[
                  ...boardState.pads.map((p) => ({ type: 'pcb_smtpad', ...p })),
                  ...boardState.traces.map((t) => ({ type: 'pcb_trace', ...t })),
                  ...boardState.keepouts.map((k) => ({ type: 'pcb_keepout', ...k })),
                ]}
                onClose={() => setShowDrcPanel(false)}
                onMarkerClick={null}
              />
            </div>
          )}
          {showSIPanel && (
            <div className="pointer-events-auto">
              <SIPanel onClose={() => setShowSIPanel(false)} />
            </div>
          )}
          {showSiliconPanel && (
            <div className="pointer-events-auto">
              <SiliconSynthPanel onClose={() => setShowSiliconPanel(false)} />
            </div>
          )}
        </div>
      )}

      {/* ── Tune Length panel — shown when tune-length tool is active ─────── */}
      {tool === 'tune-length' && (
        <div
          data-testid="tune-length-panel"
          className="px-3 py-2 bg-[#0d2233] border-t border-teal-800/50 text-xs text-gray-300 flex flex-wrap items-end gap-3"
        >
          <span className="text-teal-400 font-semibold text-[11px] shrink-0">
            Diff-Pair Length Tuner
          </span>

          {/* Net P */}
          <label className="flex flex-col gap-0.5">
            <span className="text-gray-500">Net P (trace A)</span>
            <input
              data-testid="tune-net-a"
              type="text"
              value={tuneNetA}
              onChange={(e) => setTuneNetA(e.target.value)}
              placeholder="e.g. USB_DP"
              className="bg-black/40 border border-white/10 rounded px-2 py-1 text-white placeholder-gray-600 w-24 focus:outline-none focus:border-teal-600"
            />
          </label>

          {/* Net N */}
          <label className="flex flex-col gap-0.5">
            <span className="text-gray-500">Net N (trace B)</span>
            <input
              data-testid="tune-net-b"
              type="text"
              value={tuneNetB}
              onChange={(e) => setTuneNetB(e.target.value)}
              placeholder="e.g. USB_DM"
              className="bg-black/40 border border-white/10 rounded px-2 py-1 text-white placeholder-gray-600 w-24 focus:outline-none focus:border-teal-600"
            />
          </label>

          {/* Target length */}
          <label className="flex flex-col gap-0.5">
            <span className="text-gray-500">Target (mm)</span>
            <input
              data-testid="tune-target-mm"
              type="number"
              min="0.1"
              step="0.1"
              value={tuneTargetMm}
              onChange={(e) => setTuneTargetMm(e.target.value)}
              className="bg-black/40 border border-white/10 rounded px-2 py-1 text-white w-20 focus:outline-none focus:border-teal-600"
            />
          </label>

          {/* Pattern */}
          <label className="flex flex-col gap-0.5">
            <span className="text-gray-500">Pattern</span>
            <select
              data-testid="tune-pattern"
              value={tunePattern}
              onChange={(e) => setTunePattern(e.target.value)}
              className="bg-black/40 border border-white/10 rounded px-2 py-1 text-white focus:outline-none focus:border-teal-600"
            >
              <option value="arc">Arc (best SI)</option>
              <option value="rectangular">Rectangular</option>
              <option value="chamfered_45">45° Chamfer</option>
            </select>
          </label>

          {/* Tune button */}
          <button
            data-testid="tune-run-btn"
            onClick={handleTuneDiffPair}
            disabled={tuneLoading}
            className="px-3 py-1.5 rounded-md bg-teal-700 hover:bg-teal-600 text-white font-medium transition-colors disabled:opacity-40 disabled:pointer-events-none"
          >
            {tuneLoading ? 'Tuning…' : 'Tune Pair'}
          </button>

          {/* Result inline */}
          {tuneResult && !tuneResult.error && !tuneResult._demo && (
            <div className="text-[11px] text-gray-300 flex gap-3 flex-wrap">
              <span>
                A: <span className="text-teal-300">{tuneResult.length_a_mm?.toFixed(3)} mm</span>
                {' '}({tuneResult.meanders_a} meanders)
              </span>
              <span>
                B: <span className="text-teal-300">{tuneResult.length_b_mm?.toFixed(3)} mm</span>
                {' '}({tuneResult.meanders_b} meanders)
              </span>
              <span>
                Skew: <span className={tuneResult.is_skew_within_tolerance ? 'text-emerald-400' : 'text-red-400'}>
                  {(tuneResult.skew_mm * 1000)?.toFixed(1)} μm
                </span>
                {' '}{tuneResult.is_skew_within_tolerance ? '✓' : '✗'}
              </span>
            </div>
          )}
          {tuneResult?.error && (
            <span className="text-red-400">{tuneResult.error}</span>
          )}
          {tuneResult?._demo && (
            <span className="text-yellow-500 text-[11px]">{tuneResult.message}</span>
          )}
        </div>
      )}
    </div>
  )
}
