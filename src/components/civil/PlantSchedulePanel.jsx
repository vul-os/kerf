/**
 * PlantSchedulePanel.jsx — Plant schedule (planting plan) with catalog lookup.
 *
 * Renders:
 *   • Filterable plant schedule table (species, mature dims, zone range, water, etc.)
 *   • Dispatch buttons for landscape_lookup_plant and landscape_filter_plants
 *   • Planting grid count per species
 *
 * Dispatches:
 *   • `landscape_lookup_plant`   — single species detail
 *   • `landscape_filter_plants`  — site-filtered catalog query
 *   via POST /api/tools/call
 *
 * Props
 * ─────
 *   plants    {Array<{id, species, count?, x?, y?}>}  Site plant list.
 *   usdaZone  {number}   USDA hardiness zone for filtering (default 6).
 *   className {string}
 *   onDispatch {function}  Called with { tool, params } instead of fetch.
 */

import { useState } from 'react'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''

// Water use colour indicators
const WATER_BADGE = {
  low:    'bg-emerald-900 text-emerald-300',
  medium: 'bg-blue-900 text-blue-300',
  high:   'bg-cyan-900 text-cyan-300',
}

// Pollinator value dots
const POLLINATOR_DOT = {
  high:   '●●●',
  medium: '●●○',
  low:    '●○○',
  none:   '○○○',
}

