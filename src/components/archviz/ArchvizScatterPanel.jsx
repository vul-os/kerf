/**
 * ArchvizScatterPanel.jsx — Archviz scatter / population panel.
 *
 * Purpose
 * -------
 * Let users populate an archviz scene with proxy instances of trees, shrubs,
 * people, cars and furniture.  Controls density, random seed, min-spacing,
 * scale/rotation jitter, distribution method (Poisson-disk vs jittered grid).
 * A top-down SVG preview renders instance dots colour-coded by asset category.
 * An asset palette lets users browse and select from the built-in catalogue.
 *
 * Backend tools used (via callTool prop)
 * ----------------------------------------
 *   archviz_asset_library     — browse/search assets
 *   archviz_scatter_populate  — run scatter engine, get instance list
 *
 * Props
 * -----
 *   file        {object|null}
 *   content     {object|string|null}
 *   projectId   {string|null}
 *   fileId      {string|null}
 *   callTool    {(name:string, args:object) => Promise<any>}
 *   onDispatch  {(action:object) => void}
 */

import { useState, useCallback, useRef } from 'react'
import {
  Trees,
  Users,
  Car,
  Armchair,
  Shuffle,
  Grid3x3,
  Play,
  RefreshCw,
  Search,
  ChevronDown,
  ChevronRight,
  Info,
} from 'lucide-react'

// ── Category colour map (matches Python backend) ──────────────────────────
export const CATEGORY_COLORS = {
  tree:         '#2d8a3e',
  shrub:        '#5aad4e',
  ground_cover: '#8aaa44',
  person:       '#e07040',
  car:          '#4070c0',
  furniture:    '#9060b0',
}

// ── Category icon helper ───────────────────────────────────────────────────
function CategoryIcon({ category, size = 14 }) {
  const props = { size, strokeWidth: 1.8 }
  switch (category) {
    case 'tree':
    case 'shrub':
    case 'ground_cover': return <Trees {...props} />
    case 'person':       return <Users {...props} />
    case 'car':          return <Car {...props} />
    case 'furniture':    return <Armchair {...props} />
    default:             return <Trees {...props} />
  }
}

// ── Top-down scatter preview ───────────────────────────────────────────────
export function ScatterPreview({ instances, area, width = 320, height = 220 }) {
  if (!area) return null
  const xRange = (area.x_max ?? 10) - (area.x_min ?? 0)
  const yRange = (area.y_max ?? 10) - (area.y_min ?? 0)
  if (xRange <= 0 || yRange <= 0) return null

  const pad = 12
  const svgW = width - pad * 2
  const svgH = height - pad * 2

  function toSvg(x, y) {
    const sx = pad + ((x - (area.x_min ?? 0)) / xRange) * svgW
    const sy = pad + (1 - (y - (area.y_min ?? 0)) / yRange) * svgH
    return [sx, sy]
  }

  return (
    <svg
      width={width}
      height={height}
      style={{
        background: '#1a2010',
        border: '1px solid #2a3520',
        borderRadius: 6,
        display: 'block',
      }}
      aria-label="Scatter preview — top-down view"
    >
      {/* Ground plane */}
      <rect x={pad} y={pad} width={svgW} height={svgH} fill="#1e2a16" rx={2} />

      {/* Instances */}
      {(instances || []).map((inst) => {
        const [sx, sy] = toSvg(inst.position[0], inst.position[1])
        const color = CATEGORY_COLORS[inst.category] ?? '#aaaaaa'
        const r = Math.max(2, Math.min(7, (inst.scale?.[0] ?? 1) * 3))
        return (
          <circle
            key={inst.id}
            cx={sx}
            cy={sy}
            r={r}
            fill={color}
            fillOpacity={0.8}
            stroke={color}
            strokeWidth={0.5}
            strokeOpacity={0.4}
          />
        )
      })}

      {/* Legend */}
      {Object.entries(CATEGORY_COLORS).map(([cat, col], i) => {
        const used = (instances || []).some((inst) => inst.category === cat)
        if (!used) return null
        return (
          <g key={cat} transform={`translate(${pad + 4}, ${pad + 8 + i * 14})`}>
            <circle cx={5} cy={0} r={4} fill={col} fillOpacity={0.9} />
            <text x={12} y={4} fontSize={9} fill="#c8d8c0" fontFamily="monospace">
              {cat}
            </text>
          </g>
        )
      })}

      {/* Count badge */}
      <text
        x={width - pad - 2}
        y={height - 4}
        fontSize={9}
        fill="#6a8a60"
        textAnchor="end"
        fontFamily="monospace"
      >
        {(instances || []).length} instances
      </text>
    </svg>
  )
}

