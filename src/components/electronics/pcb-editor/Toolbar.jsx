// Toolbar.jsx — PCB editor toolbar: tool-mode toggles, layer selector,
// DRC indicator, and undo/redo controls.
//
// Props:
//   tool          — 'select' | 'route' | 'push-shove' | 'delete'
//   onToolChange  — (tool) => void
//   layer         — 'top' | 'bottom' | 'inner1' | 'inner2'
//   onLayerChange — (layer) => void
//   drcOk         — boolean | null (null = unknown/loading)
//   canUndo       — boolean
//   canRedo       — boolean
//   onUndo        — () => void
//   onRedo        — () => void

import { MousePointer2, Route, Zap, Trash2, Layers, CheckCircle2, XCircle, Undo2, Redo2, Loader, Ruler, Activity, Cpu, ShieldAlert, Box, Layers3, Thermometer } from 'lucide-react'

const TOOLS = [
  { id: 'select',     label: 'Select',      Icon: MousePointer2 },
  { id: 'route',      label: 'Route',       Icon: Route },
  { id: 'push-shove', label: 'Push-Shove',  Icon: Zap },
  { id: 'delete',     label: 'Delete',      Icon: Trash2 },
  { id: 'tune-length', label: 'Tune Length', Icon: Ruler },
]

const LAYERS = [
  { id: 'top',    label: 'Top',    color: '#ef4444' },
  { id: 'bottom', label: 'Bottom', color: '#3b82f6' },
  { id: 'inner1', label: 'Inner1', color: '#f59e0b' },
  { id: 'inner2', label: 'Inner2', color: '#8b5cf6' },
]

