// RenderView — viewer/editor for `.render` scene description files.
// Props: { content, fileName, onContentChange }

import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, Camera, Layers, Palette, Play, Settings2, Sun, X } from 'lucide-react'
import { addLight, removeLight, setCameraFromOrbit, validateRender } from '../lib/render.js'

const DEBOUNCE_MS = 250

function numInput(val, onChange, opts = {}) {
  const { min, max, step = 1 } = opts
  return (
    <input type="number" value={val ?? ''} min={min} max={max} step={step}
      onChange={(e) => onChange(parseFloat(e.target.value))}
      className="w-full bg-ink-950 border border-ink-800 rounded px-2 py-1 text-xs text-ink-100 outline-none focus:border-kerf-300/60" />
  )
}

function Lbl({ children }) {
  return <div className="text-[10px] uppercase tracking-wider text-ink-500 font-medium mb-0.5">{children}</div>
}

function Heading({ icon: Icon, children }) {
  return (
    <div className="flex items-center gap-1.5 mb-3 text-[10px] uppercase tracking-wider text-ink-400 font-semibold">
      {Icon && <Icon size={11} className="text-kerf-300 shrink-0" />}
      {children}
    </div>
  )
}

function XYZRow({ label, value, onChange }) {
  const set = (i) => (v) => { const n = [...(value || [0, 0, 0])]; n[i] = isNaN(v) ? 0 : v; onChange(n) }
  return (
    <div>
      <Lbl>{label}</Lbl>
      <div className="grid grid-cols-3 gap-1">
        {['X', 'Y', 'Z'].map((axis, i) => (
          <div key={axis}>
            <span className="text-[9px] text-ink-600 block text-center">{axis}</span>
            {numInput((value || [0, 0, 0])[i], set(i), { step: 10 })}
          </div>
        ))}
      </div>
    </div>
  )
}

function OrbitPopover({ render, onApply, onClose }) {
  const [dist, setDist] = useState(5000)
  const [az, setAz] = useState(45)
  const [el, setEl] = useState(35)
  const apply = () => onApply(setCameraFromOrbit(render, render?.camera?.target || [0, 0, 500], dist, az, el))
  return (
    <div className="absolute top-8 right-0 z-30 w-60 bg-ink-900 border border-ink-800 rounded-lg shadow-2xl p-3 text-xs">
      <div className="flex items-center justify-between mb-2">
        <span className="text-ink-300 font-medium text-[11px]">Set from orbit</span>
        <button type="button" onClick={onClose} className="text-ink-500 hover:text-ink-200"><X size={12} /></button>
      </div>
      <div className="space-y-2">
        {[['Distance (mm)', dist, setDist, 100, 20000, 100], ['Azimuth (°)', az, setAz, 0, 360, 1], ['Elevation (°)', el, setEl, -89, 89, 1]].map(([lbl, v, setter, mn, mx, st]) => (
          <div key={lbl}>
            <Lbl>{lbl}</Lbl>
            <input type="range" min={mn} max={mx} step={st} value={v}
              onChange={(e) => setter(+e.target.value)} className="w-full accent-kerf-300" />
            <span className="text-ink-500 text-[10px]">{v}{lbl.includes('°') ? '°' : ' mm'}</span>
          </div>
        ))}
      </div>
      <button type="button" onClick={apply}
        className="mt-3 w-full px-2 py-1.5 rounded bg-kerf-300 text-ink-950 text-[11px] font-medium hover:bg-kerf-200">
        Apply
      </button>
    </div>
  )
}

const KINDS = ['sun', 'area', 'point', 'spot']

function LightRow({ light, onChange, onRemove }) {
  const useDir = light.kind === 'sun' || light.kind === 'spot'
  const set = (key) => (val) => onChange({ ...light, [key]: val })
  return (
    <div className="bg-ink-900 border border-ink-800 rounded p-2 space-y-2">
      <div className="flex items-center gap-2">
        <select value={light.kind} onChange={(e) => set('kind')(e.target.value)}
          className="bg-ink-950 border border-ink-800 rounded px-1.5 py-1 text-[11px] text-ink-100 outline-none">
          {KINDS.map((k) => <option key={k}>{k}</option>)}
        </select>
        <span className="text-[10px] text-ink-500 truncate flex-1 font-mono">{light.id || ''}</span>
        <input type="color" value={light.color || '#ffffff'} onChange={(e) => set('color')(e.target.value)}
          className="w-6 h-6 rounded cursor-pointer border-0 bg-transparent" title="Light color" />
        <button type="button" onClick={onRemove} className="text-ink-600 hover:text-red-400"><X size={12} /></button>
      </div>
      {useDir
        ? <XYZRow label="Direction" value={light.direction} onChange={set('direction')} />
        : <XYZRow label="Position" value={light.position} onChange={set('position')} />}
      <div>
        <Lbl>Intensity</Lbl>
        <input type="range" min={0} max={20} step={0.1} value={light.intensity ?? 1}
          onChange={(e) => set('intensity')(+e.target.value)} className="w-full accent-kerf-300" />
        <span className="text-ink-500 text-[10px]">{(light.intensity ?? 1).toFixed(1)}</span>
      </div>
    </div>
  )
}

