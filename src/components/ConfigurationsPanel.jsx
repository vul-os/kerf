// ConfigurationsPanel — author per-file parameter overrides ("M3 / M4 / M5"
// flavors of one Part). Mounted as a slide-out panel inside the editor for
// any file kind that supports configurations (Part / Feature / Sketch).
//
// State model:
//   - The host owns `configurations` (array of {id, label, params}) and
//     `default_config` (string id) and passes them in.
//   - The host also owns serialization back to the underlying file: changes
//     bubble out via `onChange({ configurations, default_config })`. We
//     never mutate the host's data in place — every edit produces a fresh
//     array so React diffs cleanly.
//
// Each row shows id (read-only after creation), label (editable),
// "default" radio, params as expandable JSON textarea, and a remove button.
// "+ Add configuration" at the bottom appends a new row with a fresh id
// (the user can rename the label but the canonical id stays stable so
// references — `default_config` and assembly `config_id` — survive
// label edits). A small "Apply to runner" hint reminds the user that the
// runner re-runs on save (config switch in the dropdown is the live path).

import { useMemo, useState } from 'react'
import { Plus, X, Star, AlertTriangle } from 'lucide-react'

const NEW_ID_PREFIX = 'cfg'

function nextConfigId(existing) {
  // Fresh, short, sortable id. Assembly references store this id so it
  // must NOT collide with an existing one.
  for (let i = 1; i < 1024; i++) {
    const candidate = `${NEW_ID_PREFIX}${i}`
    if (!existing.find((c) => c.id === candidate)) return candidate
  }
  // Pathological — fall back to a random suffix.
  return `${NEW_ID_PREFIX}-${Math.random().toString(36).slice(2, 6)}`
}

export default function ConfigurationsPanel({
  configurations = [],
  defaultConfig = '',
  onChange,
  onClose,
}) {
  const list = useMemo(() => Array.isArray(configurations) ? configurations : [], [configurations])

  const updateAll = (next) => {
    const cfgs = Array.isArray(next.configurations) ? next.configurations : list
    const def = typeof next.default_config === 'string' ? next.default_config : defaultConfig
    // Auto-correct dangling default: if the picked id no longer exists,
    // collapse to the first row's id (if any) or empty.
    const valid = cfgs.find((c) => c.id === def)
    const safeDefault = valid ? def : (cfgs[0]?.id || '')
    onChange?.({ configurations: cfgs, default_config: safeDefault })
  }

  const addConfig = () => {
    const id = nextConfigId(list)
    const next = [...list, { id, label: id, params: {} }]
    updateAll({ configurations: next, default_config: defaultConfig || id })
  }

  const removeConfig = (id) => {
    const next = list.filter((c) => c.id !== id)
    updateAll({ configurations: next, default_config: defaultConfig === id ? '' : defaultConfig })
  }

  const updateConfig = (id, patch) => {
    const next = list.map((c) => (c.id === id ? { ...c, ...patch } : c))
    updateAll({ configurations: next, default_config: defaultConfig })
  }

  const setDefault = (id) => {
    updateAll({ configurations: list, default_config: id })
  }

  return (
    <div className="absolute right-3 top-3 bottom-3 w-[380px] z-30 rounded-lg bg-ink-950 border border-ink-800 shadow-2xl flex flex-col overflow-hidden">
      <header className="flex items-center justify-between px-4 py-3 border-b border-ink-800 bg-ink-900/60">
        <div className="flex flex-col">
          <span className="text-[13px] font-semibold text-ink-100">Configurations</span>
          <span className="text-[10px] text-ink-500">Per-file parameter overrides</span>
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded hover:bg-ink-800 text-ink-400 hover:text-ink-100"
            title="Close"
          >
            <X size={14} />
          </button>
        )}
      </header>

      <div className="flex-1 min-h-0 overflow-y-auto px-3 py-2">
        {list.length === 0 ? (
          <div className="px-2 py-6 text-center text-[11px] text-ink-500">
            No configurations yet.
            <br />
            Click "Add configuration" to create one.
          </div>
        ) : (
          <ul className="flex flex-col gap-2">
            {list.map((cfg) => (
              <ConfigRow
                key={cfg.id}
                cfg={cfg}
                isDefault={defaultConfig === cfg.id}
                onSetDefault={() => setDefault(cfg.id)}
                onRemove={() => removeConfig(cfg.id)}
                onUpdate={(patch) => updateConfig(cfg.id, patch)}
              />
            ))}
          </ul>
        )}
      </div>

      <footer className="border-t border-ink-800 px-3 py-2 bg-ink-900/40">
        <button
          type="button"
          onClick={addConfig}
          className="w-full inline-flex items-center justify-center gap-1.5 px-2 py-1.5 rounded bg-kerf-300/10 border border-kerf-300/30 text-kerf-200 hover:bg-kerf-300/20 text-[11px]"
        >
          <Plus size={11} />
          Add configuration
        </button>
      </footer>
    </div>
  )
}

function ConfigRow({ cfg, isDefault, onSetDefault, onRemove, onUpdate }) {
  const [paramsDraft, setParamsDraft] = useState(() => paramsToText(cfg.params))
  const [paramsErr, setParamsErr] = useState(null)

  const commitParams = () => {
    if (paramsDraft.trim() === '') {
      setParamsErr(null)
      onUpdate({ params: {} })
      return
    }
    try {
      const parsed = JSON.parse(paramsDraft)
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        setParamsErr('Must be a JSON object.')
        return
      }
      setParamsErr(null)
      onUpdate({ params: parsed })
    } catch (err) {
      setParamsErr(err?.message || 'Invalid JSON')
    }
  }

  return (
    <li className="rounded border border-ink-800 bg-ink-900/40 p-2 flex flex-col gap-1.5">
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={onSetDefault}
          title={isDefault ? 'Default configuration' : 'Make default'}
          className={`p-1 rounded ${isDefault
            ? 'text-amber-300 bg-amber-300/10'
            : 'text-ink-500 hover:text-amber-300'}`}
        >
          <Star size={11} className={isDefault ? 'fill-current' : ''} />
        </button>
        <input
          type="text"
          value={cfg.label}
          onChange={(e) => onUpdate({ label: e.target.value })}
          placeholder={cfg.id}
          className="flex-1 bg-ink-950 border border-ink-800 rounded px-2 py-1 text-[12px] text-ink-100 outline-none focus:border-kerf-300/60"
        />
        <span className="font-mono text-[10px] text-ink-500" title="Stable id used by assembly references">
          {cfg.id}
        </span>
        <button
          type="button"
          onClick={onRemove}
          title="Remove configuration"
          className="p-1 rounded text-ink-500 hover:text-red-300 hover:bg-red-300/10"
        >
          <X size={11} />
        </button>
      </div>
      <div className="flex flex-col gap-1">
        <textarea
          value={paramsDraft}
          onChange={(e) => setParamsDraft(e.target.value)}
          onBlur={commitParams}
          spellCheck={false}
          rows={3}
          placeholder='{ "d": 4, "head_d": 7 }'
          className="w-full bg-ink-950 border border-ink-800 rounded px-2 py-1 text-[11px] font-mono text-ink-100 outline-none focus:border-kerf-300/60 resize-y"
        />
        {paramsErr && (
          <span className="inline-flex items-center gap-1 text-[10px] text-red-300">
            <AlertTriangle size={10} />
            {paramsErr}
          </span>
        )}
      </div>
    </li>
  )
}

function paramsToText(p) {
  if (!p || typeof p !== 'object') return ''
  try {
    return JSON.stringify(p, null, 2)
  } catch {
    return ''
  }
}
