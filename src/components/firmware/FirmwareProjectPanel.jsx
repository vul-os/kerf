/**
 * FirmwareProjectPanel.jsx — context panel for firmware projects.
 *
 * Shown in the Editor centre pane when the active file has kind 'firmware_project'
 * (a .fw.json / kerf.fw.json manifest). Displays:
 *   - Board target + toolchain + entrypoint from the manifest
 *   - Build / Flash / Monitor action buttons
 *   - Inline BuildOutput panel (streaming compiler log)
 *   - SerialMonitor panel (toggled by the Monitor button)
 *
 * Tool dispatch uses POST /api/firmware/build and /api/firmware/monitor
 * via firmwareBridge.js — the same endpoints wired by FirmwareActions.jsx.
 * Flash also uses firmwareBridge.uploadFirmware (POST /api/firmware/upload).
 *
 * Cloud sentinel: Upload + Monitor show a "requires local Kerf CLI" notice
 * when running in the hosted environment (VITE_LOCAL_CLI env var absent /
 * falsy). Build is server-runnable.
 *
 * Props:
 *   file      {object}  — the .fw.json file object from the workspace store
 *   content   {string}  — the raw JSON string content of the file
 *   projectId {string}  — active project ID
 *   onFileAdded {function} — called when a build artefact path is ready so the
 *                           parent can refresh the file tree; signature:
 *                           (artifactPath: string) => void
 */

import { useState } from 'react'
import {
  Cpu, Hammer, Upload, Activity, Loader2, CheckCircle2, AlertCircle,
  ChevronDown, ChevronRight, Info,
} from 'lucide-react'
import { buildFirmware, uploadFirmware } from '../../lib/firmwareBridge.js'
import BuildOutput from './BuildOutput.jsx'
import SerialMonitor from './SerialMonitor.jsx'

// ── helpers ───────────────────────────────────────────────────────────────────

const IS_LOCAL_CLI = typeof import.meta !== 'undefined' && import.meta.env
  ? import.meta.env.VITE_LOCAL_CLI === '1'
  : false

function parseFwConfig(content) {
  try { return JSON.parse(content || '{}') } catch { return null }
}

// ── sub-components ────────────────────────────────────────────────────────────

function FieldRow({ label, value }) {
  if (!value) return null
  return (
    <div className="flex items-start gap-2 text-[11px]">
      <span className="text-ink-500 w-20 flex-shrink-0">{label}</span>
      <span className="text-ink-200 font-mono truncate">{value}</span>
    </div>
  )
}

function CloudSentinel({ action }) {
  return (
    <div className="flex items-start gap-2 rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
      <Info size={12} className="flex-shrink-0 mt-0.5" />
      <span>
        <strong>{action}</strong> requires the local Kerf CLI (hardware access is not
        available in the hosted environment). Run <code className="font-mono bg-ink-800 px-0.5 rounded">kerf dev</code> locally.
      </span>
    </div>
  )
}

// ── main component ────────────────────────────────────────────────────────────

