// PCBInteractiveEditor.jsx — Interactive PCB canvas with push-shove routing.
//
// Wires the Toolbar and Canvas sub-components together.
// Backend contract:
//   POST /api/llm-tools/electronics_route_trace  {start_pad, end_pad, layer, width}
//   POST /api/llm-tools/electronics_delete_object {id, type}
//   POST /api/llm-tools/pcb_shove_trace           {circuit_json, layer, points, clearance_mm}
//   GET  /api/llm-tools/pcb_drc                   → {ok, violations:[]}
//   GET  /api/projects/:id/pcb                    → {pads, traces, keepouts}
//
// Mock fixture is used when no project_id is provided or the load fails.

import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import Toolbar from './pcb-editor/Toolbar.jsx'
import Canvas from './pcb-editor/Canvas.jsx'

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

  // ─────────────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-full bg-[#0f172a] text-white font-mono">
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
    </div>
  )
}
