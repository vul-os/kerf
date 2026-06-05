// GeometryImportPanel.jsx — STEP / IGES / 3DM import preview + report
//
// Covers the file-exchange gap in the compare matrix:
//   - DXF / IGES / 3DM file exchange (maxsurf row)
//   - 3D PCB editor (STEP import, clearance) (altium row)
//
// Three integration points:
//   1. <GeometryImportButton> — trigger that opens <GeometryImportDialog>
//   2. <GeometryImportDialog> — modal: file picker + upload + import preview
//      Recognises .step/.stp/.iges/.igs/.3dm by extension.
//      Upload fires on file pick; import calls the appropriate LLM tool.
//   3. <GeometryImportReport> — inline report card (entity counts, warnings)
//
// Supported formats (kerf-imports backend):
//   .step / .stp  — STEP AP214 / AP242 (import_step / ap242_reader)
//   .iges / .igs  — IGES 5.3 (import_iges)
//   .3dm          — Rhino 3dm (import_3dm)
//   .dxf          — DXF r12–2018 (import_dxf)
//   .fcstd        — FreeCAD (import_freecad)

import { useEffect, useRef, useState } from 'react'
import {
  AlertCircle,
  Box,
  CheckCircle2,
  FileBox,
  Loader2,
  Upload,
  X,
} from 'lucide-react'
import { api, ApiError } from '../lib/api.js'

// ---------------------------------------------------------------------------
// Format detection
// ---------------------------------------------------------------------------

const SUPPORTED_EXTS = {
  '.step': { label: 'STEP',     icon: 'Box',     accept: '.step,.stp' },
  '.stp':  { label: 'STEP',     icon: 'Box',     accept: '.step,.stp' },
  '.iges': { label: 'IGES 5.3', icon: 'Box',     accept: '.iges,.igs' },
  '.igs':  { label: 'IGES 5.3', icon: 'Box',     accept: '.iges,.igs' },
  '.3dm':  { label: 'Rhino 3dm',icon: 'Box',     accept: '.3dm'       },
  '.dxf':  { label: 'DXF',      icon: 'FileBox', accept: '.dxf'       },
  '.fcstd':{ label: 'FreeCAD',  icon: 'FileBox', accept: '.FCStd,.fcstd' },
}

const ALL_ACCEPT = '.step,.stp,.iges,.igs,.3dm,.dxf,.FCStd,.fcstd'

export function detectGeometryFormat(fileOrName) {
  const name = typeof fileOrName === 'string' ? fileOrName : fileOrName?.name || ''
  const ext = '.' + name.split('.').pop().toLowerCase()
  return SUPPORTED_EXTS[ext] || null
}

export function isGeometryFile(fileOrName) {
  return detectGeometryFormat(fileOrName) !== null
}

// ---------------------------------------------------------------------------
// GeometryImportReport — inline entity-count card
// ---------------------------------------------------------------------------

/**
 * GeometryImportReport
 *
 * Props:
 *   format   — 'STEP' | 'IGES 5.3' | 'Rhino 3dm' | 'DXF' | 'FreeCAD'
 *   data     — raw import response from backend
 *   warnings — string[]
 */