export default function FirmwareProjectPanel({
  file,
  content,
  projectId,
  onFileAdded = null,
}) {
  const fwConfig = parseFwConfig(content)

  // Per-action state: idle | loading | success | error
  const [buildStatus, setBuildStatus] = useState('idle')
  const [uploadStatus, setUploadStatus] = useState('idle')
  const [buildError, setBuildError] = useState(null)
  const [uploadError, setUploadError] = useState(null)

  // Build output lines and last artefact paths.
  const [buildLines, setBuildLines] = useState([])
  const [lastHexPath, setLastHexPath] = useState(null)

  // Panel visibility toggles.
  const [showBuildOutput, setShowBuildOutput] = useState(false)
  const [showMonitor, setShowMonitor] = useState(false)

  // ── handlers ──────────────────────────────────────────────────────────────

  async function handleBuild() {
    setBuildStatus('loading')
    setBuildError(null)
    setBuildLines([])
    setShowBuildOutput(true)

    const sourcePath = fwConfig?.sketch_dir || file?.name || ''
    const result = await buildFirmware(sourcePath, fwConfig)

    if (result.ok) {
      setBuildStatus('success')
      setLastHexPath(result.hex_path || result.bin_path || null)
      // Surface artefact in file tree.
      const artefact = result.bin_path || result.hex_path || result.elf_path
      if (artefact) onFileAdded?.(artefact)
    } else {
      setBuildStatus('error')
      setBuildError(result.errors?.[0] || result.error || 'Build failed')
    }

    // Show the build log regardless of success/failure.
    const log = result.build_log || result.build_log_preview || ''
    if (log) setBuildLines(log.split('\n'))
  }

  async function handleFlash() {
    if (!IS_LOCAL_CLI) return  // guarded by the sentinel UI
    setUploadStatus('loading')
    setUploadError(null)
    const result = await uploadFirmware(lastHexPath || '', fwConfig)
    if (result.ok) {
      setUploadStatus('success')
    } else {
      setUploadStatus('error')
      setUploadError(result.errors?.[0] || 'Flash failed')
    }
  }

  function handleMonitor() {
    if (!IS_LOCAL_CLI) return  // guarded by sentinel UI
    setShowMonitor((v) => !v)
  }

  // ── render ────────────────────────────────────────────────────────────────

  const board      = fwConfig?.board || '—'
  const framework  = fwConfig?.framework || '—'
  const entrypoint = fwConfig?.sketch_dir || fwConfig?.sources?.[0] || '—'
  const anyLoading = buildStatus === 'loading' || uploadStatus === 'loading'

  return (
    <div
      className="flex flex-col gap-4 p-4 h-full min-h-0 overflow-y-auto"
      data-testid="firmware-project-panel"
    >
      {/* ── Manifest info ─────────────────────────────────────────────────── */}
      <section className="rounded-lg border border-ink-700/60 bg-ink-900/60 p-4">
        <div className="flex items-center gap-2 mb-3">
          <Cpu size={14} className="text-green-300 flex-shrink-0" />
          <span className="text-sm font-medium text-ink-100">
            {file?.name || 'firmware project'}
          </span>
        </div>
        <div className="space-y-1.5">
          <FieldRow label="Board"      value={board} />
          <FieldRow label="Framework"  value={framework} />
          <FieldRow label="Entrypoint" value={entrypoint} />
        </div>
      </section>

      {/* ── Action buttons ────────────────────────────────────────────────── */}
      <section className="flex items-center gap-2 flex-wrap">
        {/* Build */}
        <button
          type="button"
          onClick={handleBuild}
          disabled={anyLoading}
          data-testid="btn-build"
          className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium border border-ink-600 bg-ink-800 text-ink-100 hover:bg-ink-700 hover:border-kerf-400 hover:text-kerf-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {buildStatus === 'loading'
            ? <Loader2 size={12} className="animate-spin flex-shrink-0" />
            : <Hammer size={12} className="flex-shrink-0" />}
          Build
          {buildStatus === 'success' && <CheckCircle2 size={12} className="text-emerald-400 flex-shrink-0" />}
          {buildStatus === 'error'   && <AlertCircle   size={12} className="text-red-400 flex-shrink-0" />}
        </button>

        {/* Flash */}
        <button
          type="button"
          onClick={IS_LOCAL_CLI ? handleFlash : undefined}
          disabled={anyLoading || !IS_LOCAL_CLI}
          data-testid="btn-flash"
          title={IS_LOCAL_CLI ? 'Flash firmware to connected board' : 'Requires local Kerf CLI'}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium border border-ink-600 bg-ink-800 text-ink-100 hover:bg-ink-700 hover:border-kerf-400 hover:text-kerf-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {uploadStatus === 'loading'
            ? <Loader2 size={12} className="animate-spin flex-shrink-0" />
            : <Upload size={12} className="flex-shrink-0" />}
          Flash
          {uploadStatus === 'success' && <CheckCircle2 size={12} className="text-emerald-400 flex-shrink-0" />}
          {uploadStatus === 'error'   && <AlertCircle   size={12} className="text-red-400 flex-shrink-0" />}
        </button>

        {/* Monitor */}
        <button
          type="button"
          onClick={IS_LOCAL_CLI ? handleMonitor : undefined}
          disabled={!IS_LOCAL_CLI}
          data-testid="btn-monitor"
          title={IS_LOCAL_CLI ? 'Open serial monitor' : 'Requires local Kerf CLI'}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium border transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
            showMonitor && IS_LOCAL_CLI
              ? 'border-green-600/70 bg-green-900/30 text-green-300'
              : 'border-ink-600 bg-ink-800 text-ink-100 hover:bg-ink-700 hover:border-green-600 hover:text-green-300'
          }`}
        >
          <Activity size={12} className="flex-shrink-0" />
          Monitor
        </button>

        {/* Build output toggle */}
        <button
          type="button"
          onClick={() => setShowBuildOutput((v) => !v)}
          className="flex items-center gap-1 text-[10px] text-ink-500 hover:text-ink-300 transition-colors ml-auto"
        >
          {showBuildOutput ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
          Build log
        </button>
      </section>

      {/* Cloud sentinel for Flash */}
      {!IS_LOCAL_CLI && uploadError !== null && (
        <CloudSentinel action="Flash" />
      )}

      {/* Cloud sentinel for Monitor */}
      {!IS_LOCAL_CLI && showMonitor && (
        <CloudSentinel action="Monitor" />
      )}

      {/* Flash error */}
      {IS_LOCAL_CLI && uploadError && (
        <div className="text-xs text-red-300 rounded border border-red-700/40 bg-red-950/40 px-3 py-2">
          {uploadError}
        </div>
      )}

      {/* ── Build output ──────────────────────────────────────────────────── */}
      {showBuildOutput && (
        <div className="flex-1 min-h-0" style={{ minHeight: '12rem' }}>
          <BuildOutput
            lines={buildLines}
            running={buildStatus === 'loading'}
            error={buildError}
            onClear={() => { setBuildLines([]); setBuildError(null); setBuildStatus('idle') }}
          />
        </div>
      )}

      {/* ── Serial monitor ────────────────────────────────────────────────── */}
      {showMonitor && IS_LOCAL_CLI && (
        <div className="flex-1 min-h-0" style={{ minHeight: '14rem' }}>
          <SerialMonitor fwConfig={fwConfig} projectId={projectId} />
        </div>
      )}
    </div>
  )
}
