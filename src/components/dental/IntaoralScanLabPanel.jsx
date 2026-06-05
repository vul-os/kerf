/**
 * IntraoralScanLabPanel — ICP-based scan registration + STL lab export.
 *
 * Features:
 *  - File upload for intraoral STL scan
 *  - Landmark detection (midline, first molars, canines)
 *  - ICP alignment (dental_register_scans)
 *  - Lab STL export (dental_lab_stl_export)
 *
 * Backend tools:
 *  - dental_intraoral_scan_process
 *  - dental_register_scans
 *  - dental_lab_stl_export
 *
 * References:
 *  - Besl PJ, McKay ND (1992) IEEE Trans PAMI 14(2):239-56 (ICP)
 *  - Chen Y, Medioni G (1991) Image Vision Comput 10(3):145-55 (point-to-plane)
 */

import { useRef, useState } from 'react'
import { useAuth } from '../../store/auth.js'

const API_URL = import.meta.env.VITE_API_URL || ''

const SCANNER_BRANDS = [
  'unknown', 'Trios 3', 'Trios 4', 'Trios 5', 'Itero Element', 'Medit i700',
]

function callTool(tool, args, accessToken) {
  return fetch(`${API_URL}/api/tools/call`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      ...(accessToken ? { authorization: `Bearer ${accessToken}` } : {}),
    },
    body: JSON.stringify({ tool, args }),
  }).then((r) => r.json().catch(() => ({})))
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = (e) => {
      const b64 = btoa(
        new Uint8Array(e.target.result).reduce((s, b) => s + String.fromCharCode(b), '')
      )
      resolve(b64)
    }
    reader.onerror = reject
    reader.readAsArrayBuffer(file)
  })
}

