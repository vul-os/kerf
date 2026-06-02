// KiCadRoundTripPanel — KiCad bridge widget for the Electronics tab.
//
// Provides a two-step workflow:
//   1. Export: sends the current CircuitJSON to elec_export_kicad LLM tool
//      to write a .kicad_pro/.kicad_sch/.kicad_pcb directory.
//   2. Import: reads a routed .kicad_pcb path from the user and calls
//      elec_import_kicad_pcb to bring tracks/vias/footprint positions back.
//
// Props:
//   circuitJson   — parsed CircuitJSON array (from workspace store)
//   onImportResult — (KiCadImportResult) => void  (optional; called after import)
//
// The panel calls LLM tools via the Kerf tool invocation helper if available,
// falling back to clipboard-friendly JSON instructions when the API is absent.

import { useCallback, useState } from 'react'
import { ArrowDownToLine, ArrowUpFromLine, CheckCircle, CircuitBoard, Info, Loader, XCircle } from 'lucide-react'

// ─── constants ────────────────────────────────────────────────────────────────

const STEP_IDLE    = 'idle'
const STEP_RUNNING = 'running'
const STEP_OK      = 'ok'
const STEP_ERROR   = 'error'

// ─── StatusBadge ─────────────────────────────────────────────────────────────

function StatusBadge({ status, message }) {
  if (status === STEP_IDLE)    return null
  if (status === STEP_RUNNING) return (
    <div className="flex items-center gap-1.5 text-[11px] text-ink-400">
      <Loader size={11} className="animate-spin" />
      {message || 'Working…'}
    </div>
  )
  if (status === STEP_OK) return (
    <div className="flex items-start gap-1.5 text-[11px] text-green-400">
      <CheckCircle size={11} className="mt-0.5 flex-shrink-0" />
      <span className="break-all">{message}</span>
    </div>
  )
  if (status === STEP_ERROR) return (
    <div className="flex items-start gap-1.5 text-[11px] text-red-400">
      <XCircle size={11} className="mt-0.5 flex-shrink-0" />
      <span className="break-all">{message}</span>
    </div>
  )
  return null
}

// ─── InfoBox ─────────────────────────────────────────────────────────────────

function InfoBox({ children }) {
  return (
    <div className="flex items-start gap-1.5 rounded bg-ink-800/50 border border-ink-700 px-2.5 py-2 text-[10px] text-ink-400 leading-relaxed">
      <Info size={10} className="mt-0.5 flex-shrink-0 text-ink-500" />
      <span>{children}</span>
    </div>
  )
}

// ─── KiCadRoundTripPanel ─────────────────────────────────────────────────────

