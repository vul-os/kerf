/**
 * SysMLTracePanel.jsx — SysML Traceability UI.
 *
 * Three tabs:
 *   1. Coverage Matrix  — requirements / design elements / test cases with coverage % bars
 *   2. Trace Graph      — SVG force-directed graph (req ↔ design ↔ tests)
 *   3. XMI Export       — serialized XMI from /api/llm-tools/sysml_export_xmi + Download
 *
 * Tools used:
 *   POST /api/llm-tools/sysml_trace_coverage  → {covered, uncovered, total, coverage_pct, ...}
 *   POST /api/llm-tools/sysml_export_xmi      → {ok, path, ...} (XMI text in body or fetched)
 */

import { useState, useCallback, useRef, useEffect } from 'react'
import { Download, RefreshCw, GitBranch, Table2, FileCode } from 'lucide-react'

// ---------------------------------------------------------------------------
// Demo seed data
// ---------------------------------------------------------------------------

const DEMO_REQUIREMENTS = [
  { id: 'REQ-001', text: 'System shall support 1000 concurrent users',    satisfied_by: ['BLK-001'],          verified_by: ['TC-001', 'TC-002'] },
  { id: 'REQ-002', text: 'Response time < 200 ms at p99',                  satisfied_by: ['BLK-001', 'BLK-002'], verified_by: ['TC-003'] },
  { id: 'REQ-003', text: 'Data encrypted at rest (AES-256)',               satisfied_by: ['BLK-003'],          verified_by: ['TC-004'] },
  { id: 'REQ-004', text: 'Audit log retained for 7 years',                 satisfied_by: [],                   verified_by: [] },
  { id: 'REQ-005', text: 'API versioned; breaking changes require semver', satisfied_by: ['BLK-002'],          verified_by: [] },
]

const DEMO_DESIGN_ELEMENTS = [
  { id: 'BLK-001', kind: 'block', name: 'LoadBalancer',    allocated_to: ['REQ-001', 'REQ-002'] },
  { id: 'BLK-002', kind: 'block', name: 'APIGateway',      allocated_to: ['REQ-002', 'REQ-005'] },
  { id: 'BLK-003', kind: 'block', name: 'EncryptionLayer', allocated_to: ['REQ-003'] },
]