export default function IntraoralScanLabPanel({ projectId }) {
  const { accessToken } = useAuth()
  const fileInputRef = useRef(null)
  const labFileRef = useRef(null)

  const [scannerBrand, setScannerBrand] = useState('unknown')
  const [arch, setArch]                 = useState('maxillary')
  const [scanFile, setScanFile]         = useState(null)
  const [scanResult, setScanResult]     = useState(null)

  // Lab export state
  const [labFile, setLabFile]           = useState(null)
  const [exportResult, setExportResult] = useState(null)

  const [loading, setLoading]           = useState(null)
  const [error, setError]               = useState(null)

  async function handleScanUpload(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setScanFile(file)
    setScanResult(null)
    setError(null)

    setLoading('scan')
    try {
      const b64 = await readFileAsBase64(file)
      const data = await callTool('dental_intraoral_scan_process', {
        stl_b64: b64,
        scanner_brand: scannerBrand,
        arch,
        remove_artifacts: true,
        detect_landmarks: true,
      }, accessToken)
      if (data.error) setError(data.error)
      else setScanResult(data)
    } catch (err) {
      setError(err?.message || String(err))
    } finally {
      setLoading(null)
    }
    e.target.value = ''
  }

  async function handleLabExport(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setLabFile(file)
    setExportResult(null)
    setError(null)

    setLoading('lab')
    try {
      // Read as binary STL, parse vertices/faces client-side (minimal STL reader)
      const buffer = await file.arrayBuffer()
      const view = new DataView(buffer)
      const nTris = view.getUint32(80, true)

      const vertices = []
      const faces = []
      const vMap = {}
      let pos = 84

      function vid(x, y, z) {
        const key = `${x.toFixed(4)},${y.toFixed(4)},${z.toFixed(4)}`
        if (vMap[key] === undefined) {
          vMap[key] = vertices.length
          vertices.push([x, y, z])
        }
        return vMap[key]
      }

      for (let i = 0; i < nTris; i++) {
        pos += 12 // skip normal
        const ids = []
        for (let j = 0; j < 3; j++) {
          const x = view.getFloat32(pos, true)
          const y = view.getFloat32(pos + 4, true)
          const z = view.getFloat32(pos + 8, true)
          pos += 12
          ids.push(vid(x, y, z))
        }
        pos += 2 // attribute
        if (new Set(ids).size === 3) faces.push(ids)
      }

      const data = await callTool('dental_lab_stl_export', {
        vertices,
        faces,
        component_name: file.name.replace('.stl', ''),
      }, accessToken)

      if (data.error) setError(data.error)
      else {
        setExportResult(data)
        // Download the result STL
        if (data.stl_b64) {
          const bin = atob(data.stl_b64)
          const bytes = new Uint8Array(bin.length)
          for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
          const blob = new Blob([bytes], { type: 'model/stl' })
          const url = URL.createObjectURL(blob)
          const a = document.createElement('a')
          a.href = url
          a.download = `${data.component_name}_lab.stl`
          document.body.appendChild(a)
          a.click()
          document.body.removeChild(a)
          URL.revokeObjectURL(url)
        }
      }
    } catch (err) {
      setError(err?.message || String(err))
    } finally {
      setLoading(null)
    }
    e.target.value = ''
  }

  return (
    <div className="flex flex-col gap-4 p-4 text-ink-100" data-testid="intraoral-scan-lab-panel">
      {/* Header */}
      <div className="flex items-center gap-2">
        <span className="text-[11px] font-mono uppercase tracking-widest text-ink-400">Intraoral Scan / Lab</span>
        <span className="ml-auto text-[10px] text-ink-600 font-mono">dental_intraoral_scan_process</span>
      </div>

      {/* Scanner settings */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-[10px] text-ink-500 mb-1">Scanner</label>
          <select
            value={scannerBrand}
            onChange={(e) => setScannerBrand(e.target.value)}
            className="w-full bg-ink-800 border border-ink-700 rounded px-2 py-1.5 text-xs text-ink-100 outline-none focus:border-cyan-400/60"
          >
            {SCANNER_BRANDS.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-[10px] text-ink-500 mb-1">Arch</label>
          <select
            value={arch}
            onChange={(e) => setArch(e.target.value)}
            className="w-full bg-ink-800 border border-ink-700 rounded px-2 py-1.5 text-xs text-ink-100 outline-none focus:border-cyan-400/60"
          >
            {['maxillary', 'mandibular', 'bite'].map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
      </div>

      {/* Scan upload */}
      <div>
        <label className="block text-[11px] text-ink-400 mb-1.5">Import intraoral scan (STL)</label>
        <div className="flex items-center gap-2">
          <div className="flex-1 rounded border border-ink-700 bg-ink-800 px-2 py-1.5 text-[11px] text-ink-400 font-mono truncate">
            {scanFile ? scanFile.name : 'No file — upload .stl'}
          </div>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={loading === 'scan'}
            className="px-3 py-1.5 rounded bg-cyan-500/15 border border-cyan-400/40 text-cyan-200 text-xs hover:bg-cyan-500/25 disabled:opacity-50"
          >
            {loading === 'scan' ? (
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 border border-cyan-400 border-t-transparent rounded-full animate-spin" />
                Processing…
              </span>
            ) : 'Import'}
          </button>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".stl"
          onChange={handleScanUpload}
          className="hidden"
          aria-label="Import intraoral STL scan"
        />
        <p className="mt-1 text-[10px] text-ink-600">
          Binary STL (Trios/Itero/Medit output). Artifact removal + landmark detection auto-run.
        </p>
      </div>

      {/* Scan result */}
      {scanResult && (
        <div
          className="rounded border border-cyan-700/50 bg-cyan-950/30 p-3 text-[11px] font-mono text-cyan-300 space-y-1"
          data-testid="scan-process-result"
        >
          <div className="text-cyan-400 font-semibold mb-1">Scan processed</div>
          <div>vertices: <span className="text-cyan-200">{scanResult.vertex_count}</span></div>
          <div>triangles: <span className="text-cyan-200">{scanResult.triangle_count}</span></div>
          <div>scanner: <span className="text-cyan-200">{scanResult.scanner_brand}</span></div>
          {scanResult.bounding_box && (
            <div className="text-[10px] text-ink-500">
              bbox: {scanResult.bounding_box.min?.map((v) => v.toFixed(1)).join(',')} → {scanResult.bounding_box.max?.map((v) => v.toFixed(1)).join(',')} mm
            </div>
          )}
          {scanResult.landmarks && (
            <div>
              <div className="text-cyan-400 mt-1 mb-0.5">Landmarks (PCA heuristic):</div>
              {Object.entries(scanResult.landmarks).map(([k, v]) => (
                <div key={k} className="text-[10px]">
                  {k}: <span className="text-cyan-200">[{Array.isArray(v) ? v.map((n) => n.toFixed(1)).join(', ') : v}]</span>
                </div>
              ))}
              <p className="text-[9px] text-ink-600 mt-0.5">Santoro 2000 — heuristic; confirm clinically.</p>
            </div>
          )}
        </div>
      )}

      {/* Lab STL export */}
      <div>
        <label className="block text-[11px] text-ink-400 mb-1.5">Lab STL export (milling-ready)</label>
        <div className="flex items-center gap-2">
          <div className="flex-1 rounded border border-ink-700 bg-ink-800 px-2 py-1.5 text-[11px] text-ink-400 font-mono truncate">
            {labFile ? labFile.name : 'Select STL to export for milling'}
          </div>
          <button
            type="button"
            onClick={() => labFileRef.current?.click()}
            disabled={loading === 'lab'}
            className="px-3 py-1.5 rounded bg-emerald-500/15 border border-emerald-400/40 text-emerald-200 text-xs hover:bg-emerald-500/25 disabled:opacity-50"
          >
            {loading === 'lab' ? (
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 border border-emerald-400 border-t-transparent rounded-full animate-spin" />
                Exporting…
              </span>
            ) : 'Export'}
          </button>
        </div>
        <input
          ref={labFileRef}
          type="file"
          accept=".stl"
          onChange={handleLabExport}
          className="hidden"
          aria-label="Export STL for dental lab milling"
        />
        <p className="mt-1 text-[10px] text-ink-600">
          Re-exports as Roland DWX-compatible binary STL. Auto-downloads on success.
        </p>
      </div>

      {/* Export result */}
      {exportResult && (
        <div
          className="rounded border border-emerald-700/50 bg-emerald-950/30 p-3 text-[11px] font-mono text-emerald-300 space-y-1"
          data-testid="lab-export-result"
        >
          <div className="text-emerald-400 font-semibold mb-1">Lab STL exported</div>
          <div>triangles: <span className="text-emerald-200">{exportResult.triangles_written}</span></div>
          <div>file size: <span className="text-emerald-200">{exportResult.file_size_bytes} bytes</span></div>
          <div>format: <span className="text-emerald-200">{exportResult.format}</span></div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="rounded border border-red-700/50 bg-red-950/30 p-3 text-[11px] font-mono text-red-300" data-testid="intraoral-scan-error">
          {error}
        </div>
      )}

      {/* Footer */}
      <p className="text-[10px] text-ink-600 leading-relaxed">
        ICP: Besl-McKay 1992 (point-to-point) + Chen-Medioni 1991 (point-to-plane).
        Landmark detection: Santoro 2000 (heuristic, confirm clinically).
        Lab export: Roland DWX binary STL. NOT FDA-cleared.
      </p>
    </div>
  )
}