export default function KiCadRoundTripPanel({ circuitJson, onImportResult }) {
  // Export state
  const [exportDir, setExportDir]       = useState('')
  const [exportStem, setExportStem]     = useState('board')
  const [exportStatus, setExportStatus] = useState(STEP_IDLE)
  const [exportMsg, setExportMsg]       = useState('')
  const [exportResult, setExportResult] = useState(null)

  // Import state
  const [importPath, setImportPath]     = useState('')
  const [importStatus, setImportStatus] = useState(STEP_IDLE)
  const [importMsg, setImportMsg]       = useState('')
  const [importResult, setImportResult] = useState(null)

  // ── Export ─────────────────────────────────────────────────────────────

  const handleExport = useCallback(async () => {
    if (!circuitJson || !Array.isArray(circuitJson) || circuitJson.length === 0) {
      setExportStatus(STEP_ERROR)
      setExportMsg('No circuit data loaded. Open a .circuit file first.')
      return
    }
    const dir = exportDir.trim()
    if (!dir) {
      setExportStatus(STEP_ERROR)
      setExportMsg('Please enter an output directory path.')
      return
    }

    setExportStatus(STEP_RUNNING)
    setExportMsg('Exporting to KiCad…')
    setExportResult(null)

    try {
      // Invoke via Kerf tool API if available, else surface the call as JSON
      const toolArgs = {
        circuit_json: circuitJson,
        output_dir: dir,
        stem: exportStem.trim() || 'board',
      }

      let result = null

      if (typeof window !== 'undefined' && window.__kerf_invoke_tool) {
        result = await window.__kerf_invoke_tool('elec_export_kicad', toolArgs)
      } else {
        // Fallback: display the tool call for the user to run via chat
        setExportStatus(STEP_OK)
        setExportMsg(
          `Run this in Kerf Chat:\n\n` +
          `elec_export_kicad(${JSON.stringify(toolArgs, null, 2)})`
        )
        return
      }

      if (result?.error) {
        setExportStatus(STEP_ERROR)
        setExportMsg(`Export error: ${result.error}`)
        return
      }

      setExportResult(result)
      setExportStatus(STEP_OK)
      setExportMsg(
        `Exported ${result.num_components} component(s), ${result.num_nets} net(s). ` +
        `PCB file: ${result.pcb_path}`
      )
      // Pre-fill import path for convenience
      if (result.pcb_path && !importPath) {
        setImportPath(result.pcb_path)
      }
    } catch (err) {
      setExportStatus(STEP_ERROR)
      setExportMsg(`Unexpected error: ${err.message || String(err)}`)
    }
  }, [circuitJson, exportDir, exportStem, importPath])

  // ── Import ─────────────────────────────────────────────────────────────

  const handleImport = useCallback(async () => {
    const path = importPath.trim()
    if (!path) {
      setImportStatus(STEP_ERROR)
      setImportMsg('Please enter the path to the routed .kicad_pcb file.')
      return
    }

    setImportStatus(STEP_RUNNING)
    setImportMsg('Importing from KiCad…')
    setImportResult(null)

    try {
      const toolArgs = { pcb_path: path }

      let result = null

      if (typeof window !== 'undefined' && window.__kerf_invoke_tool) {
        result = await window.__kerf_invoke_tool('elec_import_kicad_pcb', toolArgs)
      } else {
        setImportStatus(STEP_OK)
        setImportMsg(
          `Run this in Kerf Chat:\n\nelec_import_kicad_pcb(${JSON.stringify(toolArgs, null, 2)})`
        )
        return
      }

      if (result?.error) {
        setImportStatus(STEP_ERROR)
        setImportMsg(`Import error: ${result.error}`)
        return
      }

      setImportResult(result)
      setImportStatus(STEP_OK)
      setImportMsg(
        `Imported ${result.num_tracks} track(s), ${result.num_vias} via(s), ` +
        `${result.num_footprints} footprint(s).`
      )
      onImportResult?.(result)
    } catch (err) {
      setImportStatus(STEP_ERROR)
      setImportMsg(`Unexpected error: ${err.message || String(err)}`)
    }
  }, [importPath, onImportResult])

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col gap-3 p-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        <CircuitBoard size={13} className="text-kerf-300 flex-shrink-0" />
        <span className="text-[11px] font-semibold text-ink-200 uppercase tracking-wider">
          KiCad Round-Trip
        </span>
      </div>

      <InfoBox>
        Kerf is view-only for interactive PCB routing. Export to KiCad, route in Pcbnew,
        then import back to run Kerf DRC / fab tools on the finished board.
      </InfoBox>

      {/* ── Step 1 — Export ─────────────────────────────────────────── */}
      <section>
        <h3 className="text-[10px] font-semibold uppercase tracking-wider text-ink-500 mb-2">
          Step 1 — Export to KiCad
        </h3>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] text-ink-400" htmlFor="kicad-export-dir">
            Output directory
          </label>
          <input
            id="kicad-export-dir"
            type="text"
            value={exportDir}
            onChange={(e) => setExportDir(e.target.value)}
            placeholder="/tmp/my-board-kicad"
            className="w-full rounded bg-ink-800 border border-ink-700 text-[11px] text-ink-200 px-2 py-1.5 placeholder-ink-600 focus:outline-none focus:border-kerf-300/50"
          />

          <label className="text-[10px] text-ink-400" htmlFor="kicad-export-stem">
            Project name (stem)
          </label>
          <input
            id="kicad-export-stem"
            type="text"
            value={exportStem}
            onChange={(e) => setExportStem(e.target.value)}
            placeholder="board"
            className="w-full rounded bg-ink-800 border border-ink-700 text-[11px] text-ink-200 px-2 py-1.5 placeholder-ink-600 focus:outline-none focus:border-kerf-300/50"
          />

          <button
            type="button"
            onClick={handleExport}
            disabled={exportStatus === STEP_RUNNING}
            className={[
              'flex items-center justify-center gap-1.5 rounded px-3 py-1.5 text-[11px] font-medium',
              'focus:outline-none focus:ring-2 focus:ring-kerf-300 min-h-[2rem]',
              exportStatus === STEP_RUNNING
                ? 'bg-ink-700 text-ink-500 cursor-not-allowed'
                : 'bg-kerf-300 text-ink-950 hover:bg-kerf-200',
            ].join(' ')}
          >
            <ArrowDownToLine size={11} />
            Export to KiCad
          </button>

          <StatusBadge status={exportStatus} message={exportMsg} />

          {exportResult && exportStatus === STEP_OK && (
            <div className="rounded bg-ink-800/60 border border-ink-700 px-2.5 py-2 text-[10px] text-ink-400 space-y-0.5">
              <div><span className="text-ink-500">Components:</span> {exportResult.num_components}</div>
              <div><span className="text-ink-500">Nets:</span> {exportResult.num_nets}</div>
              <div><span className="text-ink-500">PCB:</span> <span className="font-mono break-all">{exportResult.pcb_path}</span></div>
            </div>
          )}
        </div>

        <div className="mt-2">
          <InfoBox>
            Open the exported <span className="font-mono">.kicad_pcb</span> in KiCad Pcbnew, route the board, then save.
            Route → File → Save (Ctrl+S).
          </InfoBox>
        </div>
      </section>

      {/* ── Step 2 — Import ─────────────────────────────────────────── */}
      <section>
        <h3 className="text-[10px] font-semibold uppercase tracking-wider text-ink-500 mb-2">
          Step 2 — Import routed .kicad_pcb
        </h3>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] text-ink-400" htmlFor="kicad-import-path">
            Routed .kicad_pcb path
          </label>
          <input
            id="kicad-import-path"
            type="text"
            value={importPath}
            onChange={(e) => setImportPath(e.target.value)}
            placeholder="/tmp/my-board-kicad/board.kicad_pcb"
            className="w-full rounded bg-ink-800 border border-ink-700 text-[11px] text-ink-200 px-2 py-1.5 placeholder-ink-600 focus:outline-none focus:border-kerf-300/50"
          />

          <button
            type="button"
            onClick={handleImport}
            disabled={importStatus === STEP_RUNNING}
            className={[
              'flex items-center justify-center gap-1.5 rounded px-3 py-1.5 text-[11px] font-medium',
              'focus:outline-none focus:ring-2 focus:ring-kerf-300 min-h-[2rem]',
              importStatus === STEP_RUNNING
                ? 'bg-ink-700 text-ink-500 cursor-not-allowed'
                : 'bg-ink-700 border border-ink-600 text-ink-200 hover:bg-ink-600 hover:border-ink-500',
            ].join(' ')}
          >
            <ArrowUpFromLine size={11} />
            Import from KiCad
          </button>

          <StatusBadge status={importStatus} message={importMsg} />

          {importResult && importStatus === STEP_OK && (
            <div className="rounded bg-ink-800/60 border border-ink-700 px-2.5 py-2 text-[10px] text-ink-400 space-y-0.5">
              <div><span className="text-ink-500">Tracks:</span> {importResult.num_tracks}</div>
              <div><span className="text-ink-500">Vias:</span> {importResult.num_vias}</div>
              <div><span className="text-ink-500">Footprints:</span> {importResult.num_footprints}</div>
              {importResult.net_names?.length > 0 && (
                <div>
                  <span className="text-ink-500">Nets:</span>{' '}
                  {importResult.net_names.slice(0, 8).join(', ')}
                  {importResult.net_names.length > 8 && ` +${importResult.net_names.length - 8} more`}
                </div>
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
