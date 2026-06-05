// MultiBoardPanel.jsx — Altium MB3D-style multi-board workspace panel.
//
// Provides: workspace creation, inter-board connector declaration,
// mating validation, cross-board net map, and STEP assembly export.
//
// Backend contracts:
//   POST /api/llm-tools/electronics_mb3d_create_workspace   {workspace_name, boards}
//   POST /api/llm-tools/electronics_mb3d_add_connector      {name, from_board, …}
//   POST /api/llm-tools/electronics_mb3d_validate_workspace {workspace_name, boards, connectors}
//   POST /api/llm-tools/electronics_mb3d_net_map            {workspace_name, boards, connectors}
//   POST /api/llm-tools/electronics_mb3d_export_step        {workspace_name, boards, connectors}
//
// References: Altium MB3D Design Guide §2-5; IPC-2581 §7.4.
//
// Props:
//   onClose — () => void

import { useCallback, useState } from 'react'
import { Box, Network, AlertTriangle, CheckCircle2, X, Download, RefreshCw } from 'lucide-react'

// ── Demo fixture ─────────────────────────────────────────────────────────────

const DEMO_WORKSPACE = {
  workspace_name: 'Demo Assembly',
  boards: [
    { board_id: 'cpu_board', file_path: 'boards/cpu.circuitjson',
      position: [0, 0, 0], rotation_xyz_deg: [0, 0, 0],
      board_width_mm: 100, board_height_mm: 80 },
    { board_id: 'io_board',  file_path: 'boards/io.circuitjson',
      position: [200, 0, 0], rotation_xyz_deg: [0, 0, 0],
      board_width_mm: 80, board_height_mm: 60 },
  ],
  connectors: [
    { name: 'J1-J2 PCIe link',
      from_board: 'cpu_board', from_designator: 'J1', from_pin_count: 4,
      to_board: 'io_board',   to_designator: 'J2', to_pin_count: 4,
      pin_mapping: { '1': 1, '2': 2, '3': 3, '4': 4 }, connector_type: 'board_to_board' },
  ],
}

// ── Helpers ──────────────────────────────────────────────────────────────────