// ── Asset chip ─────────────────────────────────────────────────────────────
function AssetChip({ asset, selected, onToggle }) {
  const color = CATEGORY_COLORS[asset.category] ?? '#888'
  return (
    <button
      onClick={() => onToggle(asset.id)}
      title={`${asset.label}\nBBox: ${asset.bbox?.join(' × ')} m`}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '3px 8px',
        borderRadius: 12,
        border: `1.5px solid ${selected ? color : '#334'}`,
        background: selected ? color + '22' : 'transparent',
        color: selected ? color : '#889',
        cursor: 'pointer',
        fontSize: 11,
        fontFamily: 'monospace',
        transition: 'all 0.15s',
      }}
    >
      <CategoryIcon category={asset.category} size={11} />
      {asset.label}
    </button>
  )
}

// ── Numeric slider control ─────────────────────────────────────────────────
function SliderControl({ label, value, min, max, step, onChange, format }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#8a9' }}>
        <span>{label}</span>
        <span style={{ fontFamily: 'monospace', color: '#c8d' }}>
          {format ? format(value) : value}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        style={{ width: '100%', accentColor: '#5a8a5a', cursor: 'pointer' }}
      />
    </div>
  )
}

// ── Main panel ─────────────────────────────────────────────────────────────
export default function ArchvizScatterPanel({ callTool }) {
  // Scatter parameters
  const [density, setDensity] = useState(1.0)
  const [seed, setSeed] = useState(42)
  const [minSpacing, setMinSpacing] = useState(0.5)
  const [scaleJitter, setScaleJitter] = useState(0.2)
  const [rotJitter, setRotJitter] = useState(360)
  const [method, setMethod] = useState('poisson')
  const [area] = useState({ x_min: 0, y_min: 0, x_max: 20, y_max: 20, base_z: 0 })

  // Asset library
  const [catalogue, setCatalogue] = useState([])
  const [catalogueLoaded, setCatalogueLoaded] = useState(false)
  const [assetSearch, setAssetSearch] = useState('')
  const [selectedAssets, setSelectedAssets] = useState(new Set(['tree_deciduous_medium', 'person_standing_male']))
  const [assetPaletteOpen, setAssetPaletteOpen] = useState(true)

  // Scatter results
  const [instances, setInstances] = useState([])
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)
  const [stats, setStats] = useState(null)

  // Load asset catalogue on first open
  const loadCatalogue = useCallback(async () => {
    if (catalogueLoaded || !callTool) return
    try {
      const res = await callTool('archviz_asset_library', { action: 'search', limit: 100 })
      const data = typeof res === 'string' ? JSON.parse(res) : res
      const list = data?.result?.assets ?? data?.assets ?? []
      setCatalogue(list)
      setCatalogueLoaded(true)
    } catch (e) {
      // Graceful fallback — show built-in default names
      setCatalogueLoaded(true)
    }
  }, [callTool, catalogueLoaded])

  const toggleAssetPalette = useCallback(() => {
    setAssetPaletteOpen((v) => !v)
    if (!catalogueLoaded) loadCatalogue()
  }, [catalogueLoaded, loadCatalogue])

  const toggleAsset = useCallback((id) => {
    setSelectedAssets((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  // Run scatter
  const runScatter = useCallback(async () => {
    if (!callTool) {
      setError('callTool prop is not available')
      return
    }
    const assetIds = [...selectedAssets]
    if (!assetIds.length) {
      setError('Select at least one asset from the palette')
      return
    }
    setRunning(true)
    setError(null)
    try {
      const res = await callTool('archviz_scatter_populate', {
        area,
        asset_ids: assetIds,
        density,
        seed,
        min_spacing: minSpacing,
        scale_jitter: scaleJitter,
        rotation_jitter_deg: rotJitter,
        method,
      })
      const data = typeof res === 'string' ? JSON.parse(res) : res
      const rawInstances = data?.result?.instances ?? data?.instances ?? []

      // Attach category from asset_meta for preview colouring
      const meta = data?.result?.asset_meta ?? data?.asset_meta ?? {}
      const enriched = rawInstances.map((inst) => ({
        ...inst,
        category: meta[inst.asset_id]?.category ?? 'tree',
      }))

      setInstances(enriched)
      setStats({
        count: enriched.length,
        method: data?.result?.method ?? method,
        seed: data?.result?.seed ?? seed,
      })
    } catch (e) {
      setError(String(e?.message ?? e))
    } finally {
      setRunning(false)
    }
  }, [callTool, selectedAssets, area, density, seed, minSpacing, scaleJitter, rotJitter, method])

  const randomiseSeed = useCallback(() => setSeed(Math.floor(Math.random() * 99999)), [])

  // Filter catalogue by search
  const visibleCatalogue = catalogue.filter((a) => {
    if (!assetSearch) return true
    const q = assetSearch.toLowerCase()
    return (
      a.label?.toLowerCase().includes(q) ||
      a.id?.toLowerCase().includes(q) ||
      a.tags?.some((t) => t.includes(q))
    )
  })

  const panelStyle = {
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
    padding: 14,
    background: '#141a10',
    color: '#c8d8c0',
    fontFamily: 'system-ui, sans-serif',
    fontSize: 12,
    height: '100%',
    overflowY: 'auto',
    boxSizing: 'border-box',
  }

  const sectionStyle = {
    background: '#1c2616',
    border: '1px solid #2a3520',
    borderRadius: 8,
    padding: 12,
  }

  return (
    <div style={panelStyle}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Trees size={18} color="#5aad4e" />
        <span style={{ fontWeight: 600, fontSize: 14, color: '#c8e8b0' }}>
          Archviz Scatter
        </span>
        <span style={{
          marginLeft: 'auto',
          fontSize: 10,
          color: '#5a7a50',
          background: '#1e2e16',
          padding: '2px 8px',
          borderRadius: 8,
          border: '1px solid #2a4020',
        }}>
          proxy assets · not photoreal
        </span>
      </div>

      {/* Asset Palette ─────────────────────────────────────────────────── */}
      <div style={sectionStyle}>
        <button
          onClick={toggleAssetPalette}
          style={{
            display: 'flex', alignItems: 'center', gap: 6, width: '100%',
            background: 'none', border: 'none', color: '#a8c898', cursor: 'pointer',
            fontSize: 12, padding: 0, fontWeight: 500,
          }}
        >
          {assetPaletteOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          Asset Palette
          <span style={{ marginLeft: 'auto', fontSize: 10, color: '#5a7a50' }}>
            {selectedAssets.size} selected
          </span>
        </button>

        {assetPaletteOpen && (
          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ position: 'relative' }}>
              <Search size={11} style={{ position: 'absolute', left: 7, top: 7, color: '#5a7a50' }} />
              <input
                placeholder="Filter assets…"
                value={assetSearch}
                onChange={(e) => setAssetSearch(e.target.value)}
                style={{
                  width: '100%',
                  paddingLeft: 22,
                  padding: '5px 8px 5px 22px',
                  background: '#131c10',
                  border: '1px solid #2a3520',
                  borderRadius: 5,
                  color: '#c8d8c0',
                  fontSize: 11,
                  boxSizing: 'border-box',
                }}
              />
            </div>

            {!catalogueLoaded && catalogue.length === 0 && (
              <div style={{ color: '#5a7a50', fontSize: 10, padding: '4px 0' }}>
                Catalogue loads on first scatter run…
              </div>
            )}

            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {visibleCatalogue.map((asset) => (
                <AssetChip
                  key={asset.id}
                  asset={asset}
                  selected={selectedAssets.has(asset.id)}
                  onToggle={toggleAsset}
                />
              ))}
              {catalogue.length === 0 && (
                /* Show default asset ids when catalogue not yet loaded */
                [
                  { id: 'tree_deciduous_medium', category: 'tree',    label: 'Deciduous Tree (M)' },
                  { id: 'tree_conifer_tall',      category: 'tree',    label: 'Conifer Tall' },
                  { id: 'shrub_rounded',          category: 'shrub',   label: 'Rounded Shrub' },
                  { id: 'person_standing_male',   category: 'person',  label: 'Standing Male' },
                  { id: 'person_standing_female', category: 'person',  label: 'Standing Female' },
                  { id: 'car_sedan',              category: 'car',     label: 'Sedan' },
                  { id: 'furniture_chair',        category: 'furniture', label: 'Chair' },
                ].map((asset) => (
                  <AssetChip
                    key={asset.id}
                    asset={asset}
                    selected={selectedAssets.has(asset.id)}
                    onToggle={toggleAsset}
                  />
                ))
              )}
            </div>
          </div>
        )}
      </div>

      {/* Scatter Controls ──────────────────────────────────────────────── */}
      <div style={sectionStyle}>
        <div style={{ fontWeight: 500, color: '#a8c898', marginBottom: 10, fontSize: 12 }}>
          Distribution Controls
        </div>

        {/* Method toggle */}
        <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
          {['poisson', 'grid'].map((m) => (
            <button
              key={m}
              onClick={() => setMethod(m)}
              style={{
                flex: 1,
                padding: '4px 0',
                borderRadius: 5,
                border: `1.5px solid ${method === m ? '#4a8a4a' : '#2a3520'}`,
                background: method === m ? '#1e3020' : 'transparent',
                color: method === m ? '#a8d898' : '#5a7a50',
                cursor: 'pointer',
                fontSize: 11,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 4,
              }}
            >
              {m === 'poisson' ? <Shuffle size={11} /> : <Grid3x3 size={11} />}
              {m === 'poisson' ? 'Poisson-Disk' : 'Jittered Grid'}
            </button>
          ))}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <SliderControl
            label="Density (instances/m²)"
            value={density}
            min={0.05} max={10} step={0.05}
            onChange={setDensity}
            format={(v) => v.toFixed(2)}
          />
          <SliderControl
            label="Min Spacing (m)"
            value={minSpacing}
            min={0.1} max={5} step={0.1}
            onChange={setMinSpacing}
            format={(v) => v.toFixed(1) + ' m'}
          />
          <SliderControl
            label="Scale Jitter"
            value={scaleJitter}
            min={0} max={0.8} step={0.05}
            onChange={setScaleJitter}
            format={(v) => '±' + Math.round(v * 100) + '%'}
          />
          <SliderControl
            label="Rotation Jitter"
            value={rotJitter}
            min={0} max={360} step={5}
            onChange={setRotJitter}
            format={(v) => '±' + Math.round(v / 2) + '°'}
          />
        </div>

        {/* Seed row */}
        <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 11, color: '#8a9', flex: 1 }}>Seed</span>
          <input
            type="number"
            value={seed}
            onChange={(e) => setSeed(parseInt(e.target.value, 10) || 0)}
            style={{
              width: 70,
              padding: '3px 6px',
              background: '#131c10',
              border: '1px solid #2a3520',
              borderRadius: 4,
              color: '#c8d8c0',
              fontSize: 11,
              textAlign: 'right',
            }}
          />
          <button
            onClick={randomiseSeed}
            title="Random seed"
            style={{
              background: 'none', border: '1px solid #2a3520', borderRadius: 4,
              padding: '3px 6px', color: '#5a7a50', cursor: 'pointer',
            }}
          >
            <RefreshCw size={11} />
          </button>
        </div>
      </div>

      {/* Run button */}
      <button
        onClick={runScatter}
        disabled={running}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
          padding: '8px 0',
          background: running ? '#1e3020' : '#2a5a2a',
          border: `1px solid ${running ? '#2a4020' : '#4a8a4a'}`,
          borderRadius: 6,
          color: running ? '#5a7a50' : '#a8d898',
          cursor: running ? 'not-allowed' : 'pointer',
          fontSize: 12, fontWeight: 500,
        }}
      >
        <Play size={13} />
        {running ? 'Scattering…' : 'Scatter Instances'}
      </button>

      {/* Error */}
      {error && (
        <div style={{
          background: '#2a1010', border: '1px solid #5a2020', borderRadius: 6,
          padding: '8px 10px', color: '#e07070', fontSize: 11,
        }}>
          {error}
        </div>
      )}

      {/* Stats */}
      {stats && !error && (
        <div style={{
          display: 'flex', gap: 10, fontSize: 10, color: '#6a8a60',
          fontFamily: 'monospace',
        }}>
          <span>{stats.count} instances</span>
          <span>·</span>
          <span>{stats.method}</span>
          <span>·</span>
          <span>seed {stats.seed}</span>
        </div>
      )}

      {/* Preview */}
      {instances.length > 0 && (
        <div style={sectionStyle}>
          <div style={{ fontWeight: 500, color: '#a8c898', marginBottom: 8, fontSize: 12 }}>
            Top-Down Preview
          </div>
          <ScatterPreview instances={instances} area={area} width={290} height={200} />
          <div style={{
            display: 'flex', alignItems: 'center', gap: 4,
            marginTop: 6, color: '#4a6a40', fontSize: 10,
          }}>
            <Info size={10} />
            Proxy placeholder dots — not photoreal geometry
          </div>
        </div>
      )}

      {/* Instance table (first 15) */}
      {instances.length > 0 && (
        <div style={sectionStyle}>
          <div style={{ fontWeight: 500, color: '#a8c898', marginBottom: 6, fontSize: 12 }}>
            Instance List (first {Math.min(instances.length, 15)} / {instances.length})
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10, fontFamily: 'monospace' }}>
              <thead>
                <tr style={{ color: '#5a7a50', borderBottom: '1px solid #2a3520' }}>
                  <th style={{ textAlign: 'left', padding: '2px 4px' }}>#</th>
                  <th style={{ textAlign: 'left', padding: '2px 4px' }}>asset</th>
                  <th style={{ textAlign: 'right', padding: '2px 4px' }}>x</th>
                  <th style={{ textAlign: 'right', padding: '2px 4px' }}>y</th>
                  <th style={{ textAlign: 'right', padding: '2px 4px' }}>rz°</th>
                  <th style={{ textAlign: 'right', padding: '2px 4px' }}>scale</th>
                </tr>
              </thead>
              <tbody>
                {instances.slice(0, 15).map((inst) => {
                  const col = CATEGORY_COLORS[inst.category] ?? '#888'
                  return (
                    <tr key={inst.id} style={{ borderBottom: '1px solid #1e2a16' }}>
                      <td style={{ padding: '2px 4px', color: '#4a6a40' }}>{inst.id}</td>
                      <td style={{ padding: '2px 4px', color: col }}>
                        {inst.asset_id.replace(/^(tree_|shrub_|person_|car_|furniture_|ground_cover_)/, '')}
                      </td>
                      <td style={{ padding: '2px 4px', textAlign: 'right', color: '#a0b890' }}>
                        {inst.position[0].toFixed(2)}
                      </td>
                      <td style={{ padding: '2px 4px', textAlign: 'right', color: '#a0b890' }}>
                        {inst.position[1].toFixed(2)}
                      </td>
                      <td style={{ padding: '2px 4px', textAlign: 'right', color: '#8a9880' }}>
                        {inst.rotation[2].toFixed(1)}
                      </td>
                      <td style={{ padding: '2px 4px', textAlign: 'right', color: '#8a9880' }}>
                        {inst.scale[0].toFixed(2)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
