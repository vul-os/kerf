// PCBInteractiveEditor.jsx — Interactive PCB canvas with push-shove routing.
//
// Wires the Toolbar and Canvas sub-components together.
// Backend contract — tools go through api.callTool (POST /api/tools/call):
//   electronics_route_trace            {start_pad, end_pad, layer, width}
//   electronics_delete_object          {id, type}
//   pcb_shove_trace                    {circuit_json, layer, points, clearance_mm}
//   electronics_tune_diff_pair_lengths {path_a, path_b, target_length_mm, …}
//   pcb_drc                            → {ok, violations:[]}
//   GET /api/projects/:id/pcb          → {pads, traces, keepouts}
//
// Mock fixture is used when no project_id is provided or the load fails.

import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import Toolbar from './pcb-editor/Toolbar.jsx'
import type { PcbTool, PcbLayer } from './pcb-editor/Toolbar.jsx'
import Canvas from './pcb-editor/Canvas.jsx'
import type { Pad, Trace, Keepout, RouteCommit, ShoveCommit, ObjectType, ActiveTool } from './pcb-editor/Canvas.jsx'
import DrcErcPanel from './DrcErcPanel.jsx'
import SIPanel from './SIPanel.jsx'
import SiliconSynthPanel from './SiliconSynthPanel.jsx'
import MultiBoardPanel from './MultiBoardPanel.jsx'
import PCB3DPanel from './PCB3DPanel.jsx'
import EMCPanel from './EMCPanel.jsx'
import PCBThermalPanel from './PCBThermalPanel.jsx'
import { api } from '../../lib/api.js'
import type { CircuitJson } from '../../types'

// ─── Domain types ─────────────────────────────────────────────────────────────

interface BoardSnapshot {
  pads: Pad[]
  traces: Trace[]
  keepouts: Keepout[]
}

interface BoardState extends BoardSnapshot {
  past: BoardSnapshot[]
  future: BoardSnapshot[]
}

type BoardAction =
  | { type: 'LOAD_BOARD'; pads?: Pad[]; traces?: Trace[]; keepouts?: Keepout[] }
  | { type: 'ADD_TRACE'; trace: Trace }
  | { type: 'SHOVE_TRACES'; updatedTraces: Trace[]; newTrace?: Trace | null }
  | { type: 'DELETE_OBJECT'; id: string; objType: ObjectType }
  | { type: 'UNDO' }
  | { type: 'REDO' }

// pcb_shove_trace answers with the whole board back plus the ids it moved;
// distances are mm on the wire, mils in the editor.
interface ShovedTrace {
  id: string
  points?: [number, number][]
  layer: PcbLayer
  width_mm?: number
  net_id?: string
}

interface ShoveResult {
  circuit_json?: { pcb_board?: { pcb_trace?: ShovedTrace[] } }
  shoved_traces?: string[]
}

interface TuneResult {
  error?: string
  _demo?: boolean
  message?: string
  length_a_mm?: number
  meanders_a?: number
  length_b_mm?: number
  meanders_b?: number
  skew_mm?: number
  is_skew_within_tolerance?: boolean
}

// electronics_tune_diff_pair_lengths answers with an {ok, result} envelope;
// on failure `ok` is false and `message` carries the reason.
interface TuneEnvelope {
  ok?: boolean
  result?: TuneResult
  message?: string
}

// ─── Mock fixture ─────────────────────────────────────────────────────────────

const MOCK_PADS: Pad[] = [
  { id: 'pad_u1_1', x: 150, y: 200, layer: 'top', net: 'VCC',  drill: 12, size: 24 },
  { id: 'pad_u1_2', x: 200, y: 200, layer: 'top', net: 'GND',  drill: 12, size: 24 },
  { id: 'pad_u1_3', x: 250, y: 200, layer: 'top', net: 'SDA',  drill: 12, size: 24 },
  { id: 'pad_r1_1', x: 150, y: 400, layer: 'top', net: 'SDA',  drill: 10, size: 20 },
  { id: 'pad_r1_2', x: 225, y: 400, layer: 'top', net: 'SCL',  drill: 10, size: 20 },
  { id: 'pad_c1_1', x: 500, y: 300, layer: 'top', net: 'GND',  drill: 10, size: 20 },
]