async function apiPost(endpoint, body) {
  try {
    const r = await fetch(`/api/llm-tools/${endpoint}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    })
    return r.ok ? r.json() : { ok: false, error: `HTTP ${r.status}` }
  } catch (e) {
    return { ok: false, error: e.message }
  }
}

// ── Violation row ────────────────────────────────────────────────────────────

function IssueRow({ text }) {
  return (
    <div className="flex items-start gap-2 px-2 py-1 text-[11px]">
      <AlertTriangle size={12} className="text-yellow-400 mt-0.5 shrink-0" />
      <span className="text-gray-300">{text}</span>
    </div>
  )
}

// ── Main panel ───────────────────────────────────────────────────────────────

export default function MultiBoardPanel({ onClose }) {
  const [tab, setTab] = useState('workspace')
  const [loading, setLoading] = useState(false)
  const [validateResult, setValidateResult] = useState(null)
  const [netMapResult, setNetMapResult]     = useState(null)
  const [stepResult, setStepResult]         = useState(null)
  const [offline, setOffline]               = useState(false)

  const ws = DEMO_WORKSPACE

  const runValidate = useCallback(async () => {
    setLoading(true)
    const r = await apiPost('electronics_mb3d_validate_workspace', ws)
    setLoading(false)
    if (!r || r.error) { setOffline(true); return }
    setValidateResult(r)
  }, [])

  const runNetMap = useCallback(async () => {
    setLoading(true)
    const r = await apiPost('electronics_mb3d_net_map', ws)
    setLoading(false)
    if (!r || r.error) { setOffline(true); return }
    setNetMapResult(r)
  }, [])

  const runExportStep = useCallback(async () => {
    setLoading(true)
    const r = await apiPost('electronics_mb3d_export_step', ws)
    setLoading(false)
    if (!r || r.error) { setOffline(true); return }
    setStepResult(r)
  }, [])

  const TABS = [
    { id: 'workspace', label: 'Workspace' },
    { id: 'connectors', label: 'Connectors' },
    { id: 'netmap', label: 'Net Map' },
    { id: 'export', label: 'STEP Export' },
  ]

  return (
    <div
      data-testid="multi-board-panel"
      className="absolute top-12 right-4 w-96 bg-[#12122a] border border-white/10 rounded-xl shadow-2xl z-50 flex flex-col max-h-[80vh] overflow-hidden"
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-white/10">
        <Box size={15} className="text-indigo-400" />
        <span className="text-sm font-semibold text-white">Multi-Board Workspace (MB3D)</span>
        <button
          data-testid="multi-board-close"
          onClick={onClose}
          className="ml-auto p-1 rounded hover:bg-white/10 text-gray-500 hover:text-white transition-colors"
        >
          <X size={14} />
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 px-3 pt-2">
        {TABS.map(({ id, label }) => (
          <button
            key={id}
            data-testid={`mb3d-tab-${id}`}
            onClick={() => setTab(id)}
            className={[
              'px-3 py-1.5 rounded-md text-[11px] font-medium transition-colors',
              tab === id ? 'bg-indigo-600 text-white' : 'text-gray-400 hover:text-white hover:bg-white/10',
            ].join(' ')}
          >
            {label}
          </button>
        ))}
      </div>

      {offline && (
        <div className="mx-3 mt-2 px-3 py-2 bg-yellow-900/30 border border-yellow-700/40 rounded-lg text-[11px] text-yellow-300">
          Backend offline — showing demo data (MB3D tools wired, backend not reachable)
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3" data-testid="mb3d-content">
        {/* ── Workspace tab ─────────────────────────────────────────────── */}
        {tab === 'workspace' && (
          <div className="space-y-3">
            <div className="text-[11px] text-gray-400 px-1">
              Workspace: <span className="text-white font-medium">{ws.workspace_name}</span>
              <span className="ml-2 text-gray-500">({ws.boards.length} boards)</span>
            </div>

            {/* Board list */}
            <div className="space-y-1">
              {ws.boards.map((b) => (
                <div key={b.board_id}
                  data-testid={`mb3d-board-${b.board_id}`}
                  className="px-3 py-2 bg-white/5 rounded-lg text-[11px]"
                >
                  <div className="font-medium text-white">{b.board_id}</div>
                  <div className="text-gray-500">
                    pos: ({b.position.join(', ')}) mm — {b.board_width_mm}×{b.board_height_mm} mm
                  </div>
                </div>
              ))}
            </div>

            {/* Validate button */}
            <button
              data-testid="mb3d-validate-btn"
              onClick={runValidate}
              disabled={loading}
              className="w-full py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs font-medium flex items-center justify-center gap-2 transition-colors"
            >
              {loading ? <RefreshCw size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
              Validate Workspace
            </button>

            {validateResult && (
              <div data-testid="mb3d-validate-result" className="space-y-1">
                <div className={`text-[11px] font-medium ${validateResult.valid ? 'text-emerald-400' : 'text-red-400'}`}>
                  {validateResult.valid ? '✓ Workspace valid' : `✗ ${(validateResult.mating_issues?.length ?? 0) + (validateResult.overlap_warnings?.length ?? 0)} issue(s) found`}
                </div>
                {[...(validateResult.mating_issues ?? []), ...(validateResult.overlap_warnings ?? [])].map((issue, idx) => (
                  <IssueRow key={idx} text={issue} />
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Connectors tab ────────────────────────────────────────────── */}
        {tab === 'connectors' && (
          <div className="space-y-2">
            <div className="text-[11px] text-gray-400 px-1">{ws.connectors.length} connector pair(s)</div>
            {ws.connectors.map((c, idx) => (
              <div key={idx} className="px-3 py-2 bg-white/5 rounded-lg text-[11px] space-y-0.5">
                <div className="font-medium text-white">{c.name}</div>
                <div className="text-gray-400">
                  {c.from_board}/{c.from_designator} ({c.from_pin_count}P)
                  <span className="mx-1 text-gray-600">↔</span>
                  {c.to_board}/{c.to_designator} ({c.to_pin_count}P)
                </div>
                <div className="text-gray-500">
                  type: {c.connector_type} — {Object.keys(c.pin_mapping).length} pins mapped
                </div>
              </div>
            ))}
            <div className="text-[10px] text-gray-600 px-1">
              IPC-2581 §7.4 inter-board net declaration; pin mapping: {'{'}from_pin→to_pin{'}'}
            </div>
          </div>
        )}

        {/* ── Net map tab ───────────────────────────────────────────────── */}
        {tab === 'netmap' && (
          <div className="space-y-3">
            <button
              data-testid="mb3d-netmap-btn"
              onClick={runNetMap}
              disabled={loading}
              className="w-full py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs font-medium flex items-center justify-center gap-2 transition-colors"
            >
              {loading ? <RefreshCw size={12} className="animate-spin" /> : <Network size={12} />}
              Compute Net Map
            </button>

            {netMapResult && (
              <div data-testid="mb3d-netmap-result" className="space-y-2">
                <div className="text-[11px] text-gray-300">
                  {netMapResult.bridge_count ?? 0} cross-board bridge(s)
                  {netMapResult.floating_nets?.length > 0 && (
                    <span className="ml-2 text-yellow-400">
                      {netMapResult.floating_nets.length} floating net(s)
                    </span>
                  )}
                </div>
                {(netMapResult.bridges ?? []).slice(0, 8).map((b, idx) => (
                  <div key={idx} className="px-2 py-1 bg-white/5 rounded text-[10px] text-gray-400">
                    <span className="text-white">{b.workspace_net}</span>:{' '}
                    {b.board_a}/{b.board_a_net} ↔ {b.board_b}/{b.board_b_net}
                  </div>
                ))}
                {(netMapResult.continuity_issues ?? []).map((iss, idx) => (
                  <IssueRow key={idx} text={iss} />
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── STEP export tab ───────────────────────────────────────────── */}
        {tab === 'export' && (
          <div className="space-y-3">
            <div className="text-[11px] text-gray-400 px-1">
              Export multi-board assembly as STEP AP242 (ISO 10303-242:2014 §4).
              Each board is placed at its declared workspace position and rotation.
            </div>
            <button
              data-testid="mb3d-step-btn"
              onClick={runExportStep}
              disabled={loading}
              className="w-full py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs font-medium flex items-center justify-center gap-2 transition-colors"
            >
              {loading ? <RefreshCw size={12} className="animate-spin" /> : <Download size={12} />}
              Export STEP Assembly
            </button>

            {stepResult && (
              <div data-testid="mb3d-step-result" className="px-3 py-2 bg-emerald-900/30 border border-emerald-700/40 rounded-lg text-[11px] space-y-0.5">
                <div className="text-emerald-300 font-medium">STEP export ready</div>
                <div className="text-gray-400">File: {stepResult.filename}</div>
                <div className="text-gray-400">
                  {stepResult.board_count} boards — {(stepResult.size_bytes / 1024).toFixed(1)} KB
                </div>
              </div>
            )}

            <div className="text-[10px] text-gray-600 px-1">
              Format: STEP AP242 — compatible with SolidWorks, Creo, CATIA, Inventor.
              Board geometry: bounding-box approximation (exact geometry requires pythonOCC).
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