export default function PlantSchedulePanel({
  content,
  plants: plants_prop = [],
  usdaZone: usdaZone_prop = 6,
  className = '',
  onDispatch,
}) {
  // Accept a `content` string (JSON) from the panel registry.
  const _p = (() => { if (!content) return {}; try { return JSON.parse(content) } catch { return {} } })()
  const plants   = _p.plants   ?? plants_prop
  const usdaZone = _p.usdaZone ?? usdaZone_prop
  const [loading, setLoading] = useState(false)
  const [activeAction, setActiveAction] = useState(null)
  const [schedule, setSchedule] = useState(null)  // filtered catalog results
  const [lookupResult, setLookupResult] = useState(null)
  const [lookupName, setLookupName] = useState('')
  const [error, setError] = useState(null)

  // ── Filter plants catalog ──────────────────────────────────────────────────
  async function handleFilterPlants() {
    setLoading(true)
    setActiveAction('filter')
    setError(null)
    const params = { usda_zone: usdaZone }
    try {
      if (onDispatch) {
        onDispatch({ tool: 'landscape_filter_plants', params })
      } else {
        const res = await fetch(`${API_URL}/api/tools/call`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ tool_name: 'landscape_filter_plants', params }),
        })
        const data = await res.json()
        if (data.ok) {
          setSchedule(data.plants)
        } else {
          setError(data.error || 'Filter failed')
        }
      }
    } catch (e) {
      setError(e.message || 'Dispatch failed')
    } finally {
      setLoading(false)
      setActiveAction(null)
    }
  }

  // ── Lookup single plant ────────────────────────────────────────────────────
  async function handleLookup() {
    if (!lookupName.trim()) return
    setLoading(true)
    setActiveAction('lookup')
    setError(null)
    const params = { name: lookupName.trim() }
    try {
      if (onDispatch) {
        onDispatch({ tool: 'landscape_lookup_plant', params })
      } else {
        const res = await fetch(`${API_URL}/api/tools/call`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ tool_name: 'landscape_lookup_plant', params }),
        })
        const data = await res.json()
        if (data.ok) {
          setLookupResult(data)
        } else {
          setError(data.error || `Not found: ${lookupName}`)
        }
      }
    } catch (e) {
      setError(e.message || 'Lookup failed')
    } finally {
      setLoading(false)
      setActiveAction(null)
    }
  }

  // Display list: prefer catalog results, fall back to prop plants
  const displayPlants = schedule
    ? schedule.slice(0, 40)
    : plants.map(p => ({ common_name: p.species || p.id, kind: p.type || 'shrub', count: p.count ?? 1 }))

  return (
    <div className={`flex flex-col gap-2 ${className}`} data-testid="plant-schedule-panel">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-1 flex-wrap gap-2">
        <span className="text-xs text-slate-500 font-medium tracking-wide uppercase">
          Plant Schedule
        </span>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            className="text-xs px-2 py-1 rounded border border-slate-600 hover:border-slate-400 text-slate-300 disabled:opacity-50 transition-colors"
            onClick={handleFilterPlants}
            disabled={loading}
            data-testid="plant-filter-btn"
          >
            {loading && activeAction === 'filter' ? 'Loading…' : `Zone ${usdaZone} catalog`}
          </button>
          <div className="flex items-center gap-1">
            <input
              className="text-xs px-2 py-1 rounded border border-slate-700 bg-slate-900 text-slate-200 w-36 focus:outline-none focus:border-slate-400"
              placeholder="Species name…"
              value={lookupName}
              onChange={e => setLookupName(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleLookup() }}
              data-testid="plant-lookup-input"
            />
            <button
              className="text-xs px-2 py-1 rounded bg-kerf-700 hover:bg-kerf-600 text-white disabled:opacity-50 transition-colors"
              onClick={handleLookup}
              disabled={loading || !lookupName.trim()}
              data-testid="plant-lookup-btn"
            >
              {loading && activeAction === 'lookup' ? '…' : 'Lookup'}
            </button>
          </div>
        </div>
      </div>

      {/* Single species lookup card */}
      {lookupResult && (
        <div
          className="mx-1 rounded border border-slate-700 bg-slate-900 p-2 text-xs font-mono"
          data-testid="plant-lookup-card"
        >
          <div className="text-slate-100 font-semibold">
            {lookupResult.common_name}{' '}
            <span className="text-slate-500 font-normal italic">{lookupResult.scientific_name}</span>
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 mt-1 text-slate-400">
            <span>H: {lookupResult.mature_height_m} m</span>
            <span>Spread: {lookupResult.mature_spread_m} m</span>
            <span>Zone: {lookupResult.usda_zones_min}–{lookupResult.usda_zones_max}</span>
            <span>Light: {lookupResult.light.replace('_', ' ')}</span>
            <span>Water: {lookupResult.water}</span>
            <span>Deer: {lookupResult.deer_resistant ? 'resistant' : 'browsed'}</span>
          </div>
          <div className="text-slate-500 mt-1">{lookupResult.notes}</div>
        </div>
      )}

      {/* Plant schedule table */}
      {displayPlants.length > 0 ? (
        <div className="overflow-auto max-h-64" data-testid="plant-schedule-table">
          <table className="w-full text-xs font-mono text-slate-300 border-collapse">
            <thead className="sticky top-0 bg-slate-900">
              <tr className="text-slate-500 text-[10px] uppercase">
                <th className="text-left py-1 pr-2">Common name</th>
                <th className="text-left pr-2">Scientific</th>
                <th className="text-left pr-2">Type</th>
                <th className="text-right pr-2">H (m)</th>
                <th className="text-left pr-2">Water</th>
                <th className="text-center pr-2">Pollin.</th>
                <th className="text-center">Deer</th>
              </tr>
            </thead>
            <tbody>
              {displayPlants.map((p, i) => (
                <tr key={i} className="border-t border-slate-800 hover:bg-slate-800/40">
                  <td className="py-0.5 pr-2 text-slate-200">{p.common_name}</td>
                  <td className="pr-2 text-slate-500 italic">{p.scientific_name || '—'}</td>
                  <td className="pr-2 text-slate-400">{(p.kind || '').replace('_', ' ')}</td>
                  <td className="text-right pr-2 text-slate-400">{p.mature_height_m ?? '—'}</td>
                  <td className="pr-2">
                    {p.water ? (
                      <span className={`px-1 rounded text-[9px] ${WATER_BADGE[p.water] || 'text-slate-400'}`}>
                        {p.water}
                      </span>
                    ) : '—'}
                  </td>
                  <td className="text-center pr-2 text-yellow-500 text-[9px]">
                    {POLLINATOR_DOT[p.pollinator_value] || '○○○'}
                  </td>
                  <td className="text-center text-[9px]">
                    {p.deer_resistant === true ? (
                      <span className="text-emerald-400">DR</span>
                    ) : p.deer_resistant === false ? (
                      <span className="text-slate-600">—</span>
                    ) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {schedule && (
            <div className="text-[10px] text-slate-600 px-1 py-1">
              {schedule.length} species for USDA Zone {usdaZone} ·
              Dirr MWLP 6th ed. (2009) · NOT USDA certified
            </div>
          )}
        </div>
      ) : (
        <div className="text-xs text-slate-600 px-1 py-4 text-center">
          No plants to display — add plants props or click the zone catalog button
        </div>
      )}

      {error && (
        <div className="text-xs text-red-400 px-1" data-testid="plant-schedule-error">
          {error}
        </div>
      )}
    </div>
  )
}
