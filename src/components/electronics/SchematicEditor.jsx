// SchematicEditor.jsx — LTspice-equivalent web schematic capture GUI.
//
// Architecture:
//   Left  → PartLibrary  (15 parts, grouped, drag-to-place)
//   Centre → Canvas      (SVG, 1600×1000 mil, 25-mil grid)
//   Right  → PropertiesPanel (selected component params)
//   Top    → Toolbar     (mode, undo/redo, Run Simulation)
//   Bottom → ProbeOverlay (waveform plot, SVG-only)
//
// Backend:
//   POST /run-spice  {netlist, analysis, probes}
//   Returns {waveforms: [{name, kind, x, y}]}
//
// State is managed with useReducer for undo/redo support.

import { useCallback, useEffect, useReducer, useState } from 'react'
import Canvas from './schematic-editor/Canvas.jsx'
import PartLibrary from './schematic-editor/PartLibrary.jsx'
import PropertiesPanel from './schematic-editor/PropertiesPanel.jsx'
import ProbeOverlay from './schematic-editor/probe_overlay.jsx'
import { PARTS_MAP } from './schematic-editor/parts_library.js'

// ─── Netlist serializer ───────────────────────────────────────────────────────
// Converts the schematic state into a SPICE netlist string suitable for
// POST /run-spice. Node numbers are assigned by flood-fill from wires/pins.

function buildNetlist(devices, wires, probes) {
  // 1. Assign net names based on connected wire segments
  //    Each wire gets a net; pins connected to the same wire share the net.
  //    Simple approach: label nets N1..Nn, with '0' reserved for GND.

  const netMap = new Map() // pin-key → net-name
  let netCounter = 1

  function pinKey(devId, pinId) { return `${devId}::${pinId}` }

  // Assign GND nets first
  for (const dev of devices) {
    if (dev.partId === 'GND') {
      const key = pinKey(dev.id, 'GND')
      netMap.set(key, dev.props?.net ?? '0')
    }
  }

  // For each wire, collect all pin-keys within snapping distance (6 mil)
  for (const wire of wires) {
    if (!wire.points?.length) continue
    const netName = `N${netCounter++}`

    // Endpoints of each wire segment
    const endpoints = [wire.points[0], wire.points[wire.points.length - 1]]

    for (const ep of endpoints) {
      for (const dev of devices) {
        const partDef = PARTS_MAP[dev.partId]
        if (!partDef) continue
        for (const pin of partDef.pins) {
          const px = dev.x + pin.dx
          const py = dev.y + pin.dy
          if (Math.hypot(px - ep.x, py - ep.y) < 10) {
            const key = pinKey(dev.id, pin.id)
            if (!netMap.has(key)) netMap.set(key, netName)
          }
        }
      }
    }
  }

  // Assign unconnected pins to floating nets
  for (const dev of devices) {
    const partDef = PARTS_MAP[dev.partId]
    if (!partDef) continue
    for (const pin of partDef.pins) {
      const key = pinKey(dev.id, pin.id)
      if (!netMap.has(key)) netMap.set(key, `F${netCounter++}`)
    }
  }

  // 2. Build SPICE lines
  const lines = ['* Kerf Schematic Export']
  const refCounts = {}

  for (const dev of devices) {
    const partDef = PARTS_MAP[dev.partId]
    if (!partDef || !partDef.spicePrefix) continue

    const prefix = partDef.spicePrefix
    refCounts[prefix] = (refCounts[prefix] ?? 0) + 1
    const refDes = dev.label || `${prefix}${refCounts[prefix]}`
    const nets = partDef.pins.map((pin) => netMap.get(pinKey(dev.id, pin.id)) ?? '0').join(' ')

    switch (dev.partId) {
      case 'R':
        lines.push(`${refDes} ${nets} ${dev.props?.resistance ?? '1k'}`)
        break
      case 'C':
        lines.push(`${refDes} ${nets} ${dev.props?.capacitance ?? '100n'}`)
        break
      case 'L':
        lines.push(`${refDes} ${nets} ${dev.props?.inductance ?? '100u'}`)
        break
      case 'Diode':
      case 'LED':
      case 'Zener':
        lines.push(`${refDes} ${nets} ${dev.props?.model ?? 'D1N4148'}`)
        break
      case 'NMOS':
      case 'PMOS': {
        const W = dev.props?.W ?? '10u'
        const L = dev.props?.L ?? '1u'
        const model = dev.props?.model ?? (dev.partId === 'NMOS' ? 'NMOS_GENERIC' : 'PMOS_GENERIC')
        lines.push(`${refDes} ${nets} ${model} W=${W} L=${L}`)
        break
      }
      case 'NPN':
      case 'PNP':
        lines.push(`${refDes} ${nets} ${dev.props?.model ?? 'Q2N3904'}`)
        break
      case 'OpAmp': {
        const model = dev.props?.model ?? 'OPAMP_IDEAL'
        lines.push(`${refDes} ${nets} ${model}`)
        break
      }
      case 'VSource':
        if ((dev.props?.type ?? 'dc') === 'dc') {
          lines.push(`${refDes} ${nets} DC ${dev.props?.dc ?? '5'}`)
        } else {
          lines.push(`${refDes} ${nets} AC ${dev.props?.ac ?? '1'} DC ${dev.props?.dc ?? '0'}`)
        }
        break
      case 'ISource':
        lines.push(`${refDes} ${nets} DC ${dev.props?.dc ?? '1m'}`)
        break
      default:
        break
    }
  }

  // Default transient analysis
  lines.push('.TRAN 1us 10ms')
  lines.push('.END')

  // Collect probe expressions
  const probeExprs = probes
    .filter((d) => d.partId === 'Probe')
    .map((d) => {
      const pinKey2 = `${d.id}::TIP`
      const net = netMap.get(pinKey2) ?? '0'
      return d.props?.kind === 'current' ? `I(${net})` : `V(${net})`
    })

  return { netlist: lines.join('\n'), probeExprs }
}