export default function Toolbar({
  tool,
  onToolChange,
  layer,
  onLayerChange,
  drcOk,
  canUndo,
  canRedo,
  onUndo,
  onRedo,
  onToggleDrcPanel,
  onToggleSIPanel,
  onToggleSiliconPanel,
  onToggleMultiBoardPanel,
  onTogglePCB3DPanel,
  onToggleEMCPanel,
  onTogglePCBThermalPanel,
}) {
  return (
    <div className="flex items-center gap-2 px-3 py-2 bg-[#1a1a2e] border-b border-white/10 text-sm select-none flex-wrap">
      {/* Tool toggles */}
      <div className="flex items-center gap-1 bg-black/30 rounded-lg p-1">
        {TOOLS.map(({ id, label, Icon }) => (
          <button
            key={id}
            data-testid={`tool-${id}`}
            onClick={() => onToolChange(id)}
            title={label}
            className={[
              'flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors',
              tool === id
                ? 'bg-indigo-600 text-white shadow'
                : 'text-gray-400 hover:text-white hover:bg-white/10',
            ].join(' ')}
          >
            <Icon size={13} />
            <span className="hidden sm:inline">{label}</span>
          </button>
        ))}
      </div>

      <div className="w-px h-5 bg-white/10" />

      {/* Layer selector */}
      <div className="flex items-center gap-1">
        <Layers size={13} className="text-gray-500" />
        <div className="flex items-center gap-0.5 bg-black/30 rounded-lg p-1">
          {LAYERS.map(({ id, label, color }) => (
            <button
              key={id}
              data-testid={`layer-${id}`}
              onClick={() => onLayerChange(id)}
              title={label}
              className={[
                'px-2 py-1 rounded-md text-xs font-medium transition-colors',
                layer === id
                  ? 'text-white shadow'
                  : 'text-gray-400 hover:text-white hover:bg-white/10',
              ].join(' ')}
              style={layer === id ? { backgroundColor: color + '33', color } : {}}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1" />

      {/* DRC indicator */}
      <div
        data-testid="drc-indicator"
        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs"
        title={drcOk == null ? 'DRC pending…' : drcOk ? 'DRC passed' : 'DRC violations found'}
      >
        {drcOk == null ? (
          <>
            <Loader size={13} className="animate-spin text-gray-400" />
            <span className="text-gray-400">DRC…</span>
          </>
        ) : drcOk ? (
          <>
            <CheckCircle2 size={13} className="text-emerald-400" />
            <span className="text-emerald-400">DRC OK</span>
          </>
        ) : (
          <>
            <XCircle size={13} className="text-red-400" />
            <span className="text-red-400">DRC Fail</span>
          </>
        )}
      </div>

      <div className="w-px h-5 bg-white/10" />

      {/* Panel toggles — DRC/ERC, SI, Silicon */}
      <div className="flex items-center gap-1 bg-black/30 rounded-lg p-1">
        {onToggleDrcPanel && (
          <button
            data-testid="btn-toggle-drc-panel"
            onClick={onToggleDrcPanel}
            title="DRC / ERC results panel"
            className="flex items-center gap-1 px-2 py-1.5 rounded-md text-xs text-gray-400 hover:text-white hover:bg-white/10 transition-colors"
          >
            <ShieldAlert size={13} />
            <span className="hidden sm:inline">DRC/ERC</span>
          </button>
        )}
        {onToggleSIPanel && (
          <button
            data-testid="btn-toggle-si-panel"
            onClick={onToggleSIPanel}
            title="Signal Integrity panel (Z0 / crosstalk / IBIS eye)"
            className="flex items-center gap-1 px-2 py-1.5 rounded-md text-xs text-gray-400 hover:text-white hover:bg-white/10 transition-colors"
          >
            <Activity size={13} />
            <span className="hidden sm:inline">SI</span>
          </button>
        )}
        {onToggleSiliconPanel && (
          <button
            data-testid="btn-toggle-silicon-panel"
            onClick={onToggleSiliconPanel}
            title="Silicon synthesis / P&R (Yosys + OpenLane)"
            className="flex items-center gap-1 px-2 py-1.5 rounded-md text-xs text-gray-400 hover:text-white hover:bg-white/10 transition-colors"
          >
            <Cpu size={13} />
            <span className="hidden sm:inline">Synth</span>
          </button>
        )}
        {onToggleMultiBoardPanel && (
          <button
            data-testid="btn-toggle-multiboard-panel"
            onClick={onToggleMultiBoardPanel}
            title="Multi-board workspace (Altium MB3D)"
            className="flex items-center gap-1 px-2 py-1.5 rounded-md text-xs text-gray-400 hover:text-white hover:bg-white/10 transition-colors"
          >
            <Box size={13} />
            <span className="hidden sm:inline">MB3D</span>
          </button>
        )}
        {onTogglePCB3DPanel && (
          <button
            data-testid="btn-toggle-pcb3d-panel"
            onClick={onTogglePCB3DPanel}
            title="3D PCB editor — STEP import + clearance DRC"
            className="flex items-center gap-1 px-2 py-1.5 rounded-md text-xs text-gray-400 hover:text-white hover:bg-white/10 transition-colors"
          >
            <Layers3 size={13} />
            <span className="hidden sm:inline">3D</span>
          </button>
        )}
        {onToggleEMCPanel && (
          <button
            data-testid="btn-toggle-emc-panel"
            onClick={onToggleEMCPanel}
            title="EMC pre-compliance (radiated / shielding / FCC + CISPR limits)"
            className="flex items-center gap-1 px-2 py-1.5 rounded-md text-xs text-gray-400 hover:text-white hover:bg-white/10 transition-colors"
          >
            <Zap size={13} />
            <span className="hidden sm:inline">EMC</span>
          </button>
        )}
        {onTogglePCBThermalPanel && (
          <button
            data-testid="btn-toggle-thermal-panel"
            onClick={onTogglePCBThermalPanel}
            title="PCB thermal analysis — 2D FD hotspot map + via recommendations"
            className="flex items-center gap-1 px-2 py-1.5 rounded-md text-xs text-gray-400 hover:text-white hover:bg-white/10 transition-colors"
          >
            <Thermometer size={13} />
            <span className="hidden sm:inline">Thermal</span>
          </button>
        )}
      </div>

      <div className="w-px h-5 bg-white/10" />

      {/* Undo / Redo */}
      <div className="flex items-center gap-1 bg-black/30 rounded-lg p-1">
        <button
          data-testid="btn-undo"
          onClick={onUndo}
          disabled={!canUndo}
          title="Undo (Ctrl-Z)"
          className="p-1.5 rounded-md text-gray-400 hover:text-white hover:bg-white/10 disabled:opacity-30 disabled:pointer-events-none transition-colors"
        >
          <Undo2 size={13} />
        </button>
        <button
          data-testid="btn-redo"
          onClick={onRedo}
          disabled={!canRedo}
          title="Redo (Ctrl-Shift-Z)"
          className="p-1.5 rounded-md text-gray-400 hover:text-white hover:bg-white/10 disabled:opacity-30 disabled:pointer-events-none transition-colors"
        >
          <Redo2 size={13} />
        </button>
      </div>
    </div>
  )
}
