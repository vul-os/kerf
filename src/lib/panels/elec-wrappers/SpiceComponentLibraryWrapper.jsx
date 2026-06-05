// SpiceComponentLibraryWrapper.jsx
// Panel-registry wrapper for the SPICE Component Library browser.
//
// The panel delivers:
//   - Category tree sidebar (22 device families)
//   - Keyword + spec-filter search bar
//   - Model-card preview area (full .MODEL / .SUBCKT SPICE text)
//   - "Insert" button that fires a kerf:spice-insert CustomEvent so the
//     active netlist editor can receive the model string without tight coupling.
//
// Content JSON shape (optional, forwarded from file content):
//   { initial_category?: string, initial_keyword?: string }

import { useState, useCallback } from 'react'

// ── Category metadata (mirrors spice_library.py CATEGORIES) ──────────────────
const CATEGORIES = {
  diode_rectifier:  'Diodes — Rectifier',
  diode_schottky:   'Diodes — Schottky',
  diode_zener:      'Diodes — Zener / Voltage Reference',
  diode_tvs:        'Diodes — TVS / ESD',
  diode_led:        'Diodes — LED',
  bjt_npn:          'BJTs — NPN',
  bjt_pnp:          'BJTs — PNP',
  bjt_darlington:   'BJTs — Darlington',
  bjt_rf:           'BJTs — RF',
  mosfet_nmos:      'MOSFETs — N-channel',
  mosfet_pmos:      'MOSFETs — P-channel',
  jfet_n:           'JFETs — N-channel',
  jfet_p:           'JFETs — P-channel',
  opamp:            'Op-Amps',
  comparator:       'Comparators',
  vref:             'Voltage References',
  regulator:        'Voltage Regulators',
  passive_cap:      'Passives — Capacitors',
  passive_ind:      'Passives — Inductors',
  passive_res:      'Passives — Resistors',
  logic:            'Logic Gates',
  ic_timer:         'ICs — Timer',
  ic_misc:          'ICs — Miscellaneous',
}

const DISCLAIMER =
  'All models use representative / generic parameter values — NOT extracted ' +
  'from vendor datasheets. For high-accuracy simulation, replace with ' +
  'vendor-supplied SPICE models from the manufacturer\'s website.'

function parseContent(raw) {
  if (!raw || typeof raw !== 'string') return {}
  try { return JSON.parse(raw) || {} } catch { return {} }
}

// ── Styles (inline — panel is self-contained) ────────────────────────────────
const S = {
  root: {
    display: 'flex', height: '100%', fontFamily: 'system-ui, sans-serif',
    fontSize: 13, color: '#e2e8f0', background: '#0f1117',
  },
  sidebar: {
    width: 220, borderRight: '1px solid #1e2430', overflowY: 'auto',
    padding: '8px 0', flexShrink: 0,
  },
  catItem: (active) => ({
    padding: '5px 14px', cursor: 'pointer',
    background: active ? '#1a2340' : 'transparent',
    color: active ? '#60a5fa' : '#94a3b8',
    borderLeft: active ? '2px solid #3b82f6' : '2px solid transparent',
    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
  }),
  catGroup: {
    padding: '6px 14px 2px', fontSize: 10, color: '#475569',
    textTransform: 'uppercase', letterSpacing: '0.08em',
  },
  main: { flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 },
  toolbar: {
    display: 'flex', gap: 8, padding: '8px 12px',
    borderBottom: '1px solid #1e2430', flexShrink: 0,
  },
  input: {
    flex: 1, background: '#1a1f2e', border: '1px solid #2d3748',
    borderRadius: 4, color: '#e2e8f0', padding: '4px 8px', fontSize: 13,
    outline: 'none',
  },
  specRow: { display: 'flex', gap: 6, alignItems: 'center' },
  specLabel: { color: '#64748b', fontSize: 12, whiteSpace: 'nowrap' },
  specInput: {
    width: 80, background: '#1a1f2e', border: '1px solid #2d3748',
    borderRadius: 4, color: '#e2e8f0', padding: '4px 6px', fontSize: 12,
    outline: 'none',
  },
  body: { flex: 1, display: 'flex', minHeight: 0 },
  list: {
    width: 240, borderRight: '1px solid #1e2430', overflowY: 'auto',
    flexShrink: 0,
  },
  listItem: (active) => ({
    padding: '6px 12px', cursor: 'pointer',
    background: active ? '#1a2340' : 'transparent',
    borderBottom: '1px solid #0d111a',
  }),
  listName: { fontWeight: 600, color: '#e2e8f0', fontSize: 12 },
  listDesc: { color: '#64748b', fontSize: 11, marginTop: 2 },
  preview: { flex: 1, overflowY: 'auto', padding: 16 },
  previewTitle: { fontSize: 15, fontWeight: 700, color: '#f1f5f9', marginBottom: 4 },
  previewCat: { fontSize: 11, color: '#60a5fa', marginBottom: 8 },
  previewDesc: { fontSize: 12, color: '#94a3b8', marginBottom: 12 },
  previewCode: {
    background: '#070a10', border: '1px solid #1e2430', borderRadius: 6,
    padding: '12px 14px', fontSize: 12, fontFamily: 'monospace',
    color: '#86efac', whiteSpace: 'pre-wrap', wordBreak: 'break-all',
    overflowX: 'auto',
  },
  paramRow: { display: 'flex', gap: 16, marginBottom: 12, flexWrap: 'wrap' },
  param: {
    background: '#1a1f2e', borderRadius: 4, padding: '3px 8px',
    fontSize: 11, color: '#94a3b8',
  },
  insertBtn: {
    marginTop: 14, padding: '7px 18px', background: '#2563eb',
    color: '#fff', border: 'none', borderRadius: 5, cursor: 'pointer',
    fontSize: 13, fontWeight: 600,
  },
  disclaimer: {
    margin: '14px 0 0', padding: '8px 12px', background: '#1a1f10',
    border: '1px solid #374419', borderRadius: 5, fontSize: 11, color: '#a3a832',
  },
  empty: { color: '#475569', padding: 24, fontSize: 13 },
  count: { fontSize: 11, color: '#475569', padding: '4px 12px 8px' },
}