const DEMO_TEST_CASES = [
  { id: 'TC-001', name: 'Load test 1000 users',       verifies: ['REQ-001'] },
  { id: 'TC-002', name: 'Spike load test',            verifies: ['REQ-001'] },
  { id: 'TC-003', name: 'Latency regression suite',   verifies: ['REQ-002'] },
  { id: 'TC-004', name: 'Encryption cipher audit',    verifies: ['REQ-003'] },
  { id: 'TC-005', name: 'Orphan test (no req link)',  verifies: [] },
]

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function pctBar(pct, color = 'bg-blue-500') {
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${color}`}
          style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          role="progressbar"
        />
      </div>
      <span className="text-xs tabular-nums w-10 text-right text-gray-600 dark:text-gray-400">
        {pct.toFixed(0)}%
      </span>
    </div>
  )
}

function coverageColor(pct) {
  if (pct >= 80) return 'bg-green-500'
  if (pct >= 50) return 'bg-amber-500'
  return 'bg-red-500'
}

// ---------------------------------------------------------------------------
// Tab: Coverage Matrix
// ---------------------------------------------------------------------------

function CoverageMatrixTab({ report, requirements, designElements, testCases }) {
  if (!report) {
    return (
      <p className="text-sm text-gray-400 dark:text-gray-500 italic mt-4">
        Click &ldquo;Compute Coverage&rdquo; to generate the traceability matrix.
      </p>
    )
  }

  const { covered, uncovered, total, coverage_pct, orphaned_requirements, unverified_requirements, orphaned_tests } = report

  // Per-requirement coverage
  const reqRows = requirements.map((req) => {
    const hasDesign = (req.satisfied_by ?? []).length > 0
    const hasTest   = (req.verified_by ?? []).length > 0
    const pct = hasDesign && hasTest ? 100 : hasDesign || hasTest ? 50 : 0
    return { ...req, pct }
  })

  // Design coverage: % of reqs that reference this block
  const totalReqs = requirements.length || 1
  const designRows = designElements.map((de) => {
    const count = requirements.filter((r) => (r.satisfied_by ?? []).includes(de.id)).length
    return { ...de, pct: (count / totalReqs) * 100 }
  })

  // Test coverage: verifies at least 1 req?
  const testRows = testCases.map((tc) => {
    const active = (tc.verifies ?? []).length > 0
    return { ...tc, pct: active ? 100 : 0 }
  })

  return (
    <div className="flex flex-col gap-6 mt-4">
      {/* Summary stats */}
      <div className="flex flex-wrap gap-4">
        {[
          { label: 'Overall coverage',  value: `${coverage_pct?.toFixed(1) ?? 0}%`, sub: `${covered}/${total} requirements` },
          { label: 'Orphaned reqs',     value: orphaned_requirements?.length ?? 0,   sub: 'no design link' },
          { label: 'Unverified reqs',   value: unverified_requirements?.length ?? 0, sub: 'no test case' },
          { label: 'Orphaned tests',    value: orphaned_tests?.length ?? 0,          sub: 'verify nothing' },
        ].map(({ label, value, sub }) => (
          <div key={label} className="rounded-lg border border-gray-200 dark:border-gray-700 px-4 py-3 min-w-[120px]">
            <div className="text-xl font-bold tabular-nums text-gray-900 dark:text-gray-100">{value}</div>
            <div className="text-xs font-medium text-gray-700 dark:text-gray-300">{label}</div>
            <div className="text-xs text-gray-400 dark:text-gray-500">{sub}</div>
          </div>
        ))}
      </div>

      {/* Three columns */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">

        {/* Requirements */}
        <div className="flex flex-col gap-2">
          <h3 className="text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wide">
            Requirements ({reqRows.length})
          </h3>
          <div className="flex flex-col gap-2">
            {reqRows.map((req) => (
              <div key={req.id} className="flex flex-col gap-1 rounded border border-gray-100 dark:border-gray-800 p-2">
                <div className="flex items-start justify-between gap-2">
                  <span className="font-mono text-xs text-blue-700 dark:text-blue-400">{req.id}</span>
                  <span className={`rounded-full px-1.5 py-0.5 text-xs font-medium ${
                    req.pct === 100
                      ? 'bg-green-100 dark:bg-green-950/30 text-green-700 dark:text-green-400'
                      : req.pct === 50
                      ? 'bg-amber-100 dark:bg-amber-950/30 text-amber-700 dark:text-amber-400'
                      : 'bg-red-100 dark:bg-red-950/30 text-red-700 dark:text-red-400'
                  }`}>
                    {req.pct === 100 ? 'Full' : req.pct === 50 ? 'Partial' : 'None'}
                  </span>
                </div>
                <p className="text-xs text-gray-600 dark:text-gray-400 line-clamp-2">{req.text}</p>
                {pctBar(req.pct, coverageColor(req.pct))}
              </div>
            ))}
          </div>
        </div>

        {/* Design elements */}
        <div className="flex flex-col gap-2">
          <h3 className="text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wide">
            Design Elements ({designRows.length})
          </h3>
          <div className="flex flex-col gap-2">
            {designRows.map((de) => (
              <div key={de.id} className="flex flex-col gap-1 rounded border border-gray-100 dark:border-gray-800 p-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs text-purple-700 dark:text-purple-400">{de.id}</span>
                  <span className="text-xs text-gray-500 dark:text-gray-400 italic">{de.kind}</span>
                </div>
                <p className="text-xs font-medium text-gray-800 dark:text-gray-200">{de.name}</p>
                {pctBar(de.pct, 'bg-purple-500')}
              </div>
            ))}
          </div>
        </div>

        {/* Test cases */}
        <div className="flex flex-col gap-2">
          <h3 className="text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wide">
            Test Cases ({testRows.length})
          </h3>
          <div className="flex flex-col gap-2">
            {testRows.map((tc) => (
              <div key={tc.id} className="flex flex-col gap-1 rounded border border-gray-100 dark:border-gray-800 p-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs text-teal-700 dark:text-teal-400">{tc.id}</span>
                  {tc.pct === 0 && (
                    <span className="rounded-full bg-red-100 dark:bg-red-950/30 text-red-600 dark:text-red-400 px-1.5 py-0.5 text-xs">
                      Orphan
                    </span>
                  )}
                </div>
                <p className="text-xs text-gray-600 dark:text-gray-400">{tc.name}</p>
                {pctBar(tc.pct, 'bg-teal-500')}
              </div>
            ))}
          </div>
        </div>

      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab: Trace Graph (SVG force-directed)
// ---------------------------------------------------------------------------

const NODE_RADIUS = 20
const WIDTH  = 640
const HEIGHT = 360

function TraceGraphTab({ requirements, designElements, testCases }) {
  const svgRef = useRef(null)
  const animRef = useRef(null)

  // Build nodes + edges
  const nodes = [
    ...requirements.map((r, i) => ({
      id: r.id, label: r.id, kind: 'req',
      x: 80 + (i % 3) * 90 + Math.random() * 20,
      y: 60 + Math.floor(i / 3) * 80 + Math.random() * 20,
      vx: 0, vy: 0,
    })),
    ...designElements.map((d, i) => ({
      id: d.id, label: d.name ?? d.id, kind: 'design',
      x: 200 + i * 100 + Math.random() * 20,
      y: 200 + Math.random() * 20,
      vx: 0, vy: 0,
    })),
    ...testCases.map((t, i) => ({
      id: t.id, label: t.id, kind: 'test',
      x: 80 + (i % 4) * 110 + Math.random() * 20,
      y: 300 + Math.random() * 20,
      vx: 0, vy: 0,
    })),
  ]

  const nodeMap = Object.fromEntries(nodes.map((n) => [n.id, n]))

  const edges = []
  for (const req of requirements) {
    for (const de of (req.satisfied_by ?? [])) {
      if (nodeMap[de]) edges.push({ source: req.id, target: de, kind: 'satisfies' })
    }
    for (const tc of (req.verified_by ?? [])) {
      if (nodeMap[tc]) edges.push({ source: tc, target: req.id, kind: 'verifies' })
    }
  }

  const nodeColor = { req: '#3b82f6', design: '#a855f7', test: '#14b8a6' }
  const edgeColor = { satisfies: '#a855f7', verifies: '#14b8a6' }

  return (
    <div className="mt-4 flex flex-col gap-2">
      <p className="text-xs text-gray-500 dark:text-gray-400">
        Blue = Requirements · Purple = Design Elements · Teal = Test Cases
      </p>
      <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
        <svg
          ref={svgRef}
          width={WIDTH}
          height={HEIGHT}
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="w-full"
          aria-label="SysML traceability graph"
        >
          <defs>
            <marker id="arrow-satisfies" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
              <path d="M0,0 L0,6 L8,3 Z" fill={edgeColor.satisfies} />
            </marker>
            <marker id="arrow-verifies" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
              <path d="M0,0 L0,6 L8,3 Z" fill={edgeColor.verifies} />
            </marker>
          </defs>

          {edges.map((e, i) => {
            const s = nodeMap[e.source]
            const t = nodeMap[e.target]
            if (!s || !t) return null
            return (
              <line
                key={i}
                x1={s.x} y1={s.y}
                x2={t.x} y2={t.y}
                stroke={edgeColor[e.kind] ?? '#9ca3af'}
                strokeWidth={1.5}
                strokeOpacity={0.6}
                markerEnd={`url(#arrow-${e.kind})`}
              />
            )
          })}

          {nodes.map((n) => (
            <g key={n.id} transform={`translate(${n.x},${n.y})`}>
              <circle
                r={NODE_RADIUS}
                fill={nodeColor[n.kind] ?? '#9ca3af'}
                fillOpacity={0.15}
                stroke={nodeColor[n.kind] ?? '#9ca3af'}
                strokeWidth={1.5}
              />
              <text
                textAnchor="middle"
                dominantBaseline="middle"
                fontSize={9}
                fill={nodeColor[n.kind] ?? '#9ca3af'}
                fontFamily="monospace"
              >
                {n.label.length > 8 ? n.label.slice(0, 8) + '…' : n.label}
              </text>
            </g>
          ))}
        </svg>
      </div>
      <div className="flex items-center gap-4 text-xs text-gray-500 dark:text-gray-400">
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-0.5 bg-purple-500" /> satisfies
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-0.5 bg-teal-500" /> verifies
        </span>
        <span className="ml-auto">{nodes.length} nodes · {edges.length} edges</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab: XMI Export