export function GeometryImportReport({ format, data, warnings }) {
  if (!data) return null
  const [expanded, setExpanded] = useState(false)

  // Extract common stats across formats
  const stats = []

  if (data.entity_counts) {
    // IGES
    for (const [name, count] of Object.entries(data.entity_counts)) {
      if (count > 0) stats.push({ label: name, value: count })
    }
    if (data.nurbs_curves !== undefined)
      stats.push({ label: 'NURBS curves', value: data.nurbs_curves })
    if (data.nurbs_surfaces !== undefined)
      stats.push({ label: 'NURBS surfaces', value: data.nurbs_surfaces })
    if (data.brep_bodies !== undefined)
      stats.push({ label: 'B-rep bodies', value: data.brep_bodies })
  } else if (data.stats?.count_by_kind) {
    // Rhino 3dm
    for (const [kind, count] of Object.entries(data.stats.count_by_kind)) {
      if (count > 0) stats.push({ label: kind, value: count })
    }
  } else if (data.bodies !== undefined) {
    // STEP
    stats.push({ label: 'Bodies', value: data.bodies })
    if (data.surfaces) stats.push({ label: 'Surfaces', value: data.surfaces })
    if (data.curves) stats.push({ label: 'Curves', value: data.curves })
  } else if (data.created_files) {
    stats.push({ label: 'Files created', value: data.created_files.length })
  }

  const totalEntities = data.total_entities ?? stats.reduce((s, x) => s + (Number(x.value) || 0), 0)
  const allWarnings = [...(warnings || []), ...(data.warnings || [])]

  return (
    <div className="rounded-lg border border-emerald-600/40 bg-emerald-950/20 p-3 text-[11px]">
      <div className="flex items-center gap-2 mb-2">
        <CheckCircle2 size={12} className="text-emerald-400 shrink-0" />
        <span className="font-medium text-emerald-200">{format} import complete</span>
        <span className="ml-auto text-emerald-400 tabular-nums">
          {totalEntities > 0 ? `${totalEntities} entities` : 'parsed'}
        </span>
      </div>

      {stats.length > 0 && (
        <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[10px] text-emerald-300/80 mb-2">
          {stats.slice(0, 8).map((s, i) => (
            <div key={i} className="flex justify-between gap-1">
              <span className="truncate opacity-70">{s.label}</span>
              <span className="tabular-nums font-mono">{s.value}</span>
            </div>
          ))}
        </div>
      )}

      {data.units && (
        <div className="text-[10px] text-emerald-400/60">Units: {data.units}</div>
      )}
      {data.product_id && (
        <div className="text-[10px] text-emerald-400/60 truncate">Product: {data.product_id}</div>
      )}
      {data.source_system && (
        <div className="text-[10px] text-emerald-400/60 truncate">Source: {data.source_system}</div>
      )}

      {allWarnings.length > 0 && (
        <details className="mt-2" open={expanded}>
          <summary
            className="cursor-pointer text-[10px] text-amber-400/80 hover:text-amber-400 transition-colors"
            onClick={e => { e.preventDefault(); setExpanded(v => !v) }}
          >
            {allWarnings.length} warning{allWarnings.length !== 1 ? 's' : ''}
          </summary>
          {expanded && (
            <ul className="mt-1 space-y-0.5 text-[10px] text-amber-300/70 list-disc list-inside">
              {allWarnings.slice(0, 8).map((w, i) => (
                <li key={i} className="truncate" title={w}>{w}</li>
              ))}
              {allWarnings.length > 8 && (
                <li className="opacity-50">…and {allWarnings.length - 8} more</li>
              )}
            </ul>
          )}
        </details>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Progress card (same style as IFCImportProgress)
// ---------------------------------------------------------------------------

export function GeometryImportProgress({ filename, format, status, progress = 0, error, data, warnings, onDismiss }) {
  const isTerminal = status === 'done' || status === 'error'
  const isError = status === 'error'
  const isDone = status === 'done'

  return (
    <div
      className={[
        'rounded-lg border px-3 py-2.5 text-[11px] space-y-1.5',
        isError
          ? 'border-red-600/50 bg-red-950/30 text-red-200'
          : isDone
          ? 'border-emerald-600/40 bg-emerald-950/20 text-emerald-200'
          : 'border-kerf-300/30 bg-ink-850 text-ink-200',
      ].join(' ')}
    >
      <div className="flex items-center gap-2">
        {isDone ? (
          <CheckCircle2 size={13} className="shrink-0 text-emerald-400" />
        ) : isError ? (
          <AlertCircle size={13} className="shrink-0 text-red-400" />
        ) : (
          <Loader2 size={13} className="shrink-0 animate-spin text-kerf-300" />
        )}
        <span className="flex-1 truncate font-mono" title={filename}>{filename}</span>
        {status === 'uploading' && (
          <span className="shrink-0 tabular-nums">{progress}%</span>
        )}
        {isTerminal && onDismiss && (
          <button
            type="button"
            aria-label="Dismiss"
            onClick={onDismiss}
            className="p-0.5 rounded hover:bg-ink-700 text-current opacity-60 hover:opacity-100"
          >
            <X size={11} />
          </button>
        )}
      </div>

      {status === 'uploading' && (
        <div className="h-1 rounded bg-ink-800 overflow-hidden">
          <div
            className="h-full bg-kerf-300 transition-all duration-200"
            style={{ width: `${Math.max(2, progress)}%` }}
          />
        </div>
      )}

      <div className="text-[10px] opacity-70">
        {status === 'uploading' && `Uploading ${format || 'geometry'} file…`}
        {status === 'importing' && `Parsing ${format || 'geometry'} file…`}
        {isError && <span className="text-red-300">{error}</span>}
      </div>

      {isDone && data && (
        <GeometryImportReport format={format || 'Geometry'} data={data} warnings={warnings} />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Dialog
// ---------------------------------------------------------------------------

/**
 * GeometryImportDialog
 *
 * Props:
 *   projectId   — UUID of target Kerf project
 *   open        — boolean
 *   onClose     — callback
 *   onImported  — called with { format, data } on success
 */
export function GeometryImportDialog({ projectId, open, onClose, onImported }) {
  const fileInputRef = useRef(null)
  const [dragOver, setDragOver] = useState(false)
  const [importState, setImportState] = useState(null)

  useEffect(() => {
    if (!open) return
    const handler = (e) => {
      if (e.detail?.file && !importState) handleFile(e.detail.file)
    }
    window.addEventListener('kerf:geometry-drop', handler)
    return () => window.removeEventListener('kerf:geometry-drop', handler)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, importState])

  if (!open) return null

  function resetState() { setImportState(null) }

  async function handleFile(file) {
    if (!file) return
    const fmt = detectGeometryFormat(file)
    if (!fmt) {
      setImportState({
        filename: file.name, status: 'error',
        error: `Unsupported format. Supported: ${Object.keys(SUPPORTED_EXTS).join(', ')}`,
      })
      return
    }
    if (!projectId) {
      setImportState({
        filename: file.name, status: 'error',
        error: 'No project selected. Please create or open a project first.',
      })
      return
    }

    // Phase 1: upload
    setImportState({ filename: file.name, format: fmt.label, status: 'uploading', progress: 0 })
    let assetRecord
    try {
      assetRecord = await api.uploadAssetChunked(projectId, file, {
        kind: 'step',
        onProgress: ({ received, total }) => {
          const pct = total > 0 ? Math.round((received / total) * 100) : 0
          setImportState(s => ({ ...s, progress: pct }))
        },
      })
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : (err.message || 'Upload failed.')
      setImportState({ filename: file.name, format: fmt.label, status: 'error', error: msg })
      return
    }

    // Phase 2: import
    setImportState(s => ({ ...s, status: 'importing', progress: 100 }))
    try {
      const ext = '.' + file.name.split('.').pop().toLowerCase()
      let result

      if (ext === '.step' || ext === '.stp') {
        result = await api.importStep(projectId, assetRecord.id ?? assetRecord.file_id)
      } else if (ext === '.iges' || ext === '.igs') {
        result = await api.importIges(projectId, assetRecord.id ?? assetRecord.file_id)
      } else if (ext === '.3dm') {
        result = await api.import3dm(projectId, assetRecord.id ?? assetRecord.file_id)
      } else if (ext === '.dxf') {
        result = await api.importDxf(projectId, assetRecord.id ?? assetRecord.file_id)
      } else if (ext === '.fcstd') {
        result = await api.importFreecadProject(projectId, assetRecord.id ?? assetRecord.file_id)
      } else {
        throw new Error(`No import handler for ${ext}`)
      }

      setImportState(s => ({ ...s, status: 'done', data: result, warnings: result.warnings }))
      onImported?.({ format: fmt.label, data: result })
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : (err.message || 'Import failed.')
      setImportState(s => ({ ...s, status: 'error', error: msg }))
    }
  }

  function onInputChange(e) {
    handleFile(e.target.files?.[0])
    e.target.value = ''
  }

  function onDrop(e) {
    e.preventDefault()
    setDragOver(false)
    handleFile(e.dataTransfer.files?.[0])
  }

  const isRunning = importState && (importState.status === 'uploading' || importState.status === 'importing')

  return (
    <div className="fixed inset-0 z-50 grid place-items-center px-4">
      <div
        className="absolute inset-0 bg-ink-950/80 backdrop-blur-sm"
        onClick={!isRunning ? onClose : undefined}
        aria-hidden
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="geom-import-title"
        className="relative w-full max-w-md bg-ink-900 border border-ink-800 rounded-2xl shadow-2xl shadow-black/50"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-ink-800">
          <div className="flex items-center gap-2">
            <Box size={16} className="text-kerf-300" />
            <h2 id="geom-import-title" className="font-display text-base font-semibold tracking-tight">
              Import geometry file
            </h2>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            disabled={isRunning}
            className="text-ink-400 hover:text-ink-100 transition-colors disabled:opacity-40"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 flex flex-col gap-4">
          <p className="text-sm text-ink-300 leading-relaxed">
            Import STEP, IGES, Rhino .3dm, DXF, or FreeCAD files directly into
            your Kerf project. B-rep geometry is extracted and stored; metadata
            and entity counts are reported.
          </p>
          <p className="text-xs text-ink-400 leading-relaxed">
            Supported formats: <span className="font-mono">.step .stp .iges .igs .3dm .dxf .FCStd</span>
          </p>

          {!importState && (
            <div
              className={[
                'relative rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors cursor-pointer',
                dragOver
                  ? 'border-kerf-300/70 bg-kerf-300/5'
                  : 'border-ink-700 hover:border-ink-600 hover:bg-ink-800/40',
              ].join(' ')}
              onDragOver={e => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              onClick={() => fileInputRef.current?.click()}
              role="button"
              tabIndex={0}
              aria-label="Drop geometry file or click to browse"
              onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') fileInputRef.current?.click() }}
            >
              <Box size={28} className="mx-auto mb-3 text-ink-500" />
              <p className="text-sm text-ink-200 font-medium">
                Drop a geometry file here
              </p>
              <p className="mt-1 text-xs text-ink-400">
                or click to browse
              </p>
              <input
                ref={fileInputRef}
                type="file"
                accept={ALL_ACCEPT}
                className="hidden"
                onChange={onInputChange}
              />
            </div>
          )}

          {importState && (
            <GeometryImportProgress
              filename={importState.filename}
              format={importState.format}
              status={importState.status}
              progress={importState.progress}
              error={importState.error}
              data={importState.data}
              warnings={importState.warnings}
              onDismiss={!isRunning ? resetState : undefined}
            />
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-ink-800 flex items-center justify-between gap-2">
          <span className="text-[11px] text-ink-400 font-mono">
            STEP · IGES · 3dm · DXF · FreeCAD
          </span>
          <button
            type="button"
            onClick={onClose}
            disabled={isRunning}
            className="px-3 py-1.5 text-sm rounded-lg border border-ink-700 text-ink-200 hover:bg-ink-800 disabled:opacity-40 transition-colors"
          >
            {importState?.status === 'done' ? 'Done' : 'Cancel'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Button
// ---------------------------------------------------------------------------

/**
 * GeometryImportButton — opens <GeometryImportDialog>.
 */
export function GeometryImportButton({ projectId, onImported, className = '' }) {
  const [open, setOpen] = useState(false)

  return (
    <>
      <button
        type="button"
        title="Import STEP, IGES, Rhino .3dm, DXF, or FreeCAD geometry"
        onClick={() => setOpen(true)}
        className={[
          'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-sm font-medium',
          'border-ink-700 text-ink-200 hover:border-ink-600 hover:bg-ink-800/60 transition-colors',
          className,
        ].join(' ')}
      >
        <Upload size={13} />
        Import geometry
      </button>
      <GeometryImportDialog
        projectId={projectId}
        open={open}
        onClose={() => setOpen(false)}
        onImported={result => {
          setOpen(false)
          onImported?.(result)
        }}
      />
    </>
  )
}

export default GeometryImportPanel

// Dummy default export to satisfy named-export convention
function GeometryImportPanel({ projectId, onImported, className = '' }) {
  return <GeometryImportButton projectId={projectId} onImported={onImported} className={className} />
}