// ── Category grouping ─────────────────────────────────────────────────────────
const CAT_GROUPS = [
  { label: 'Diodes', keys: ['diode_rectifier','diode_schottky','diode_zener','diode_tvs','diode_led'] },
  { label: 'BJTs', keys: ['bjt_npn','bjt_pnp','bjt_darlington','bjt_rf'] },
  { label: 'MOSFETs / JFETs', keys: ['mosfet_nmos','mosfet_pmos','jfet_n','jfet_p'] },
  { label: 'Active ICs', keys: ['opamp','comparator','vref','regulator'] },
  { label: 'Passives', keys: ['passive_cap','passive_ind','passive_res'] },
  { label: 'Logic / ICs', keys: ['logic','ic_timer','ic_misc'] },
]

// ── Main component ────────────────────────────────────────────────────────────
export default function SpiceComponentLibraryWrapper({ content, file, projectId, fileId }) {
  const parsed = parseContent(content)

  const [activeCat, setActiveCat] = useState(parsed.initial_category || null)
  const [keyword, setKeyword] = useState(parsed.initial_keyword || '')
  const [specKey, setSpecKey] = useState('')
  const [specVal, setSpecVal] = useState('')
  const [selected, setSelected] = useState(null)
  const [searchResults, setSearchResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // ── Search via LLM tool ───────────────────────────────────────────────────
  const doSearch = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = {}
      if (activeCat) params.category = activeCat
      if (keyword.trim()) params.keyword = keyword.trim()
      if (specKey.trim()) params.spec_key = specKey.trim()
      if (specVal.trim()) params.spec_value = specVal.trim()

      const resp = await fetch('/api/tools/spice_library_search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      if (data.error) throw new Error(data.error)
      setSearchResults(data.models || [])
    } catch (err) {
      setError(err.message)
      setSearchResults([])
    } finally {
      setLoading(false)
    }
  }, [activeCat, keyword, specKey, specVal])

  // Fetch model card on selection
  const fetchModel = useCallback(async (name) => {
    try {
      const resp = await fetch('/api/tools/spice_library_get_model', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      if (data.error) throw new Error(data.error)
      setSelected(data)
    } catch (err) {
      setError(err.message)
    }
  }, [])

  const handleCatClick = (cat) => {
    setActiveCat(cat === activeCat ? null : cat)
    setSearchResults(null)
    setSelected(null)
  }

  const handleInsert = () => {
    if (!selected) return
    const ev = new CustomEvent('kerf:spice-insert', {
      bubbles: true,
      detail: { name: selected.name, spice: selected.spice, category: selected.category },
    })
    document.dispatchEvent(ev)
  }

  // Auto-search when category changes
  const handleCatSearch = (cat) => {
    const newCat = cat === activeCat ? null : cat
    setActiveCat(newCat)
    setSelected(null)
    // trigger search with new cat
    setTimeout(async () => {
      setLoading(true)
      setError(null)
      try {
        const params = {}
        if (newCat) params.category = newCat
        if (keyword.trim()) params.keyword = keyword.trim()
        const resp = await fetch('/api/tools/spice_library_search', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(params),
        })
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
        const data = await resp.json()
        if (data.error) throw new Error(data.error)
        setSearchResults(data.models || [])
      } catch (err) {
        setError(err.message)
        setSearchResults([])
      } finally {
        setLoading(false)
      }
    }, 0)
  }

  const models = searchResults || []

  return (
    <div style={S.root}>
      {/* Sidebar — category tree */}
      <div style={S.sidebar}>
        <div style={{ ...S.catItem(activeCat === null), fontWeight: 700 }}
          onClick={() => handleCatSearch(null)}>
          All ({Object.keys(CATEGORIES).length} families)
        </div>
        {CAT_GROUPS.map(group => (
          <div key={group.label}>
            <div style={S.catGroup}>{group.label}</div>
            {group.keys.map(key => (
              <div key={key}
                style={S.catItem(activeCat === key)}
                onClick={() => handleCatSearch(key)}
                title={CATEGORIES[key]}>
                {CATEGORIES[key]}
              </div>
            ))}
          </div>
        ))}
      </div>

      {/* Main content */}
      <div style={S.main}>
        {/* Toolbar */}
        <div style={{ ...S.toolbar, flexDirection: 'column', gap: 6 }}>
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              style={S.input}
              placeholder="Search by name or description…"
              value={keyword}
              onChange={e => setKeyword(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && doSearch()}
            />
            <button
              style={{ ...S.insertBtn, marginTop: 0, padding: '4px 14px' }}
              onClick={doSearch}
              disabled={loading}>
              {loading ? '…' : 'Search'}
            </button>
          </div>
          <div style={S.specRow}>
            <span style={S.specLabel}>Spec filter:</span>
            <input style={S.specInput} placeholder="param (e.g. BV)"
              value={specKey} onChange={e => setSpecKey(e.target.value)} />
            <span style={S.specLabel}>=</span>
            <input style={S.specInput} placeholder="value (e.g. 12)"
              value={specVal} onChange={e => setSpecVal(e.target.value)} />
          </div>
          {error && <div style={{ color: '#f87171', fontSize: 11 }}>Error: {error}</div>}
        </div>

        {/* Body: list + preview */}
        <div style={S.body}>
          {/* Model list */}
          <div style={S.list}>
            {searchResults === null && (
              <div style={S.empty}>Select a category or search to browse models.</div>
            )}
            {searchResults !== null && models.length === 0 && (
              <div style={S.empty}>No models found.</div>
            )}
            {models.length > 0 && (
              <div style={S.count}>{models.length} model{models.length !== 1 ? 's' : ''}</div>
            )}
            {models.map(m => (
              <div key={m.name}
                style={S.listItem(selected?.name === m.name)}
                onClick={() => fetchModel(m.name)}>
                <div style={S.listName}>{m.name}</div>
                <div style={S.listDesc}>{m.description}</div>
              </div>
            ))}
          </div>

          {/* Model card preview */}
          <div style={S.preview}>
            {!selected ? (
              <div style={S.empty}>Select a model to preview its SPICE card.</div>
            ) : (
              <>
                <div style={S.previewTitle}>{selected.name}</div>
                <div style={S.previewCat}>{selected.category_label || selected.category}</div>
                <div style={S.previewDesc}>{selected.description}</div>

                {/* Key parameters */}
                {selected.params && Object.keys(selected.params).length > 0 && (
                  <div style={S.paramRow}>
                    {Object.entries(selected.params).map(([k, v]) => (
                      <div key={k} style={S.param}>{k}: {String(v)}</div>
                    ))}
                  </div>
                )}

                {/* SPICE text */}
                <pre style={S.previewCode}>{selected.spice}</pre>

                {/* Usage hint */}
                {selected.usage_hint && (
                  <div style={{ fontSize: 11, color: '#64748b', marginTop: 10 }}>
                    {selected.usage_hint}
                  </div>
                )}

                <button style={S.insertBtn} onClick={handleInsert}>
                  Insert into Netlist
                </button>

                <div style={S.disclaimer}>{DISCLAIMER}</div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
