// ProductLifecyclePanel.jsx — PLM (Product Lifecycle) + Firmware (Embedded) panel.
//
// Wires 27 backend tools (14 PLM + 13 firmware) into a tabbed UI.
// Top tabs:  PLM (Lifecycle) | Firmware (Embedded)
// PLM sub-sections:   Change Mgmt | Part Numbering | Cost & Currency | BOM Analysis
// Firmware sub-sections:  Memory & Resources | Real-time & Safety | Hardware Verification | Protocol
//
// All tools dispatch POST /api/tools/call { tool, args }.
// Pattern follows ManufacturingPanel.jsx (data-driven ToolCard + Section).
//
// Route: /lifecycle  (also /plm-fw)

import { useState } from 'react'
import {
  ListTree, Tag, DollarSign, Cpu, Shield,
  GitBranch, Package, Activity, ChevronDown, ChevronRight,
  Play, Loader2, AlertTriangle, CheckCircle, Zap, Server,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

const API_URL = typeof import.meta !== 'undefined' && import.meta.env
  ? (import.meta.env.VITE_API_URL || '')
  : ''

async function callTool(toolName, args) {
  const res = await fetch(`${API_URL}/api/tools/call`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ tool: toolName, args }),
  })
  if (!res.ok) {
    const txt = await res.text().catch(() => res.statusText)
    throw new Error(`HTTP ${res.status}: ${txt}`)
  }
  const data = await res.json()
  if (typeof data.result === 'string') {
    try { return JSON.parse(data.result) } catch { return data.result }
  }
  return data
}

function num(v) { return v === '' || v == null ? undefined : Number(v) }
function int(v) { return v === '' || v == null ? undefined : parseInt(v, 10) }
function tryJSON(v, fallback) {
  if (!v) return fallback
  try { return JSON.parse(v) } catch { return v }
}

// ---------------------------------------------------------------------------
// Styles (dark mono palette — matches ManufacturingPanel)
// ---------------------------------------------------------------------------

const s = {
  root: {
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    fontSize: 13,
    color: '#e5e7eb',
    background: '#0d1117',
    minHeight: '100vh',
    padding: '24px 16px',
    display: 'flex',
    flexDirection: 'column',
    gap: 20,
  },
  pageHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    paddingBottom: 16,
    borderBottom: '1px solid #1f2937',
  },
  pageTitle: { fontSize: 18, fontWeight: 700, color: '#f3f4f6' },
  pageSub: { fontSize: 11, color: '#6b7280', marginTop: 2 },
  tabs: { display: 'flex', gap: 4, marginBottom: 4, flexWrap: 'wrap' },
  tab: {
    padding: '6px 16px',
    borderRadius: 5,
    border: '1px solid #374151',
    background: '#161b26',
    color: '#9ca3af',
    cursor: 'pointer',
    fontSize: 12,
    fontWeight: 500,
    display: 'flex',
    alignItems: 'center',
    gap: 5,
  },
  tabActive: {
    background: '#0e4f8f',
    borderColor: '#2563eb',
    color: '#fff',
  },
  section: {
    background: '#111827',
    borderRadius: 8,
    border: '1px solid #1f2937',
    overflow: 'hidden',
  },
  sectionHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '10px 14px',
    cursor: 'pointer',
    background: '#161b26',
    userSelect: 'none',
  },
  sectionTitle: {
    fontWeight: 600,
    fontSize: 12,
    color: '#f3f4f6',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    flex: 1,
  },
  sectionCount: { fontSize: 10, color: '#6b7280', fontWeight: 400 },
  cardGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))',
    gap: 12,
    padding: 12,
  },
  card: {
    background: '#0d1117',
    border: '1px solid #1f2937',
    borderRadius: 6,
    padding: 12,
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  cardHeader: { display: 'flex', alignItems: 'center', gap: 6 },
  cardTitle: { fontWeight: 600, fontSize: 12, color: '#f3f4f6', flex: 1 },
  cardDesc: { fontSize: 11, color: '#6b7280', lineHeight: 1.5 },
  fields: { display: 'flex', flexDirection: 'column', gap: 5 },
  row: { display: 'flex', alignItems: 'center', gap: 6 },
  label: { fontSize: 11, color: '#9ca3af', width: 120, flexShrink: 0 },
  input: {
    flex: 1,
    background: '#1f2937',
    border: '1px solid #374151',
    borderRadius: 4,
    color: '#e5e7eb',
    padding: '3px 6px',
    fontSize: 11,
    outline: 'none',
    fontFamily: 'inherit',
  },
  select: {
    flex: 1,
    background: '#1f2937',
    border: '1px solid #374151',
    borderRadius: 4,
    color: '#e5e7eb',
    padding: '3px 6px',
    fontSize: 11,
    outline: 'none',
    fontFamily: 'inherit',
  },
  runBtn: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 5,
    padding: '4px 10px',
    background: '#0e7490',
    border: 'none',
    borderRadius: 4,
    color: '#fff',
    fontSize: 11,
    fontWeight: 600,
    cursor: 'pointer',
    fontFamily: 'inherit',
    alignSelf: 'flex-start',
  },
  runBtnDisabled: { opacity: 0.45, cursor: 'not-allowed' },
  result: {
    background: '#0a0f1a',
    border: '1px solid #1f2937',
    borderRadius: 4,
    padding: '6px 8px',
    fontSize: 11,
    color: '#a3e635',
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-all',
    maxHeight: 200,
    overflowY: 'auto',
  },
  errorBox: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 5,
    background: '#1f0707',
    border: '1px solid #7f1d1d',
    borderRadius: 4,
    padding: '5px 8px',
    color: '#fca5a5',
    fontSize: 11,
  },
  successBadge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    fontSize: 10,
    fontWeight: 600,
    background: '#14532d22',
    border: '1px solid #16a34a55',
    color: '#4ade80',
    borderRadius: 9999,
    padding: '1px 7px',
  },
}

// ---------------------------------------------------------------------------
// ToolCard — generic data-driven tool card
// ---------------------------------------------------------------------------