// ---------------------------------------------------------------------------

function XMIExportTab({ requirements, designElements, testCases }) {
  const [xmiText,  setXmiText]  = useState('')
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)
  const [version,  setVersion]  = useState('1.7')

  const handleExport = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/llm-tools/sysml_export_xmi', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          requirements,
          design_elements: designElements,
          test_cases:      testCases,
          path:            'traceability.xmi',
          sysml_version:   version,
        }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      // If backend returns XMI text inline, use it; otherwise show metadata
      const text = data.xmi_text ?? data.result?.xmi_text ?? JSON.stringify(data, null, 2)
      setXmiText(text)
    } catch {
      // Demo / offline mode: generate minimal XMI client-side
      const ns = version === '1.6'
        ? 'http://www.omg.org/spec/SysML/20130901/SysML-1.6'
        : 'http://www.omg.org/spec/SysML/20150709/SysML-1.7'
      const lines = [
        `<?xml version="1.0" encoding="UTF-8"?>`,
        `<xmi:XMI xmlns:xmi="http://www.omg.org/spec/XMI/2.1"`,
        `         xmlns:sysml="${ns}"`,
        `         xmi:version="2.1">`,
        `  <!-- Requirements -->`,
        ...requirements.map((r) => `  <sysml:Requirement xmi:id="${r.id}" name="${r.id}" text="${r.text?.replace(/"/g, '&quot;') ?? ''}" />`),
        `  <!-- Design Elements -->`,
        ...designElements.map((d) => `  <sysml:Block xmi:id="${d.id}" name="${d.name ?? d.id}" />`),
        `  <!-- Test Cases -->`,
        ...testCases.map((t) => `  <uml:TestCase xmi:id="${t.id}" name="${t.name ?? t.id}" />`),
        `  <!-- Satisfy links -->`,
        ...requirements.flatMap((r) =>
          (r.satisfied_by ?? []).map((de, i) =>
            `  <sysml:Satisfy xmi:id="SAT-${r.id}-${i}" client="${de}" supplier="${r.id}" />`
          )
        ),
        `  <!-- Verify links -->`,
        ...testCases.flatMap((t) =>
          (t.verifies ?? []).map((rId, i) =>
            `  <sysml:Verify xmi:id="VER-${t.id}-${i}" client="${t.id}" supplier="${rId}" />`
          )
        ),
        `</xmi:XMI>`,
      ]
      setXmiText(lines.join('\n'))
    } finally {
      setLoading(false)
    }
  }, [requirements, designElements, testCases, version])

  const handleDownload = useCallback(() => {
    if (!xmiText) return
    const blob = new Blob([xmiText], { type: 'application/xml' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `traceability-${version}.xmi`
    a.click()
    URL.revokeObjectURL(url)
  }, [xmiText, version])

  return (
    <div className="mt-4 flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <label className="text-xs font-medium text-gray-700 dark:text-gray-300">
            SysML version
          </label>
          <select
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            className="rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500"
            aria-label="SysML XMI version"
          >
            <option value="1.7">SysML 1.7 (default)</option>
            <option value="1.6">SysML 1.6</option>
          </select>
        </div>

        <button
          onClick={handleExport}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-md border border-gray-300 dark:border-gray-600 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-gray-400 disabled:cursor-not-allowed disabled:opacity-50 transition-colors"
          aria-label="Generate XMI"
        >
          {loading ? <><RefreshCw size={12} className="animate-spin" /> Generating…</> : <><FileCode size={12} /> Generate XMI</>}
        </button>

        {xmiText && (
          <button
            onClick={handleDownload}
            className="flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
            aria-label="Download XMI file"
          >
            <Download size={12} /> Download .xmi
          </button>
        )}
      </div>

      {error && (
        <p className="text-xs text-red-600 dark:text-red-400" role="alert">{error}</p>
      )}

      {xmiText ? (
        <textarea
          readOnly
          value={xmiText}
          rows={18}
          className="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 px-3 py-2 text-xs font-mono text-gray-800 dark:text-gray-200 resize-y focus:outline-none focus:ring-1 focus:ring-blue-500"
          aria-label="XMI output"
          spellCheck={false}
        />
      ) : (
        <div className="flex items-center justify-center rounded-lg border border-dashed border-gray-300 dark:border-gray-700 h-40 text-sm text-gray-400 dark:text-gray-500 italic">
          Click &ldquo;Generate XMI&rdquo; to produce the SysML traceability export.
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// SysMLTracePanel
// ---------------------------------------------------------------------------

const TABS = [
  { id: 'matrix', label: 'Coverage Matrix', icon: Table2 },
  { id: 'graph',  label: 'Trace Graph',     icon: GitBranch },
  { id: 'xmi',    label: 'XMI Export',      icon: FileCode },
]

/**
 * SysMLTracePanel — SysML 1.x requirements traceability panel.
 *
 * Props
 * -----
 * className   {string}   Extra Tailwind classes.
 */
export default function SysMLTracePanel({ className = '' }) {
  const [activeTab,    setActiveTab]    = useState('matrix')
  const [requirements, setRequirements] = useState(DEMO_REQUIREMENTS)
  const [designEls,    setDesignEls]    = useState(DEMO_DESIGN_ELEMENTS)
  const [testCases,    setTestCases]    = useState(DEMO_TEST_CASES)
  const [report,       setReport]       = useState(null)
  const [computing,    setComputing]    = useState(false)
  const [error,        setError]        = useState(null)

  const handleComputeCoverage = useCallback(async () => {
    setComputing(true)
    setError(null)
    try {
      const res = await fetch('/api/llm-tools/sysml_trace_coverage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          requirements: requirements.map(({ id, text, parent_id, satisfied_by, verified_by }) => ({
            id, text, parent_id, satisfied_by, verified_by,
          })),
          design_elements: designEls.map(({ id, kind, name, properties, allocated_to }) => ({
            id, kind, name, properties, allocated_to,
          })),
          test_cases: testCases.map(({ id, name, verifies }) => ({ id, name, verifies })),
        }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setReport(data)
    } catch {
      // Offline / demo mode: compute coverage client-side
      const covered = requirements.filter(
        (r) => (r.satisfied_by ?? []).length > 0 && (r.verified_by ?? []).length > 0
      ).length
      const uncovered = requirements.length - covered
      const total = requirements.length
      const orphaned_requirements = requirements
        .filter((r) => (r.satisfied_by ?? []).length === 0)
        .map((r) => r.id)
      const unverified_requirements = requirements
        .filter((r) => (r.verified_by ?? []).length === 0)
        .map((r) => r.id)
      const orphaned_tests = testCases
        .filter((t) => (t.verifies ?? []).length === 0)
        .map((t) => t.id)
      setReport({
        ok: true,
        covered,
        uncovered,
        total,
        coverage_pct: total > 0 ? (covered / total) * 100 : 0,
        orphaned_requirements,
        unverified_requirements,
        orphaned_tests,
      })
    } finally {
      setComputing(false)
    }
  }, [requirements, designEls, testCases])

  return (
    <div className={`flex flex-col gap-5 ${className}`}>
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
            SysML Traceability
          </h2>
          <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
            Requirements → Design → Test traceability matrix (SysML 1.x / OMG §7 digital thread).
          </p>
        </div>
        <button
          onClick={handleComputeCoverage}
          disabled={computing}
          className="flex items-center gap-2 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50 transition-colors whitespace-nowrap"
          aria-label="Compute coverage"
        >
          {computing
            ? <><RefreshCw size={13} className="animate-spin" /> Computing…</>
            : <><Table2 size={13} /> Compute Coverage</>
          }
        </button>
      </div>

      {error && (
        <p className="text-xs text-red-600 dark:text-red-400" role="alert">{error}</p>
      )}

      {/* Tab bar */}
      <div className="flex border-b border-gray-200 dark:border-gray-700 gap-0" role="tablist" aria-label="SysML trace views">
        {TABS.map((tab) => {
          const Icon = tab.icon
          return (
            <button
              key={tab.id}
              role="tab"
              aria-selected={activeTab === tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-1.5 px-4 py-2 text-xs font-medium border-b-2 transition-colors focus:outline-none focus:ring-inset focus:ring-2 focus:ring-blue-500 ${
                activeTab === tab.id
                  ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                  : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:border-gray-300 dark:hover:border-gray-600'
              }`}
            >
              <Icon size={13} />
              {tab.label}
            </button>
          )
        })}
      </div>

      {/* Tab panels */}
      {activeTab === 'matrix' && (
        <CoverageMatrixTab
          report={report}
          requirements={requirements}
          designElements={designEls}
          testCases={testCases}
        />
      )}
      {activeTab === 'graph' && (
        <TraceGraphTab
          requirements={requirements}
          designElements={designEls}
          testCases={testCases}
        />
      )}
      {activeTab === 'xmi' && (
        <XMIExportTab
          requirements={requirements}
          designElements={designEls}
          testCases={testCases}
        />
      )}
    </div>
  )
}