export default function RenderView({ content, fileName, onContentChange }) {
  const [doc, setDoc] = useState(null)
  const [runMsg, setRunMsg] = useState(null)
  const [orbitOpen, setOrbitOpen] = useState(false)
  const debounceRef = useRef(null)

  useEffect(() => {
    const parsed = typeof content === 'object' && content !== null
      ? content
      : (() => { try { return JSON.parse(content || '{}') } catch { return null } })()
    setDoc(parsed)
  }, [content])

  const emit = useCallback((next) => {
    setDoc(next)
    if (!onContentChange) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => onContentChange(next), DEBOUNCE_MS)
  }, [onContentChange])

  const setCamera = (patch) => emit({ ...doc, camera: { ...(doc?.camera || {}), ...patch } })
  const setSettings = (patch) => emit({ ...doc, render_settings: { ...(doc?.render_settings || {}), ...patch } })
  const setMat = (patch) => emit({ ...doc, materials_override: { ...(doc?.materials_override || {}), '*': { ...(doc?.materials_override?.['*'] || {}), ...patch } } })

  if (!doc) {
    return (
      <div className="h-full flex items-center justify-center text-xs text-ink-500">
        <AlertTriangle size={13} className="mr-2 text-amber-400" /> Invalid render file.
      </div>
    )
  }

  const { ok, errors } = validateRender(doc)
  const cam = doc.camera || {}
  const rs = doc.render_settings || {}
  const mat = doc.materials_override?.['*'] || {}
  const lights = Array.isArray(doc.lights) ? doc.lights : []
  const res = rs.resolution || [1920, 1080]

  return (
    <div className="h-full flex flex-col bg-ink-950 text-ink-100 min-h-0">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-ink-800 bg-ink-900/40 flex-shrink-0">
        <Play size={13} className="text-kerf-300 shrink-0" />
        <span className="text-xs font-semibold uppercase tracking-wider text-ink-300 truncate min-w-0">
          {doc.name || fileName || 'Render'}
        </span>
        <span className="text-[11px] text-ink-500 truncate font-mono">{fileName || ''}</span>
        {!ok && (
          <span className="ml-1 text-[10px] text-amber-400 border border-amber-700/60 rounded px-1.5 py-0.5" title={errors.join('\n')}>
            {errors.length} error{errors.length !== 1 ? 's' : ''}
          </span>
        )}
        <div className="ml-auto relative">
          <button type="button" onClick={() => setRunMsg('Run not wired yet — POST /api/projects/{pid}/files/{fid}/render/run is not implemented.')}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-kerf-300 text-ink-950 text-[11px] font-medium hover:bg-kerf-200">
            <Play size={11} /> Run
          </button>
          {runMsg && (
            <div className="absolute top-9 right-0 z-30 w-72 bg-ink-900 border border-amber-700/60 rounded-lg p-3 text-[11px] text-amber-300 shadow-2xl">
              {runMsg}
              <button type="button" onClick={() => setRunMsg(null)} className="ml-2 text-ink-500 hover:text-ink-200"><X size={11} /></button>
            </div>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 min-h-0 overflow-auto">
        <div className="max-w-2xl mx-auto px-5 py-4 space-y-6">

          {/* Camera */}
          <section>
            <Heading icon={Camera}>Camera</Heading>
            <div className="space-y-3">
              <XYZRow label="Position (mm)" value={cam.position} onChange={(v) => setCamera({ position: v })} />
              <XYZRow label="Target (mm)" value={cam.target} onChange={(v) => setCamera({ target: v })} />
              <div className="grid grid-cols-2 gap-3">
                <div><Lbl>FOV (deg)</Lbl>{numInput(cam.fov_deg, (v) => setCamera({ fov_deg: v }), { min: 1, max: 179 })}</div>
                <div>
                  <Lbl>Type</Lbl>
                  <select value={cam.type || 'perspective'} onChange={(e) => setCamera({ type: e.target.value })}
                    className="w-full bg-ink-950 border border-ink-800 rounded px-2 py-1 text-xs text-ink-100 outline-none focus:border-kerf-300/60">
                    <option value="perspective">Perspective</option>
                    <option value="ortho">Orthographic</option>
                  </select>
                </div>
              </div>
              <div className="relative inline-block">
                <button type="button" onClick={() => setOrbitOpen((v) => !v)}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded border border-ink-800 bg-ink-900 text-ink-300 hover:text-kerf-300 hover:border-kerf-300/40 text-[11px]">
                  <Camera size={11} /> Set from orbit…
                </button>
                {orbitOpen && <OrbitPopover render={doc} onApply={(next) => { emit(next); setOrbitOpen(false) }} onClose={() => setOrbitOpen(false)} />}
              </div>
            </div>
          </section>

          {/* Lights */}
          <section>
            <div className="flex items-center justify-between mb-3">
              <Heading icon={Sun}>Lights</Heading>
              <button type="button"
                onClick={() => emit(addLight(doc, { id: `light_${Date.now().toString(36)}`, kind: 'sun', direction: [-1, -1, -2], intensity: 3, color: '#ffffff' }))}
                className="text-[10px] px-2 py-0.5 rounded border border-ink-800 bg-ink-900 text-ink-400 hover:text-kerf-300 hover:border-kerf-300/40">
                + Add
              </button>
            </div>
            {lights.length === 0
              ? <p className="text-[11px] text-ink-600 italic">No lights — add one above.</p>
              : <div className="space-y-2">{lights.map((light) => (
                  <LightRow key={light.id} light={light}
                    onChange={(next) => emit({ ...doc, lights: lights.map((l) => l.id === next.id ? next : l) })}
                    onRemove={() => emit(removeLight(doc, light.id))} />
                ))}</div>}
          </section>

          {/* Materials override */}
          <section>
            <Heading icon={Palette}>Materials override (*)</Heading>
            <div className="bg-ink-900 border border-ink-800 rounded p-3 space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Lbl>Kind</Lbl>
                  <select value={mat.kind || 'principled'} onChange={(e) => setMat({ kind: e.target.value })}
                    className="w-full bg-ink-950 border border-ink-800 rounded px-2 py-1 text-xs text-ink-100 outline-none focus:border-kerf-300/60">
                    {['principled', 'emission', 'glass'].map((k) => <option key={k}>{k}</option>)}
                  </select>
                </div>
                <div>
                  <Lbl>Base color</Lbl>
                  <input type="color" value={mat.base_color || '#888888'} onChange={(e) => setMat({ base_color: e.target.value })}
                    className="w-full h-8 rounded cursor-pointer border border-ink-800 bg-ink-950" />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                {[['Roughness', 'roughness', 0.5], ['Metallic', 'metallic', 0]].map(([lbl, key, def]) => (
                  <div key={key}>
                    <Lbl>{lbl}</Lbl>
                    <input type="range" min={0} max={1} step={0.01} value={mat[key] ?? def}
                      onChange={(e) => setMat({ [key]: +e.target.value })} className="w-full accent-kerf-300" />
                    <span className="text-[10px] text-ink-500">{(mat[key] ?? def).toFixed(2)}</span>
                  </div>
                ))}
              </div>
            </div>
          </section>

          {/* Render settings */}
          <section>
            <Heading icon={Settings2}>Render settings</Heading>
            <div className="bg-ink-900 border border-ink-800 rounded p-3 space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div><Lbl>Width (px)</Lbl>{numInput(res[0], (v) => setSettings({ resolution: [v, res[1]] }), { min: 1, step: 1 })}</div>
                <div><Lbl>Height (px)</Lbl>{numInput(res[1], (v) => setSettings({ resolution: [res[0], v] }), { min: 1, step: 1 })}</div>
              </div>
              <div>
                <Lbl>Samples</Lbl>
                <input type="range" min={1} max={4096} step={1} value={rs.samples ?? 128}
                  onChange={(e) => setSettings({ samples: +e.target.value })} className="w-full accent-kerf-300" />
                <span className="text-[10px] text-ink-500">{rs.samples ?? 128}</span>
              </div>
              <div className="flex items-center gap-2">
                <input type="checkbox" id="rv-denoise" checked={rs.denoise ?? true}
                  onChange={(e) => setSettings({ denoise: e.target.checked })} className="accent-kerf-300" />
                <label htmlFor="rv-denoise" className="text-xs text-ink-300 cursor-pointer">Denoise</label>
              </div>
              <div>
                <Lbl>Output format</Lbl>
                <select value={rs.output_format || 'png'} onChange={(e) => setSettings({ output_format: e.target.value })}
                  className="w-full bg-ink-950 border border-ink-800 rounded px-2 py-1 text-xs text-ink-100 outline-none focus:border-kerf-300/60">
                  <option value="png">PNG</option>
                  <option value="exr">EXR (HDR)</option>
                </select>
              </div>
            </div>
          </section>

          {/* Output preview */}
          <section>
            <Heading icon={Layers}>Output</Heading>
            {doc.last_output_url
              ? <img src={doc.last_output_url} alt="Last render output" className="w-full rounded border border-ink-800 object-contain max-h-80" />
              : <div className="flex items-center justify-center h-36 rounded border border-ink-800 bg-ink-900 text-xs text-ink-600 italic">No output yet — press Run to render.</div>}
          </section>

        </div>
      </div>
    </div>
  )
}