function ToolCard({ name, icon: Icon, color, desc, fields, buildArgs }) {
  const [values, setValues] = useState(() =>
    Object.fromEntries(fields.map((f) => [f.key, f.default ?? '']))
  )
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  function set(key, val) { setValues((v) => ({ ...v, [key]: val })) }

  async function run() {
    setRunning(true); setResult(null); setError(null)
    try {
      const args = buildArgs ? buildArgs(values) : Object.fromEntries(
        fields.map((f) => [f.key, f.coerce ? f.coerce(values[f.key]) : values[f.key]])
      )
      setResult(await callTool(name, args))
    } catch (e) {
      setError(e.message)
    } finally {
      setRunning(false)
    }
  }

  return (
    <div style={s.card} data-testid={`tool-card-${name}`}>
      <div style={s.cardHeader}>
        {Icon && <Icon size={13} style={{ color: color || '#22d3ee', flexShrink: 0 }} />}
        <span style={s.cardTitle}>{name}</span>
        {result && !error && (
          <span style={s.successBadge}><CheckCircle size={9} /> done</span>
        )}
      </div>
      {desc && <div style={s.cardDesc}>{desc}</div>}

      {fields.length > 0 && (
        <div style={s.fields}>
          {fields.map((f) => (
            <div key={f.key} style={s.row}>
              <label style={s.label}>{f.label}</label>
              {f.type === 'select' ? (
                <select value={values[f.key]} onChange={(e) => set(f.key, e.target.value)}
                  style={s.select} disabled={running}>
                  {f.options.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              ) : f.type === 'textarea' ? (
                <textarea value={values[f.key]}
                  onChange={(e) => set(f.key, e.target.value)}
                  style={{ ...s.input, height: 52, resize: 'vertical' }}
                  disabled={running} placeholder={f.placeholder || ''} />
              ) : (
                <input type={f.type || 'text'} value={values[f.key]}
                  onChange={(e) => set(f.key, e.target.value)}
                  style={s.input} disabled={running}
                  placeholder={f.placeholder || ''} />
              )}
            </div>
          ))}
        </div>
      )}

      <button onClick={run} disabled={running}
        style={{ ...s.runBtn, ...(running ? s.runBtnDisabled : {}) }}>
        {running
          ? <><Loader2 size={11} style={{ animation: 'spin 1s linear infinite' }} /> Running…</>
          : <><Play size={11} /> Run</>}
      </button>

      {error && (
        <div style={s.errorBox} role="alert">
          <AlertTriangle size={11} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>{error}</span>
        </div>
      )}
      {result && !error && (
        <div style={s.result}>
          {typeof result === 'object' ? JSON.stringify(result, null, 2) : String(result)}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section — collapsible header + card grid
// ---------------------------------------------------------------------------

function Section({ title, icon: Icon, color, cards, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div style={s.section}>
      <div style={s.sectionHeader} onClick={() => setOpen((v) => !v)}>
        <Icon size={14} style={{ color }} />
        <span style={s.sectionTitle}>{title}</span>
        <span style={s.sectionCount}>{cards.length} tools</span>
        {open
          ? <ChevronDown size={13} style={{ color: '#6b7280' }} />
          : <ChevronRight size={13} style={{ color: '#6b7280' }} />}
      </div>
      {open && (
        <div style={s.cardGrid}>
          {cards.map((card) => <ToolCard key={card.name} {...card} />)}
        </div>
      )}
    </div>
  )
}

// ===========================================================================
// PLM TOOL DEFINITIONS
// ===========================================================================

// ── Section 1: Change Management ─────────────────────────────────────────────

const PLM_CHANGE_MGMT = [
  {
    name: 'plm_change_impact',
    icon: ListTree,
    color: '#f59e0b',
    desc: 'BFS-propagate a part change through BOM hierarchy to find impacted entities with rework hours (PROSTEP-iViP SIG).',
    fields: [
      { key: 'changed_part_id', label: 'Changed part ID', type: 'text', default: 'PART-001', placeholder: 'PART-001' },
      { key: 'plm_data', label: 'PLM data JSON', type: 'textarea',
        placeholder: '{"assemblies":[...],"parts":[...]}',
        default: '{"assemblies":[{"id":"ASM-001","name":"Top Assembly","children":[{"id":"PART-001","qty":2},{"id":"PART-002","qty":4}]},{"id":"ASM-002","name":"Sub Assembly","children":[{"id":"ASM-001","qty":1}]}],"parts":[{"id":"PART-001","name":"Bracket"},{"id":"PART-002","name":"Screw"}],"requirements":[{"id":"REQ-001","linked_part_ids":["PART-001"]}]}' },
      { key: 'hourly_rate', label: 'Hourly rate (USD)', type: 'number', default: '85' },
      { key: 'max_hops', label: 'Max hops', type: 'number', default: '5' },
    ],
    buildArgs: (v) => ({
      changed_part_id: v.changed_part_id,
      plm_data: tryJSON(v.plm_data, {}),
      ...(v.hourly_rate ? { hourly_rate: num(v.hourly_rate) } : {}),
      ...(v.max_hops ? { max_hops: int(v.max_hops) } : {}),
    }),
  },
  {
    name: 'plm_analyze_ecn_impact',
    icon: GitBranch,
    color: '#f59e0b',
    desc: 'ECN cascading impact: BFS upward through BOM, drawing + work-order counts, heuristic cost, ISO 10007 class assignment.',
    fields: [
      { key: 'ecn_id', label: 'ECN ID', type: 'text', default: 'ECN-2024-001', placeholder: 'ECN-2024-001' },
      { key: 'affected_part_numbers', label: 'Affected PNs JSON', type: 'textarea',
        placeholder: '["PN-001","PN-002"]', default: '["PN-BRKT-001","PN-SCREW-003"]' },
      { key: 'bom_hierarchy', label: 'BOM hierarchy JSON', type: 'textarea',
        placeholder: '[{"parent":"ASM-001","children":["PN-BRKT-001"]}]',
        default: '[{"parent":"ASM-001","children":["PN-BRKT-001","PN-SCREW-003"]},{"parent":"ASM-TOP","children":["ASM-001"]}]' },
      { key: 'urgency', label: 'Urgency', type: 'select', default: 'normal',
        options: [
          { value: 'emergency', label: 'Emergency' },
          { value: 'normal', label: 'Normal' },
          { value: 'deferred', label: 'Deferred' },
        ]},
      { key: 'cost_per_drawing_revision', label: 'Cost per drawing rev ($)', type: 'number', default: '250' },
    ],
    buildArgs: (v) => ({
      ecn_id: v.ecn_id,
      affected_part_numbers: tryJSON(v.affected_part_numbers, []),
      bom_hierarchy: tryJSON(v.bom_hierarchy, []),
      urgency: v.urgency,
      ...(v.cost_per_drawing_revision ? { cost_per_drawing_revision: num(v.cost_per_drawing_revision) } : {}),
    }),
  },
  {
    name: 'plm_compute_change_notification',
    icon: Activity,
    color: '#f59e0b',
    desc: 'ECO notification distribution: stakeholder list, ISO 10007 classification, APQP PPAP renewal triggers.',
    fields: [
      { key: 'eco_id', label: 'ECO ID', type: 'text', default: 'ECO-2024-042', placeholder: 'ECO-2024-042' },
      { key: 'eco_lines', label: 'ECO lines JSON', type: 'textarea',
        placeholder: '[{"part_number":"PN-001","from_rev":"A","to_rev":"B","change_type":"dimension","change_class":"class_b"}]',
        default: '[{"part_number":"PN-BRKT-001","from_rev":"A","to_rev":"B","change_type":"dimension","change_class":"class_b","description":"Slot width increased 0.5 mm"}]' },
      { key: 'effectivity_date', label: 'Effectivity date', type: 'text', default: '2024-09-01', placeholder: 'YYYY-MM-DD' },
    ],
    buildArgs: (v) => ({
      eco_id: v.eco_id,
      eco_lines: tryJSON(v.eco_lines, []),
      ...(v.effectivity_date ? { effectivity_date: v.effectivity_date } : {}),
    }),
  },
  {
    name: 'plm_where_used',
    icon: ListTree,
    color: '#f59e0b',
    desc: 'Where-Used: inverse BOM traversal — find every assembly consuming a part, with depth and multiplicity (PROSTEP-iViP SIG §5.2).',
    fields: [
      { key: 'target_part_id', label: 'Target part ID', type: 'text', default: 'PART-001', placeholder: 'PART-001' },
      { key: 'plm_data', label: 'PLM data JSON', type: 'textarea',
        placeholder: '{"assemblies":[...]}',
        default: '{"assemblies":[{"id":"ASM-001","name":"Bracket Assy","children":[{"id":"PART-001","qty":2}]},{"id":"ASM-TOP","name":"Top Level","children":[{"id":"ASM-001","qty":1},{"id":"PART-001","qty":1}]}]}' },
    ],
    buildArgs: (v) => ({
      target_part_id: v.target_part_id,
      plm_data: tryJSON(v.plm_data, {}),
    }),
  },
  {
    name: 'plm_compare_boms',
    icon: GitBranch,
    color: '#f59e0b',
    desc: 'Flat BOM diff: added / removed / qty-changed / unchanged lines (ISO 10303-44 §6).',
    fields: [
      { key: 'old_bom', label: 'Old BOM JSON', type: 'textarea',
        placeholder: '[{"part_number":"PN-001","qty":2}]',
        default: '[{"part_number":"PN-001","qty":2,"description":"Bracket"},{"part_number":"PN-002","qty":8,"description":"M3 Screw"}]' },
      { key: 'new_bom', label: 'New BOM JSON', type: 'textarea',
        placeholder: '[{"part_number":"PN-001","qty":3}]',
        default: '[{"part_number":"PN-001","qty":2,"description":"Bracket"},{"part_number":"PN-002","qty":6,"description":"M3 Screw"},{"part_number":"PN-003","qty":2,"description":"Washer"}]' },
    ],
    buildArgs: (v) => ({
      old_bom: tryJSON(v.old_bom, []),
      new_bom: tryJSON(v.new_bom, []),
    }),
  },
  {
    name: 'plm_document_version_diff',
    icon: GitBranch,
    color: '#f59e0b',
    desc: 'Field-level diff of two PLM document revisions with engineering vs administrative criticality (ISO 10303-44 §5.2).',
    fields: [
      { key: 'doc_a', label: 'Doc A (rev) JSON', type: 'textarea',
        placeholder: '[{"id":"P-001","qty":2,"material":"Al"}]',
        default: '[{"id":"P-001","qty":2,"material":"Al","tolerance":"±0.1"},{"id":"P-002","qty":4,"material":"Steel"}]' },
      { key: 'doc_b', label: 'Doc B (rev) JSON', type: 'textarea',
        placeholder: '[{"id":"P-001","qty":2,"material":"Ti"}]',
        default: '[{"id":"P-001","qty":2,"material":"Ti","tolerance":"±0.05"},{"id":"P-003","qty":2,"material":"Al"}]' },
      { key: 'id_field', label: 'ID field', type: 'text', default: 'id', placeholder: 'id' },
    ],
    buildArgs: (v) => ({
      doc_a: tryJSON(v.doc_a, []),
      doc_b: tryJSON(v.doc_b, []),
      ...(v.id_field ? { id_field: v.id_field } : {}),
    }),
  },
]

// ── Section 2: Part Numbering ──────────────────────────────────────────────

const PLM_PART_NUMBERING = [
  {
    name: 'plm_validate_part_number',
    icon: Tag,
    color: '#22d3ee',
    desc: 'Syntax-validate a part number against a schema (sequential, hierarchical, semantic, hash, custom) — GS1 GTIN §2.1 + ISO 8000-110 §6.5.',
    fields: [
      { key: 'part_number', label: 'Part number', type: 'text', default: 'PN-ABC-DEF-00123', placeholder: 'PN-001' },
      { key: 'schema_type', label: 'Schema type', type: 'select', default: 'hierarchical',
        options: [
          { value: 'sequential', label: 'Sequential' },
          { value: 'hierarchical', label: 'Hierarchical' },
          { value: 'semantic', label: 'Semantic' },
          { value: 'hash_based', label: 'Hash-based' },
          { value: 'custom', label: 'Custom regex' },
        ]},
      { key: 'prefix', label: 'Prefix', type: 'text', default: 'PN', placeholder: 'PN' },
      { key: 'custom_pattern', label: 'Custom pattern', type: 'text', default: '', placeholder: 'Only for custom schema' },
    ],
    buildArgs: (v) => ({
      part_number: v.part_number,
      schema_type: v.schema_type,
      ...(v.prefix ? { prefix: v.prefix } : {}),
      ...(v.custom_pattern && v.schema_type === 'custom' ? { custom_pattern: v.custom_pattern } : {}),
    }),
  },
  {
    name: 'plm_allocate_part_number',
    icon: Tag,
    color: '#22d3ee',
    desc: 'Mint the next available part number for a schema. Pass state_json to maintain uniqueness across calls.',
    fields: [
      { key: 'schema_type', label: 'Schema type', type: 'select', default: 'sequential',
        options: [
          { value: 'sequential', label: 'Sequential' },
          { value: 'hierarchical', label: 'Hierarchical' },
          { value: 'hash_based', label: 'Hash-based' },
        ]},
      { key: 'prefix', label: 'Prefix', type: 'text', default: 'PN', placeholder: 'PN' },
      { key: 'family_key', label: 'Family key (opt)', type: 'text', default: '', placeholder: 'component' },
      { key: 'state_json', label: 'State JSON (opt)', type: 'textarea',
        placeholder: '{}', default: '{}' },
    ],
    buildArgs: (v) => ({
      schema_type: v.schema_type,
      ...(v.prefix ? { prefix: v.prefix } : {}),
      ...(v.family_key ? { family_key: v.family_key } : {}),
      state_json: tryJSON(v.state_json, {}),
    }),
  },
  {
    name: 'plm_check_part_obsolescence',
    icon: Package,
    color: '#22d3ee',
    desc: 'IEC 62402 + DMSMS obsolescence check: risk score, EOL/NRND/LTB flags, affected assemblies.',
    fields: [
      { key: 'parts', label: 'Parts JSON', type: 'textarea',
        placeholder: '[{"part_number":"PN-001","manufacturer":"TI","status":"active"}]',
        default: '[{"part_number":"PN-IC-001","manufacturer":"Texas Instruments","status":"EOL","last_buy_date":"2024-12-31","alternative_pn":"PN-IC-002"},{"part_number":"PN-IC-002","manufacturer":"Texas Instruments","status":"active"},{"part_number":"PN-RES-010","manufacturer":"Vishay","status":"NRND"}]' },
      { key: 'bom_relationships', label: 'BOM relationships JSON', type: 'textarea',
        placeholder: '[{"assembly":"ASM-001","component":"PN-001"}]',
        default: '[{"assembly":"BOARD-REV-A","component":"PN-IC-001"},{"assembly":"BOARD-REV-A","component":"PN-RES-010"}]' },
    ],
    buildArgs: (v) => ({
      parts: tryJSON(v.parts, []),
      bom_relationships: tryJSON(v.bom_relationships, []),
    }),
  },
]

// ── Section 3: Cost & Currency ─────────────────────────────────────────────

const PLM_COST = [
  {
    name: 'plm_rollup_bom_cost',
    icon: DollarSign,
    color: '#4ade80',
    desc: 'Recursive BOM cost rollup: rolled_cost(node) = internal_cost + Σ(qty × child_cost). FX-rate conversion. ISO 10303-44 §5.3.',
    fields: [
      { key: 'bom_tree', label: 'BOM tree JSON', type: 'textarea',
        placeholder: '{"part_number":"TOP","name":"Assembly","unit_cost":0,"currency":"USD","children":[...]}',
        default: '{"part_number":"ASM-TOP","name":"Robot Arm","unit_cost":50,"currency":"USD","children":[{"part_number":"PN-SERVO","name":"Servo Motor","unit_cost":35,"currency":"USD","qty":3,"children":[]},{"part_number":"PN-CTRL","name":"Controller PCB","unit_cost":80,"currency":"EUR","qty":1,"children":[]}]}' },
      { key: 'currency', label: 'Target currency', type: 'select', default: 'USD',
        options: [
          { value: 'USD', label: 'USD' },
          { value: 'EUR', label: 'EUR' },
          { value: 'GBP', label: 'GBP' },
          { value: 'ZAR', label: 'ZAR' },
        ]},
      { key: 'fx_rates', label: 'FX rates JSON', type: 'textarea',
        placeholder: '{"EUR":1.08,"GBP":1.27}',
        default: '{"EUR":1.08,"GBP":1.27,"ZAR":0.055}' },
    ],
    buildArgs: (v) => ({
      bom_tree: tryJSON(v.bom_tree, {}),
      currency: v.currency,
      fx_rates: tryJSON(v.fx_rates, {}),
    }),
  },
  {
    name: 'plm_rollup_cost_multi_currency',
    icon: DollarSign,
    color: '#4ade80',
    desc: 'Flat BOM cost rollup with per-line ISO 4217 currency. Missing FX flagged, not raised. ISO 4217:2015.',
    fields: [
      { key: 'entries', label: 'BOM entries JSON', type: 'textarea',
        placeholder: '[{"part_number":"PN-001","unit_cost":10,"qty":4,"currency":"USD"}]',
        default: '[{"part_number":"PN-001","unit_cost":10,"qty":4,"currency":"USD"},{"part_number":"PN-002","unit_cost":8,"qty":2,"currency":"EUR"},{"part_number":"PN-003","unit_cost":500,"qty":1,"currency":"ZAR"}]' },
      { key: 'target_currency', label: 'Target currency', type: 'select', default: 'USD',
        options: [
          { value: 'USD', label: 'USD' },
          { value: 'EUR', label: 'EUR' },
          { value: 'GBP', label: 'GBP' },
          { value: 'ZAR', label: 'ZAR' },
        ]},
      { key: 'fx_rates', label: 'FX rates JSON', type: 'textarea',
        placeholder: '{"EUR":1.08,"ZAR":0.055}',
        default: '{"EUR":1.08,"GBP":1.27,"ZAR":0.055}' },
    ],
    buildArgs: (v) => ({
      entries: tryJSON(v.entries, []),
      target_currency: v.target_currency,
      fx_rates: tryJSON(v.fx_rates, {}),
    }),
  },
]

// ── Section 4: BOM Analysis ────────────────────────────────────────────────

const PLM_BOM = [
  {
    name: 'plm_expand_effectivity_bom',
    icon: ListTree,
    color: '#a78bfa',
    desc: 'Expand 150% BOM to 100% BOM for a date/configuration/serial context (ISO 10303-44 + Borst-Lahti §7.4).',
    fields: [
      { key: 'bom_150pct', label: '150% BOM JSON', type: 'textarea',
        placeholder: '[{"part_number":"PN-001","qty":2,"effective_from":"2023-01-01","effective_to":null}]',
        default: '[{"part_number":"PN-STD","qty":2,"effective_from":"2023-01-01","effective_to":null},{"part_number":"PN-COLD","qty":2,"effective_from":"2024-01-01","effective_to":null,"option_requirements":{"climate":"arctic"}},{"part_number":"PN-CTRL-V2","qty":1,"effective_from":"2024-06-01","effective_to":null}]' },
      { key: 'effectivity_date', label: 'Effectivity date', type: 'text', default: '2024-09-15', placeholder: 'YYYY-MM-DD' },
      { key: 'options', label: 'Options JSON', type: 'text', default: '{}', placeholder: '{"climate":"arctic"}' },
    ],
    buildArgs: (v) => ({
      bom_150pct: tryJSON(v.bom_150pct, []),
      context: {
        date: v.effectivity_date || undefined,
        options: tryJSON(v.options, {}),
      },
    }),
  },
  {
    name: 'plm_assess_bom_maturity',
    icon: Package,
    color: '#a78bfa',
    desc: 'BOM maturity gate check: completeness, all parts released, no open ECOs, cost thresholds.',
    fields: [
      { key: 'bom', label: 'BOM JSON', type: 'textarea',
        placeholder: '[{"part_number":"PN-001","released":true,"unit_cost":10,"currency":"USD","qty":2}]',
        default: '[{"part_number":"PN-001","released":true,"unit_cost":10,"currency":"USD","qty":2},{"part_number":"PN-002","released":false,"unit_cost":5,"currency":"USD","qty":4},{"part_number":"PN-003","released":true,"unit_cost":80,"currency":"USD","qty":1}]' },
      { key: 'target_currency', label: 'Target currency', type: 'select', default: 'USD',
        options: [{ value: 'USD', label: 'USD' }, { value: 'EUR', label: 'EUR' }] },
      { key: 'fx_rates', label: 'FX rates JSON', type: 'text', default: '{}', placeholder: '{"EUR":1.08}' },
    ],
    buildArgs: (v) => ({
      bom: tryJSON(v.bom, []),
      target_currency: v.target_currency,
      fx_rates: tryJSON(v.fx_rates, {}),
    }),
  },
]

// ===========================================================================
// FIRMWARE TOOL DEFINITIONS
// ===========================================================================

// ── Section 1: Memory & Resources ─────────────────────────────────────────

const FW_MEMORY = [
  {
    name: 'firmware_analyze_const_allocation',
    icon: Server,
    color: '#f59e0b',
    desc: 'Flash (.rodata/.text) vs RAM (.data) const-allocation analyser. Finds ALL_CAPS arrays misplaced in RAM (GCC §18 + RM0383 §3).',
    fields: [
      { key: 'symbols', label: 'Symbols JSON', type: 'textarea',
        placeholder: '[{"name":"LOOKUP_TABLE","section":".data","size_bytes":512}]',
        default: '[{"name":"CRC_TABLE","section":".rodata","size_bytes":1024},{"name":"LOOKUP_TABLE","section":".data","size_bytes":512},{"name":"g_state","section":".bss","size_bytes":64},{"name":"main","section":".text","size_bytes":2048},{"name":"MAX_SPEED","section":".data","size_bytes":4}]' },
      { key: 'total_flash_bytes', label: 'Total Flash (B)', type: 'number', default: '524288' },
      { key: 'total_ram_bytes', label: 'Total RAM (B)', type: 'number', default: '131072' },
    ],
    buildArgs: (v) => ({
      symbols: tryJSON(v.symbols, []),
      ...(v.total_flash_bytes ? { total_flash_bytes: int(v.total_flash_bytes) } : {}),
      ...(v.total_ram_bytes ? { total_ram_bytes: int(v.total_ram_bytes) } : {}),
    }),
  },
  {
    name: 'firmware_audit_ram_usage',
    icon: Server,
    color: '#f59e0b',
    desc: 'MCU RAM utilisation audit: static + dynamic sections, 80% budget guard (RM0383 §2 + ATmega328P §8).',
    fields: [
      { key: 'mcu_label', label: 'MCU label', type: 'text', default: 'STM32F411', placeholder: 'STM32F411' },
      { key: 'total_ram_bytes', label: 'Total RAM (B)', type: 'number', default: '131072' },
      { key: 'data_bytes', label: '.data (B)', type: 'number', default: '8192' },
      { key: 'bss_bytes', label: '.bss (B)', type: 'number', default: '16384' },
      { key: 'heap_max_bytes', label: 'Heap max (B)', type: 'number', default: '24576' },
      { key: 'stack_max_bytes', label: 'Stack max (B)', type: 'number', default: '8192' },
    ],
    buildArgs: (v) => ({
      mcu_label: v.mcu_label,
      total_ram_bytes: int(v.total_ram_bytes),
      data_bytes: int(v.data_bytes),
      bss_bytes: int(v.bss_bytes),
      heap_max_bytes: int(v.heap_max_bytes),
      stack_max_bytes: int(v.stack_max_bytes),
    }),
  },
  {
    name: 'firmware_estimate_stack_depth',
    icon: Server,
    color: '#f59e0b',
    desc: 'DFS worst-case stack depth estimator: call graph + frame sizes + ISR preemption (ARM AAPCS IHI0042F §5.2).',
    fields: [
      { key: 'functions', label: 'Functions JSON', type: 'textarea',
        placeholder: '[{"function_name":"main","frame_size_bytes":100,"callees":["task_a"]}]',
        default: '[{"function_name":"main","frame_size_bytes":100,"callees":["task_a","task_b"]},{"function_name":"task_a","frame_size_bytes":200,"callees":["helper"]},{"function_name":"task_b","frame_size_bytes":80,"callees":[]},{"function_name":"helper","frame_size_bytes":50,"callees":[]}]' },
      { key: 'entry_function_name', label: 'Entry function', type: 'text', default: 'main', placeholder: 'main' },
      { key: 'isr_overhead_bytes', label: 'ISR overhead (B)', type: 'number', default: '32' },
    ],
    buildArgs: (v) => ({
      functions: tryJSON(v.functions, []),
      entry_function_name: v.entry_function_name,
      ...(v.isr_overhead_bytes ? { isr_overhead_bytes: int(v.isr_overhead_bytes) } : {}),
    }),
  },
  {
    name: 'firmware_compute_adc_enob',
    icon: Zap,
    color: '#f59e0b',
    desc: 'ADC ENOB from SINAD + oversampling gain (ADI MT-003 + TI SBAA221). Recommends OSR for target bits.',
    fields: [
      { key: 'nominal_bits', label: 'Nominal bits', type: 'number', default: '12' },
      { key: 'sampling_rate_Hz', label: 'Sampling rate (Hz)', type: 'number', default: '1000000' },
      { key: 'reference_voltage_V', label: 'Vref (V)', type: 'number', default: '3.3' },
      { key: 'signal_full_scale_V', label: 'Full scale (V)', type: 'number', default: '3.3' },
      { key: 'sinad_dB', label: 'SINAD (dB, opt)', type: 'number', default: '68' },
      { key: 'oversampling_ratio', label: 'OSR (opt)', type: 'number', default: '16' },
      { key: 'target_enob', label: 'Target ENOB (opt)', type: 'number', default: '14' },
    ],
    buildArgs: (v) => ({
      nominal_bits: int(v.nominal_bits),
      sampling_rate_Hz: num(v.sampling_rate_Hz),
      reference_voltage_V: num(v.reference_voltage_V),
      signal_full_scale_V: num(v.signal_full_scale_V),
      ...(v.sinad_dB ? { sinad_dB: num(v.sinad_dB) } : {}),
      ...(v.oversampling_ratio ? { oversampling: { oversampling_ratio: int(v.oversampling_ratio) } } : {}),
      ...(v.target_enob ? { target_enob: num(v.target_enob) } : {}),
    }),
  },
]

// ── Section 2: Real-time & Safety ──────────────────────────────────────────

const FW_REALTIME = [
  {
    name: 'firmware_check_watchdog',
    icon: Shield,
    color: '#ef4444',
    desc: 'Watchdog kick-gap verifier: max_gap = slowest_kicker.period + blocker WCET vs timeout (IEC 61508 §7.4.3.7 + RM0383 §19).',
    fields: [
      { key: 'tasks', label: 'Tasks JSON', type: 'textarea',
        placeholder: '[{"name":"ctrl","period_ms":100,"wcet_ms":10,"priority":1,"kicks_watchdog":true}]',
        default: '[{"name":"ctrl_loop","period_ms":100,"wcet_ms":10,"priority":2,"kicks_watchdog":true},{"name":"telemetry","period_ms":500,"wcet_ms":30,"priority":1,"kicks_watchdog":false}]' },
      { key: 'wdg_type', label: 'Watchdog type', type: 'select', default: 'IWDG',
        options: [{ value: 'IWDG', label: 'IWDG (STM32)' }, { value: 'WWDG', label: 'WWDG (window)' }] },
      { key: 'wdg_timeout_ms', label: 'Timeout (ms)', type: 'number', default: '250' },
      { key: 'wdg_window_min_ms', label: 'Window min (ms, WWDG)', type: 'number', default: '' },
    ],
    buildArgs: (v) => ({
      tasks: tryJSON(v.tasks, []),
      wdg: {
        type: v.wdg_type,
        timeout_ms: num(v.wdg_timeout_ms),
        ...(v.wdg_window_min_ms ? { window_min_ms: num(v.wdg_window_min_ms) } : {}),
      },
    }),
  },
  {
    name: 'firmware_check_watchdog_interval',
    icon: Shield,
    color: '#ef4444',
    desc: 'MCU watchdog timeout computation: timeout = prescaler × (reload+1) / clock. 2× margin check (ARM Keil AN259).',
    fields: [
      { key: 'mcu_label', label: 'MCU label', type: 'text', default: 'STM32F411', placeholder: 'STM32F411' },
      { key: 'clock_hz', label: 'Clock (Hz)', type: 'number', default: '32000' },
      { key: 'prescaler', label: 'Prescaler', type: 'number', default: '64' },
      { key: 'reload_value', label: 'Reload value', type: 'number', default: '4095' },
      { key: 'worst_case_ms', label: 'Worst-case loop (ms)', type: 'number', default: '4000' },
    ],
    buildArgs: (v) => ({
      config: {
        clock_hz: int(v.clock_hz),
        prescaler: int(v.prescaler),
        reload_value: int(v.reload_value),
        mcu_label: v.mcu_label,
      },
      latency: {
        worst_case_ms: num(v.worst_case_ms),
      },
    }),
  },
  {
    name: 'firmware_check_pwm_resolution',
    icon: Zap,
    color: '#ef4444',
    desc: 'MCU PWM resolution analyser: best (P, ARR) for max bits with |freq_error| < 1% (RM0383 §13 + ATmega328P §15).',
    fields: [
      { key: 'mcu_clock_hz', label: 'MCU clock (Hz)', type: 'number', default: '16000000' },
      { key: 'target_pwm_freq_Hz', label: 'PWM freq (Hz)', type: 'number', default: '1000' },
      { key: 'counter_bits', label: 'Counter bits', type: 'select', default: '16',
        options: [
          { value: '8', label: '8-bit' },
          { value: '10', label: '10-bit' },
          { value: '16', label: '16-bit' },
          { value: '32', label: '32-bit' },
        ]},
    ],
    buildArgs: (v) => ({
      mcu_clock_hz: int(v.mcu_clock_hz),
      target_pwm_freq_Hz: num(v.target_pwm_freq_Hz),
      counter_bits: int(v.counter_bits),
    }),
  },
  {
    name: 'firmware_check_rtos_priorities',
    icon: Shield,
    color: '#ef4444',
    desc: 'Liu-Layland rate-monotonic schedulability: U ≤ n·(2^(1/n)−1), Bini-Buttazzo hyperbolic bound, RM priority check.',
    fields: [
      { key: 'tasks', label: 'Tasks JSON', type: 'textarea',
        placeholder: '[{"name":"T1","period_ms":10,"wcet_ms":3,"priority":2}]',
        default: '[{"name":"motor_ctrl","period_ms":5,"wcet_ms":1.5,"priority":3},{"name":"sensor_read","period_ms":10,"wcet_ms":2,"priority":2},{"name":"telemetry","period_ms":50,"wcet_ms":8,"priority":1}]' },
      { key: 'rtos', label: 'RTOS', type: 'select', default: 'FreeRTOS',
        options: [
          { value: 'FreeRTOS', label: 'FreeRTOS' },
          { value: 'Zephyr', label: 'Zephyr' },
          { value: 'ChibiOS', label: 'ChibiOS' },
        ]},
    ],
    buildArgs: (v) => ({
      tasks: tryJSON(v.tasks, []),
      rtos: v.rtos,
    }),
  },
]

// ── Section 3: Hardware Verification ──────────────────────────────────────

const FW_HW_VERIFY = [
  {
    name: 'firmware_verify_clock_tree',
    icon: Cpu,
    color: '#22d3ee',
    desc: 'STM32 clock-tree verifier: PLL arithmetic, SYSCLK/APB/USB/ADC limits (RM0383 §6 + RM0090 §6).',
    fields: [
      { key: 'chip', label: 'Chip', type: 'select', default: 'STM32F411',
        options: [
          { value: 'STM32F411', label: 'STM32F411' },
          { value: 'STM32F407', label: 'STM32F407' },
        ]},
      { key: 'source', label: 'Clock source', type: 'select', default: 'HSE',
        options: [
          { value: 'HSE', label: 'HSE (crystal)' },
          { value: 'HSE_BYPASS', label: 'HSE_BYPASS (ext clk)' },
          { value: 'HSI', label: 'HSI (internal 16 MHz)' },
        ]},
      { key: 'hse_hz', label: 'HSE freq (Hz)', type: 'number', default: '8000000' },
      { key: 'PLLM', label: 'PLLM', type: 'number', default: '8' },
      { key: 'PLLN', label: 'PLLN', type: 'number', default: '100' },
      { key: 'PLLP', label: 'PLLP', type: 'select', default: '2',
        options: [{ value: '2', label: '2' }, { value: '4', label: '4' }, { value: '6', label: '6' }, { value: '8', label: '8' }] },
      { key: 'PLLQ', label: 'PLLQ (USB)', type: 'number', default: '4' },
      { key: 'AHB_div', label: 'AHB div', type: 'number', default: '1' },
      { key: 'APB1_div', label: 'APB1 div', type: 'number', default: '2' },
      { key: 'APB2_div', label: 'APB2 div', type: 'number', default: '1' },
    ],
    buildArgs: (v) => ({
      chip: v.chip,
      config: {
        source: v.source,
        ...(v.hse_hz ? { hse_hz: int(v.hse_hz) } : {}),
        PLLM: int(v.PLLM),
        PLLN: int(v.PLLN),
        PLLP: int(v.PLLP),
        PLLQ: int(v.PLLQ),
        AHB_div: int(v.AHB_div),
        APB1_div: int(v.APB1_div),
        APB2_div: int(v.APB2_div),
      },
    }),
  },
  {
    name: 'firmware_verify_spi_timing',
    icon: Cpu,
    color: '#22d3ee',
    desc: 'SPI master/slave timing compatibility: clock rate, setup/hold times, CPOL/CPHA mode (Motorola SPI spec).',
    fields: [
      { key: 'master_clock_hz', label: 'Master clock (Hz)', type: 'number', default: '1000000' },
      { key: 'master_cpol', label: 'CPOL', type: 'select', default: '0',
        options: [{ value: '0', label: '0 (idle LOW)' }, { value: '1', label: '1 (idle HIGH)' }] },
      { key: 'master_cpha', label: 'CPHA', type: 'select', default: '0',
        options: [{ value: '0', label: '0 (sample rising)' }, { value: '1', label: '1 (sample falling)' }] },
      { key: 'master_setup_ns', label: 'Setup (ns)', type: 'number', default: '10' },
      { key: 'master_hold_ns', label: 'Hold (ns)', type: 'number', default: '10' },
      { key: 'master_label', label: 'Master label', type: 'text', default: 'STM32F411 SPI1' },
      { key: 'slave_max_clk_hz', label: 'Slave max clk (Hz)', type: 'number', default: '1350000' },
      { key: 'slave_min_setup_ns', label: 'Slave setup (ns)', type: 'number', default: '50' },
      { key: 'slave_min_hold_ns', label: 'Slave hold (ns)', type: 'number', default: '50' },
      { key: 'slave_cpol', label: 'Slave CPOL', type: 'select', default: '0',
        options: [{ value: '0', label: '0' }, { value: '1', label: '1' }] },
      { key: 'slave_cpha', label: 'Slave CPHA', type: 'select', default: '0',
        options: [{ value: '0', label: '0' }, { value: '1', label: '1' }] },
      { key: 'slave_label', label: 'Slave label', type: 'text', default: 'MCP3008 ADC' },
    ],
    buildArgs: (v) => ({
      master: {
        clock_hz: int(v.master_clock_hz),
        cpol: int(v.master_cpol),
        cpha: int(v.master_cpha),
        setup_ns: num(v.master_setup_ns),
        hold_ns: num(v.master_hold_ns),
        mcu_label: v.master_label,
      },
      slave: {
        max_clk_hz: int(v.slave_max_clk_hz),
        min_setup_ns: num(v.slave_min_setup_ns),
        min_hold_ns: num(v.slave_min_hold_ns),
        cpol_required: int(v.slave_cpol),
        cpha_required: int(v.slave_cpha),
        device_label: v.slave_label,
      },
    }),
  },
  {
    name: 'firmware_check_i2c_clock_stretch',
    icon: Cpu,
    color: '#22d3ee',
    desc: 'I²C clock-stretch analysis: worst-case effective speed and SCL timeout compliance (NXP UM10204 §3.1.9).',
    fields: [
      { key: 'nominal_clock_hz', label: 'I2C clock (Hz)', type: 'number', default: '400000' },
      { key: 'scl_timeout_ms', label: 'SCL timeout (ms)', type: 'number', default: '25' },
      { key: 'mcu_label', label: 'MCU label', type: 'text', default: 'STM32F411' },
      { key: 'slaves', label: 'Slaves JSON', type: 'textarea',
        placeholder: '[{"device_label":"SHT31","address_hex":"0x44","max_stretch_per_byte_us":50,"bytes_per_transaction":6}]',
        default: '[{"device_label":"SHT31","address_hex":"0x44","max_stretch_per_byte_us":50,"bytes_per_transaction":6},{"device_label":"EEPROM","address_hex":"0x50","max_stretch_per_byte_us":5,"bytes_per_transaction":32}]' },
    ],
    buildArgs: (v) => ({
      master: {
        nominal_clock_hz: int(v.nominal_clock_hz),
        scl_low_timeout_ms: num(v.scl_timeout_ms),
        mcu_label: v.mcu_label,
      },
      slaves: tryJSON(v.slaves, []),
    }),
  },
]

// ── Section 4: Protocol & Communication ────────────────────────────────────

const FW_PROTOCOL = [
  {
    name: 'firmware_check_uart_baud_drift',
    icon: Activity,
    color: '#a78bfa',
    desc: 'UART baud-rate drift: actual = clock/(16×(UBRR+1)). Flags |drift| ≥ 2% (IEEE Std 488). Recommends best UBRR combos.',
    fields: [
      { key: 'mcu_clock_hz', label: 'MCU clock (Hz)', type: 'number', default: '16000000' },
      { key: 'ubrr_register_value', label: 'UBRR value', type: 'number', default: '103' },
      { key: 'target_baud', label: 'Target baud', type: 'number', default: '9600' },
      { key: 'double_speed', label: 'Double speed (U2X)', type: 'select', default: 'false',
        options: [{ value: 'false', label: 'Normal mode' }, { value: 'true', label: 'U2X (double speed)' }] },
    ],
    buildArgs: (v) => ({
      mcu_clock_hz: int(v.mcu_clock_hz),
      ubrr_register_value: int(v.ubrr_register_value),
      target_baud: int(v.target_baud),
      double_speed: v.double_speed === 'true',
    }),
  },
  {
    name: 'firmware_compute_can_bus_load',
    icon: Activity,
    color: '#a78bfa',
    desc: 'CAN bus utilisation: Σ(frames/s × bits/frame) / bit_rate. J1939-21 40% + ISO 26262 30% thresholds.',
    fields: [
      { key: 'messages', label: 'Messages JSON', type: 'textarea',
        placeholder: '[{"name":"ENGINE_SPEED","can_id":100,"data_bytes":8,"period_ms":10}]',
        default: '[{"name":"ENGINE_SPEED","can_id":100,"data_bytes":8,"period_ms":10},{"name":"THROTTLE","can_id":200,"data_bytes":4,"period_ms":20},{"name":"STATUS","can_id":300,"data_bytes":2,"period_ms":100}]' },
      { key: 'bit_rate_bps', label: 'Bit rate (bps)', type: 'number', default: '500000' },
    ],
    buildArgs: (v) => ({
      messages: tryJSON(v.messages, []),
      bit_rate_bps: int(v.bit_rate_bps),
    }),
  },
  {
    name: 'firmware_compute_crc',
    icon: Shield,
    color: '#a78bfa',
    desc: 'CRC checksum: CRC-8, CRC-16/CCITT, CRC-16/MODBUS, CRC-32, CRC-32C from hex payload (IEEE 802.3 + RFC 3720).',
    fields: [
      { key: 'data_hex', label: 'Data (hex)', type: 'text', default: '313233343536373839', placeholder: '31 32 33 ...' },
      { key: 'algorithm', label: 'Algorithm', type: 'select', default: 'CRC-32',
        options: [
          { value: 'CRC-8', label: 'CRC-8' },
          { value: 'CRC-16/CCITT', label: 'CRC-16/CCITT' },
          { value: 'CRC-16/MODBUS', label: 'CRC-16/MODBUS' },
          { value: 'CRC-32', label: 'CRC-32 (IEEE 802.3)' },
          { value: 'CRC-32C', label: 'CRC-32C/Castagnoli' },
        ]},
    ],
    buildArgs: (v) => ({
      data_hex: v.data_hex,
      algorithm: v.algorithm,
    }),
  },
]

// ===========================================================================
// Top-level panel component
// ===========================================================================

const PLM_TOOL_COUNT = PLM_CHANGE_MGMT.length + PLM_PART_NUMBERING.length + PLM_COST.length + PLM_BOM.length
const FW_TOOL_COUNT = FW_MEMORY.length + FW_REALTIME.length + FW_HW_VERIFY.length + FW_PROTOCOL.length

export default function ProductLifecyclePanel() {
  const [tab, setTab] = useState('plm')

  const tabs = [
    { id: 'plm', label: `PLM (Lifecycle)`, icon: ListTree, count: PLM_TOOL_COUNT },
    { id: 'firmware', label: `Firmware (Embedded)`, icon: Cpu, count: FW_TOOL_COUNT },
  ]

  return (
    <div style={s.root}>
      {/* Page header */}
      <div style={s.pageHeader}>
        <ListTree size={20} style={{ color: '#38bdf8' }} />
        <div>
          <div style={s.pageTitle}>Product Lifecycle &amp; Firmware</div>
          <div style={s.pageSub}>
            {PLM_TOOL_COUNT + FW_TOOL_COUNT} tools — PLM change/BOM/cost management + embedded firmware verification
          </div>
        </div>
      </div>

      {/* Top tabs */}
      <div style={s.tabs}>
        {tabs.map((t) => (
          <button key={t.id}
            style={{ ...s.tab, ...(tab === t.id ? s.tabActive : {}) }}
            onClick={() => setTab(t.id)}>
            <t.icon size={13} />
            {t.label}
            <span style={{ fontSize: 10, opacity: 0.7 }}>({t.count})</span>
          </button>
        ))}
      </div>

      {/* PLM tab */}
      {tab === 'plm' && (
        <>
          <Section title="Change Management" icon={GitBranch} color="#f59e0b"
            cards={PLM_CHANGE_MGMT} />
          <Section title="Part Numbering" icon={Tag} color="#22d3ee"
            cards={PLM_PART_NUMBERING} />
          <Section title="Cost &amp; Currency" icon={DollarSign} color="#4ade80"
            cards={PLM_COST} />
          <Section title="BOM Analysis" icon={ListTree} color="#a78bfa"
            cards={PLM_BOM} defaultOpen={false} />
        </>
      )}

      {/* Firmware tab */}
      {tab === 'firmware' && (
        <>
          <Section title="Memory &amp; Resources" icon={Server} color="#f59e0b"
            cards={FW_MEMORY} />
          <Section title="Real-time &amp; Safety" icon={Shield} color="#ef4444"
            cards={FW_REALTIME} />
          <Section title="Hardware Verification" icon={Cpu} color="#22d3ee"
            cards={FW_HW_VERIFY} />
          <Section title="Protocol &amp; Communication" icon={Activity} color="#a78bfa"
            cards={FW_PROTOCOL} defaultOpen={false} />
        </>
      )}
    </div>
  )
}