// ─── State machine ────────────────────────────────────────────────────────────

function initialState() {
  return {
    devices: [],
    wires: [],
    past:   [],
    future: [],
    refCounts: {},
  }
}

function snapshot(state) {
  return { devices: state.devices, wires: state.wires, refCounts: state.refCounts }
}

let _nextId = 1
function nextId(prefix) {
  return `${prefix}_${_nextId++}`
}

function reducer(state, action) {
  switch (action.type) {
    case 'ADD_DEVICE': {
      const snap = snapshot(state)
      const partDef = PARTS_MAP[action.partId]
      const prefix  = partDef?.spicePrefix || action.partId[0]
      const count   = (state.refCounts[prefix] ?? 0) + 1
      const label   = `${prefix}${count}`
      const dev = {
        id:     nextId(action.partId),
        partId: action.partId,
        x:      action.x,
        y:      action.y,
        props:  { ...(partDef?.defaultProps ?? {}) },
        label,
      }
      return {
        ...state,
        devices: [...state.devices, dev],
        refCounts: { ...state.refCounts, [prefix]: count },
        past: [...state.past, snap],
        future: [],
      }
    }

    case 'ADD_WIRE': {
      const snap = snapshot(state)
      const wire = {
        id:     nextId('wire'),
        points: action.points,
      }
      return {
        ...state,
        wires: [...state.wires, wire],
        past:  [...state.past, snap],
        future: [],
      }
    }

    case 'UPDATE_PROPS': {
      const snap = snapshot(state)
      return {
        ...state,
        devices: state.devices.map((d) =>
          d.id === action.deviceId ? { ...d, props: action.props } : d
        ),
        past:   [...state.past, snap],
        future: [],
      }
    }

    case 'UPDATE_LABEL': {
      const snap = snapshot(state)
      return {
        ...state,
        devices: state.devices.map((d) =>
          d.id === action.deviceId ? { ...d, label: action.label } : d
        ),
        past:   [...state.past, snap],
        future: [],
      }
    }

    case 'DELETE_OBJECT': {
      const snap = snapshot(state)
      if (action.objType === 'wire') {
        return {
          ...state,
          wires:  state.wires.filter((w) => w.id !== action.id),
          past:   [...state.past, snap],
          future: [],
        }
      }
      return {
        ...state,
        devices: state.devices.filter((d) => d.id !== action.id),
        past:    [...state.past, snap],
        future:  [],
      }
    }

    case 'UNDO': {
      if (!state.past.length) return state
      const prev = state.past[state.past.length - 1]
      return {
        ...state,
        ...prev,
        past:   state.past.slice(0, -1),
        future: [snapshot(state), ...state.future],
      }
    }

    case 'REDO': {
      if (!state.future.length) return state
      const next = state.future[0]
      return {
        ...state,
        ...next,
        past:   [...state.past, snapshot(state)],
        future: state.future.slice(1),
      }
    }

    case 'CLEAR': {
      _nextId = 1
      return { ...initialState() }
    }

    default:
      return state
  }
}

