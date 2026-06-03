/**
 * PathTracer.jsx — WebGPU Spectral Path Tracer demo page.
 *
 * Route: /pathtracer
 *
 * Shows a side panel with scene presets + sample counter, and a canvas
 * that runs the WebGPU path-tracer in PathTracerCanvas.
 */

import { useCallback, useMemo, useState } from 'react'
import { Download, Layers, RefreshCcw, Sparkles } from 'lucide-react'
import PathTracerCanvas from '../components/render/PathTracerCanvas.jsx'
import {
  createGlassSpheresScene,
  createCornellBoxScene,
  createPrismScene,
} from '../components/render/PathTracerScene.js'

// ─── Scene presets ───────────────────────────────────────────────────────────

const PRESETS = [
  {
    id:    'glass-spheres',
    label: 'Glass Spheres',
    desc:  'BK7 (n=1.51) · SF11 (n=1.78) · Water (n=1.33) on a checkerboard plane.',
    build: createGlassSpheresScene,
  },
  {
    id:    'cornell-box',
    label: 'Cornell Box',
    desc:  'Classic Cornell box with a glass sphere inside.',
    build: createCornellBoxScene,
  },
  {
    id:    'prism',
    label: 'Prism',
    desc:  'High-IOR (n=1.9) glass sphere approximating a prism between two diffuse spheres.',
    build: createPrismScene,
  },
]

// Canvas dimensions
const W = 800
const H = 560

// ─── Component ───────────────────────────────────────────────────────────────

export default function PathTracerPage() {
  const [presetId, setPresetId]       = useState('glass-spheres')
  const [sampleCount, setSampleCount] = useState(0)
  const [resetKey, setResetKey]       = useState(0)

  const scene = useMemo(() => {
    const preset = PRESETS.find((p) => p.id === presetId) ?? PRESETS[0]
    return preset.build()
  }, [presetId])

  // Changing resetKey forces PathTracerCanvas to remount and restart accumulation
  const handlePresetChange = useCallback((id) => {
    setPresetId(id)
    setSampleCount(0)
    setResetKey((k) => k + 1)
  }, [])

  const handleReset = useCallback(() => {
    setSampleCount(0)
    setResetKey((k) => k + 1)
  }, [])

  const handleDownload = useCallback(() => {
    const canvas = document.querySelector('canvas[data-pt-canvas]')
    if (!canvas) return
    const link = document.createElement('a')
    link.href     = canvas.toDataURL('image/png')
    link.download = `kerf-pathtracer-${presetId}-${sampleCount}spp.png`
    link.click()
  }, [presetId, sampleCount])

  const activePreset = PRESETS.find((p) => p.id === presetId) ?? PRESETS[0]

  return (
    <div className="min-h-screen bg-ink-950 text-ink-100 flex flex-col">
      {/* ── Header ── */}
      <header className="flex items-center gap-3 px-6 py-3 border-b border-ink-800 bg-ink-900/60 flex-shrink-0">
        <Sparkles size={16} className="text-kerf-300 shrink-0" />
        <h1 className="text-sm font-semibold tracking-wide text-ink-100">
          WebGPU Spectral Path Tracer{' '}
          <span className="ml-1.5 text-[10px] uppercase tracking-wider text-amber-400 border border-amber-700/60 rounded px-1.5 py-0.5">
            experimental
          </span>
        </h1>
        <div className="ml-auto flex items-center gap-3">
          <span className="text-[11px] text-ink-500 font-mono tabular-nums">
            Samples: <span className="text-kerf-300">{sampleCount}</span>
          </span>
          <button
            type="button"
            onClick={handleReset}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded border border-ink-800 bg-ink-900 text-ink-400 hover:text-kerf-300 hover:border-kerf-300/40 text-[11px] transition-colors"
          >
            <RefreshCcw size={11} />
            Reset
          </button>
          <button
            type="button"
            onClick={handleDownload}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded border border-ink-800 bg-ink-900 text-ink-400 hover:text-kerf-300 hover:border-kerf-300/40 text-[11px] transition-colors"
          >
            <Download size={11} />
            Download
          </button>
        </div>
      </header>

      {/* ── Body ── */}
      <div className="flex flex-1 min-h-0">
        {/* Side panel */}
        <aside className="w-56 flex-shrink-0 border-r border-ink-800 bg-ink-900/40 p-4 flex flex-col gap-4 overflow-y-auto">
          {/* Scene presets */}
          <section>
            <div className="flex items-center gap-1.5 mb-2 text-[10px] uppercase tracking-wider text-ink-400 font-semibold">
              <Layers size={10} className="text-kerf-300" />
              Scene
            </div>
            <div className="space-y-1">
              {PRESETS.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => handlePresetChange(p.id)}
                  className={[
                    'w-full text-left px-2.5 py-2 rounded text-[11px] transition-colors',
                    p.id === presetId
                      ? 'bg-kerf-300/10 border border-kerf-300/30 text-kerf-200'
                      : 'border border-transparent text-ink-400 hover:text-ink-200 hover:bg-ink-800',
                  ].join(' ')}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </section>

          {/* Scene description */}
          <section>
            <p className="text-[11px] text-ink-500 leading-relaxed">
              {activePreset.desc}
            </p>
          </section>

          {/* Controls reference */}
          <section className="mt-auto">
            <div className="text-[10px] uppercase tracking-wider text-ink-600 mb-1.5">Controls</div>
            <ul className="space-y-1 text-[11px] text-ink-600">
              <li><span className="text-ink-400 font-medium">Drag</span> — orbit</li>
              <li><span className="text-ink-400 font-medium">Scroll</span> — zoom</li>
              <li><span className="text-ink-400 font-medium">WASD</span> — pan</li>
              <li><span className="text-ink-400 font-medium">Space / Shift</span> — up / down</li>
            </ul>
          </section>

          {/* Sample counter */}
          <div className="border-t border-ink-800 pt-3">
            <div className="text-[10px] uppercase tracking-wider text-ink-600 mb-1">Progressive</div>
            <div className="text-2xl font-mono tabular-nums text-kerf-300">
              {sampleCount}
            </div>
            <div className="text-[10px] text-ink-600">samples per pixel</div>
          </div>
        </aside>

        {/* Canvas area */}
        <main className="flex-1 flex items-center justify-center bg-ink-950 overflow-auto p-6">
          <PathTracerCanvas
            key={`${presetId}-${resetKey}`}
            scene={scene}
            width={W}
            height={H}
            onSampleCount={setSampleCount}
          />
        </main>
      </div>
    </div>
  )
}