const MOCK_TRACES: Trace[] = [
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

const MOCK_KEEPOUTS: Keepout[] = [
  { id: 'ko_mounting', x: 75, y: 75, w: 50, h: 50 },
]

// ─── State machine ────────────────────────────────────────────────────────────

function initialState(): BoardState {
  return {
    pads: MOCK_PADS,
    traces: MOCK_TRACES,
    keepouts: MOCK_KEEPOUTS,
    past: [],   // undo stack (snapshots of {pads,traces,keepouts})
    future: [], // redo stack
  }
}

function snapshot(state: BoardState): BoardSnapshot {
  return { pads: state.pads, traces: state.traces, keepouts: state.keepouts }
}

function reducer(state: BoardState, action: BoardAction): BoardState {
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
  const [tool, setTool] = useState<PcbTool>('select')
  const [layer, setLayer] = useState<PcbLayer>('top')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [drcOk, setDrcOk] = useState<boolean | null>(null)
  const [pushedTraceIds, setPushedTraceIds] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // ── Panel visibility state ─────────────────────────────────────────────────
  const [showDrcPanel, setShowDrcPanel]               = useState(false)
  const [showSIPanel, setShowSIPanel]                 = useState(false)
  const [showSiliconPanel, setShowSiliconPanel]       = useState(false)
  const [showMultiBoardPanel, setShowMultiBoardPanel] = useState(false)
  const [showPCB3DPanel, setShowPCB3DPanel]           = useState(false)
  const [showEMCPanel, setShowEMCPanel]               = useState(false)
  const [showPCBThermalPanel, setShowPCBThermalPanel] = useState(false)

  // ── Tune-Length mode state ─────────────────────────────────────────────────
  const [tuneNetA, setTuneNetA] = useState('')
  const [tuneNetB, setTuneNetB] = useState('')
  const [tuneTargetMm, setTuneTargetMm] = useState('100')
  const [tunePattern, setTunePattern] = useState('arc')
  const [tuneResult, setTuneResult] = useState<TuneResult | null>(null)
  const [tuneLoading, setTuneLoading] = useState(false)

  const drcTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // ── Load board from project ────────────────────────────────────────────────

  useEffect(() => {
    if (!projectId) return
    // eslint-disable-next-line react-hooks/set-state-in-effect -- board-load kickoff on projectId change, pre-existing before this migration.
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
      .catch((err: Error) => {
        console.warn('PCB load failed, using mock fixture:', err.message)
        // silently fall back to mock — the mock is already loaded
      })
      .finally(() => setLoading(false))
  }, [projectId])

  // ── DRC polling (every 2s) ─────────────────────────────────────────────────

  useEffect(() => {
    function runDrc() {
      api.callTool<{ ok?: boolean }>('pcb_drc')
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
    function onKey(e: KeyboardEvent) {
      const targetTag = (e.target as HTMLElement)?.tagName
      if (targetTag === 'INPUT' || targetTag === 'TEXTAREA') return
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

  const handleRouteCommit = useCallback(async ({ start_pad, end_pad, layer: routeLayer, width }: RouteCommit) => {
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
      // Result intentionally unused today — electronics_route_trace's answer isn't
      // consulted before the push-shove call below. Pre-existing, flagging rather than fixing.
      await api.callTool('electronics_route_trace', { start_pad, end_pad, layer: routeLayer, width })
      const shoveData = await api.callTool<ShoveResult>('pcb_shove_trace', {
        circuit_json: circuitJson,
        layer: routeLayer,
        points: provisionalTrace.points.map((p) => [p.x, p.y]),
        clearance_mm: 0.25,
      })
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
    } catch {
      // backend unavailable — apply provisionally
    }

    dispatch({ type: 'ADD_TRACE', trace: provisionalTrace })
  }, [boardState.pads, boardState.traces])

  // ── Shove commit ──────────────────────────────────────────────────────────

  const handleShoveCommit = useCallback(async ({ trace_id, push_vector }: ShoveCommit) => {
    const trace = boardState.traces.find((t) => t.id === trace_id)
    if (!trace) return

    // Apply locally
    const [dx, dy] = push_vector
    const movedTrace = {
      ...trace,
      points: trace.points.map((p) => ({ x: p.x + dx, y: p.y + dy })),
    }

    try {
      await api.callTool('pcb_shove_trace', {
        circuit_json: { pcb_board: { pcb_trace: [] } },
        layer: trace.layer,
        points: movedTrace.points.map((p) => [p.x, p.y]),
        clearance_mm: 0.25,
      })
    } catch {
      /* offline-friendly */
    }

    dispatch({ type: 'SHOVE_TRACES', updatedTraces: [movedTrace], newTrace: null })
  }, [boardState.traces])

  // ── Delete ────────────────────────────────────────────────────────────────

  const handleDeleteObject = useCallback(async (id: string, objType: ObjectType) => {
    dispatch({ type: 'DELETE_OBJECT', id, objType })
    setSelectedId(null)

    try {
      await api.callTool('electronics_delete_object', { id, type: objType })
    } catch {
      /* offline-friendly */
    }
  }, [])

  // ── Selection ─────────────────────────────────────────────────────────────

  const handleSelectObject = useCallback((id: string | null) => {
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
    const toPath = (traces: Trace[]) => traces.flatMap((t) => t.points.map((p) => [p.x * 0.0254, p.y * 0.0254]))
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
      const data = await api.callTool<TuneEnvelope>('electronics_tune_diff_pair_lengths', {
        path_a,
        path_b,
        target_length_mm: target,
        skew_tolerance_mm: 0.025,
        pattern: tunePattern,
        segment_length_mm: 0.5,
        spacing_mm: 0.3,
        corner_radius_mm: 0.15,
      })
      if (data?.ok) {
        setTuneResult(data.result ?? null)
      } else {
        setTuneResult({ error: data?.message ?? 'Tuner backend error.' })
      }
    } catch {
      // Backend unavailable in demo mode — show mock result
      setTuneResult({
        _demo: true,
        message: 'Backend offline — demo mode. In production this calls the electronics_tune_diff_pair_lengths tool.',
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
        onToggleMultiBoardPanel={() => setShowMultiBoardPanel((v) => !v)}
        onTogglePCB3DPanel={() => setShowPCB3DPanel((v) => !v)}
        onToggleEMCPanel={() => setShowEMCPanel((v) => !v)}
        onTogglePCBThermalPanel={() => setShowPCBThermalPanel((v) => !v)}
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
          // Canvas's ActiveTool union predates the 'tune-length' mode (added to Toolbar's
          // PcbTool only) — tune-length is handled entirely by the panel below, and Canvas
          // treats an unrecognized tool the same as 'select'. Pre-existing type gap between
          // Toolbar and Canvas, not introduced by this migration.
          activeTool={tool as ActiveTool}
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
            className="ml-auto text-red-400 hover:text-red-300 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70"
            onClick={() => { handleDeleteObject(selectedId, 'trace'); }}
          >
            Delete
          </button>
          <button
            className="text-gray-500 hover:text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70"
            onClick={() => setSelectedId(null)}
          >
            Deselect
          </button>
        </div>
      )}

      {/* ── Floating overlay panels ───────────────────────────────────────── */}
      {(showDrcPanel || showSIPanel || showSiliconPanel || showMultiBoardPanel || showPCB3DPanel || showEMCPanel || showPCBThermalPanel) && (
        <div
          data-testid="panel-overlay"
          className="absolute inset-0 pointer-events-none z-20 flex items-start justify-end p-4 gap-3 flex-wrap"
          style={{ top: 0, right: 0 }}
        >
          {showDrcPanel && (
            <div className="pointer-events-auto">
              <DrcErcPanel
                // The editor's internal pad/trace/keepout shape is a simplified subset of the
                // real circuit-json schema (see src/types/circuit.ts's note on this same gap in
                // circuitJsonPatch.js) — DrcErcPanel only reads a handful of fields off these at
                // runtime, so the cast is safe without reshaping the editor's state model.
                circuitJson={[
                  ...boardState.pads.map((p) => ({ type: 'pcb_smtpad', ...p })),
                  ...boardState.traces.map((t) => ({ type: 'pcb_trace', ...t })),
                  ...boardState.keepouts.map((k) => ({ type: 'pcb_keepout', ...k })),
                ] as unknown as CircuitJson}
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
          {showMultiBoardPanel && (
            <div className="pointer-events-auto">
              <MultiBoardPanel onClose={() => setShowMultiBoardPanel(false)} />
            </div>
          )}
          {showPCB3DPanel && (
            <div className="pointer-events-auto">
              <PCB3DPanel
                // See the DrcErcPanel cast above — same simplified editor-state shape.
                circuitJson={[
                  ...boardState.pads.map((p) => ({ type: 'pcb_smtpad', ...p })),
                  ...boardState.traces.map((t) => ({ type: 'pcb_trace', ...t })),
                ] as unknown as CircuitJson}
                onClose={() => setShowPCB3DPanel(false)}
              />
            </div>
          )}
          {showEMCPanel && (
            <div className="pointer-events-auto">
              <EMCPanel onClose={() => setShowEMCPanel(false)} />
            </div>
          )}
          {showPCBThermalPanel && (
            <div className="pointer-events-auto">
              <PCBThermalPanel onClose={() => setShowPCBThermalPanel(false)} />
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
            className="px-3 py-1.5 rounded-md bg-teal-700 hover:bg-teal-600 text-white font-medium transition-colors disabled:opacity-40 disabled:pointer-events-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70"
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