// ─── Toolbar ──────────────────────────────────────────────────────────────────

const TOOLS = [
  { id: 'select', label: 'Select',    key: 'S', icon: '↖' },
  { id: 'wire',   label: 'Wire',      key: 'W', icon: '/' },
  { id: 'add',    label: 'Add Part',  key: 'A', icon: '+' },
  { id: 'probe',  label: 'Probe',     key: 'P', icon: '◎' },
  { id: 'delete', label: 'Delete',    key: 'D', icon: '✕' },
]

function Toolbar({ tool, onToolChange, canUndo, canRedo, onUndo, onRedo, onSimulate, simRunning, onClear }) {
  return (
    <div className="flex items-center gap-2 px-3 py-2 bg-[#0b1120] border-b border-white/10 flex-shrink-0">
      {/* Mode buttons */}
      <div className="flex gap-1">
        {TOOLS.map((t) => (
          <button
            key={t.id}
            data-testid={`tool-${t.id}`}
            onClick={() => onToolChange(t.id)}
            title={`${t.label} (${t.key})`}
            className={[
              'px-2.5 py-1 text-xs rounded font-mono transition-colors',
              tool === t.id
                ? 'bg-indigo-600 text-white'
                : 'bg-white/5 text-gray-400 hover:bg-white/10 hover:text-white',
            ].join(' ')}
          >
            <span className="mr-1">{t.icon}</span>{t.label}
          </button>
        ))}
      </div>

      <div className="w-px h-5 bg-white/10 mx-1" />

      {/* Undo/Redo */}
      <button
        onClick={onUndo}
        disabled={!canUndo}
        data-testid="btn-undo"
        className="px-2 py-1 text-xs rounded bg-white/5 text-gray-400 disabled:opacity-30 hover:bg-white/10 hover:text-white transition-colors"
        title="Undo (Ctrl+Z)"
      >
        ↩ Undo
      </button>
      <button
        onClick={onRedo}
        disabled={!canRedo}
        data-testid="btn-redo"
        className="px-2 py-1 text-xs rounded bg-white/5 text-gray-400 disabled:opacity-30 hover:bg-white/10 hover:text-white transition-colors"
        title="Redo (Ctrl+Shift+Z)"
      >
        ↪ Redo
      </button>

      <button
        onClick={onClear}
        className="px-2 py-1 text-xs rounded bg-white/5 text-gray-500 hover:bg-red-900/30 hover:text-red-400 transition-colors"
        title="Clear schematic"
      >
        Clear
      </button>

      <div className="flex-1" />

      {/* Run simulation */}
      <button
        onClick={onSimulate}
        disabled={simRunning}
        data-testid="btn-run-simulation"
        className={[
          'px-4 py-1.5 text-xs rounded font-semibold transition-colors',
          simRunning
            ? 'bg-indigo-800 text-indigo-300 cursor-not-allowed'
            : 'bg-indigo-600 hover:bg-indigo-500 text-white',
        ].join(' ')}
      >
        {simRunning ? '⏳ Running…' : '▶ Run Simulation'}
      </button>
    </div>
  )
}

// ─── Status bar ───────────────────────────────────────────────────────────────

function StatusBar({ tool, devices, wires, simError, addingPartId }) {
  const hints = {
    select: 'Click a component or wire to select it',
    wire:   'Click to start wire · click again to add bends · double-click to finish · Esc to cancel',
    add:    addingPartId ? `Placing ${addingPartId} — click to place` : 'Select a part from the sidebar first',
    probe:  'Click a net to add a voltage probe',
    delete: 'Click a component or wire to delete it',
  }

  return (
    <div className="flex items-center gap-4 px-3 py-1 bg-[#0b1120] border-b border-white/5 text-xs text-gray-500 flex-shrink-0">
      <span>{devices.length} components</span>
      <span>{wires.length} wires</span>
      <span className="text-indigo-400">{hints[tool]}</span>
      {simError && (
        <span className="ml-auto text-red-400 truncate max-w-xs" title={simError}>
          ⚠ {simError}
        </span>
      )}
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function SchematicEditor() {
  const [state, dispatch] = useReducer(reducer, undefined, initialState)
  const [tool, setTool] = useState('select')
  const [addingPartId, setAddingPartId] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [selectedType, setSelectedType] = useState(null)
  const [simRunning, setSimRunning] = useState(false)
  const [simError, setSimError] = useState(null)
  const [waveforms, setWaveforms] = useState([])

  // Switch to add mode when a part is selected from the library
  const handleSelectPart = useCallback((partId) => {
    setAddingPartId(partId)
    setTool('add')
  }, [])

  const handleDragStart = useCallback((partId, e) => {
    e.dataTransfer?.setData('partId', partId)
    setAddingPartId(partId)
  }, [])

  // Add a device at position
  const handleAddDevice = useCallback(({ partId, x, y }) => {
    dispatch({ type: 'ADD_DEVICE', partId, x, y })
  }, [])

  // Commit a completed wire
  const handleWireCommit = useCallback((points) => {
    if (points.length >= 2) {
      dispatch({ type: 'ADD_WIRE', points })
    }
  }, [])

  // Select object
  const handleSelectObject = useCallback((id, type) => {
    setSelectedId(id)
    setSelectedType(type)
  }, [])

  // Delete object
  const handleDeleteObject = useCallback((id, objType) => {
    dispatch({ type: 'DELETE_OBJECT', id, objType })
    if (selectedId === id) {
      setSelectedId(null)
      setSelectedType(null)
    }
  }, [selectedId])

  // Update component props
  const handleUpdateProps = useCallback((deviceId, props) => {
    dispatch({ type: 'UPDATE_PROPS', deviceId, props })
  }, [])

  // Update label
  const handleUpdateLabel = useCallback((deviceId, label) => {
    dispatch({ type: 'UPDATE_LABEL', deviceId, label })
  }, [])

  // Add probe device
  const handleAddProbe = useCallback(({ x, y, netLabel }) => {
    dispatch({ type: 'ADD_DEVICE', partId: 'Probe', x, y })
  }, [])

  // ── Keyboard shortcuts ─────────────────────────────────────────────────

  useEffect(() => {
    const shortcutMap = { s: 'select', w: 'wire', a: 'add', p: 'probe', d: 'delete' }
    function onKey(e) {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'z') {
        dispatch({ type: 'REDO' })
        return
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        dispatch({ type: 'UNDO' })
        return
      }
      if (e.key === 'Escape') {
        setTool('select')
        setAddingPartId(null)
        return
      }
      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (selectedId) {
          handleDeleteObject(selectedId, selectedType)
        }
        return
      }
      const mapped = shortcutMap[e.key.toLowerCase()]
      if (mapped) setTool(mapped)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selectedId, selectedType, handleDeleteObject])

  // ── Run simulation ─────────────────────────────────────────────────────

  const handleSimulate = useCallback(async () => {
    setSimRunning(true)
    setSimError(null)
    setWaveforms([])

    try {
      const probeDevices = state.devices.filter((d) => d.partId === 'Probe')
      const { netlist, probeExprs } = buildNetlist(state.devices, state.wires, probeDevices)

      const payload = {
        netlist,
        analysis: { type: 'tran', tstep: '1us', tstop: '10ms' },
        probes: probeExprs.length ? probeExprs : ['V(N1)'],
      }

      const res = await fetch('/run-spice', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      })

      if (!res.ok) {
        const text = await res.text()
        throw new Error(`HTTP ${res.status}: ${text.slice(0, 120)}`)
      }

      const data = await res.json()

      if (data.errors?.length) {
        setSimError(data.errors.join(' · '))
      }

      if (data.waveforms?.length) {
        setWaveforms(data.waveforms)
      } else if (!data.errors?.length) {
        setSimError('Simulation completed but returned no waveform data')
      }
    } catch (err) {
      setSimError(err.message)
    } finally {
      setSimRunning(false)
    }
  }, [state.devices, state.wires])

  // ── Selected object for PropertiesPanel ───────────────────────────────

  const selectedForPanel = selectedId
    ? { id: selectedId, type: selectedType }
    : null

  // ─────────────────────────────────────────────────────────────────────────

  return (
    <div
      className="flex flex-col h-full bg-[#0d1929] text-white font-mono"
      data-testid="schematic-editor"
    >
      {/* Toolbar */}
      <Toolbar
        tool={tool}
        onToolChange={(t) => {
          setTool(t)
          if (t !== 'add') setAddingPartId(null)
        }}
        canUndo={state.past.length > 0}
        canRedo={state.future.length > 0}
        onUndo={() => dispatch({ type: 'UNDO' })}
        onRedo={() => dispatch({ type: 'REDO' })}
        onSimulate={handleSimulate}
        simRunning={simRunning}
        onClear={() => {
          dispatch({ type: 'CLEAR' })
          setSelectedId(null)
          setSelectedType(null)
          setWaveforms([])
          setSimError(null)
        }}
      />

      {/* Status bar */}
      <StatusBar
        tool={tool}
        devices={state.devices}
        wires={state.wires}
        simError={simError}
        addingPartId={addingPartId}
      />

      {/* Main 3-column layout */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: Part Library */}
        <PartLibrary
          activePart={addingPartId}
          onSelectPart={handleSelectPart}
          onDragStart={handleDragStart}
        />

        {/* Centre: Canvas */}
        <div className="flex-1 overflow-hidden" data-testid="canvas-container">
          <Canvas
            devices={state.devices}
            wires={state.wires}
            activeTool={tool}
            addingPartId={addingPartId}
            selectedId={selectedId}
            onSelectObject={handleSelectObject}
            onAddDevice={handleAddDevice}
            onWireCommit={handleWireCommit}
            onDeleteObject={handleDeleteObject}
            onAddProbe={handleAddProbe}
          />
        </div>

        {/* Right: Properties Panel */}
        <PropertiesPanel
          selected={selectedForPanel}
          devices={state.devices}
          onUpdateProps={handleUpdateProps}
          onUpdateLabel={handleUpdateLabel}
          onDelete={handleDeleteObject}
        />
      </div>

      {/* Bottom: Waveform results */}
      {waveforms.length > 0 && (
        <ProbeOverlay
          waveforms={waveforms}
          height={220}
          onClose={() => setWaveforms([])}
        />
      )}
    </div>
  )
}
