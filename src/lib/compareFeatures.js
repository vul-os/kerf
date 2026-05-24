/**
 * compareFeatures.js — feature-matrix helpers for the compare system.
 *
 * Exports:
 *   DOMAIN_META   — array of 14 domain descriptors { code, slug, title, short, accent }
 *   STATUS_META   — status descriptor map { yes, partial, paid, no, unknown }
 *   loadManifest  — fetch + cache /compare-manifest.json
 *   featuresByDomain — group one item's features by domain code
 *   pivotByDomain — cross-CAD pivot table for a single domain
 */

// ---------------------------------------------------------------------------
// DOMAIN_META
// ---------------------------------------------------------------------------

/**
 * @typedef {{ code: string, slug: string, title: string, short: string, accent: string }} DomainMeta
 */

/** @type {DomainMeta[]} */
export const DOMAIN_META = [
  { code: 'D1',  slug: 'geometry',       title: 'Geometry & core CAD',         short: 'Geometry',      accent: 'kerf-300' },
  { code: 'D2',  slug: 'structural',     title: 'Structural / FEA',            short: 'Structural',    accent: 'sky-400' },
  { code: 'D3',  slug: 'machine',        title: 'Machine elements',            short: 'Machine',       accent: 'violet-400' },
  { code: 'D4',  slug: 'thermofluid',    title: 'Thermal / fluid / HVAC',      short: 'Thermal-fluid', accent: 'orange-400' },
  { code: 'D5',  slug: 'aerospace-marine', title: 'Aero / marine / space',     short: 'Aero-marine',   accent: 'cyan-400' },
  { code: 'D6',  slug: 'electronics',    title: 'Electronics / EDA / silicon', short: 'Electronics',   accent: 'emerald-400' },
  { code: 'D7',  slug: 'manufacturing',  title: 'Manufacturing / CAM',         short: 'Manufacturing', accent: 'amber-400' },
  { code: 'D8',  slug: 'civil',          title: 'Civil / infrastructure / geo',short: 'Civil',         accent: 'lime-400' },
  { code: 'D9',  slug: 'dynamics',       title: 'Dynamics / motion / controls',short: 'Dynamics',      accent: 'rose-400' },
  { code: 'D10', slug: 'electrical',     title: 'Electrical / energy / PLC',   short: 'Electrical',    accent: 'yellow-400' },
  { code: 'D11', slug: 'tolerancing',    title: 'Tolerancing / metrology / QA',short: 'Tolerancing',   accent: 'teal-400' },
  { code: 'D12', slug: 'optics',         title: 'Optics / acoustics',          short: 'Optics',        accent: 'fuchsia-400' },
  { code: 'D13', slug: 'verticals',      title: 'Verticals',                   short: 'Verticals',     accent: 'pink-400' },
  { code: 'D14', slug: 'cost',           title: 'Cost / materials / LCA',      short: 'Cost',          accent: 'indigo-400' },
]

// ---------------------------------------------------------------------------
// STATUS_META
// ---------------------------------------------------------------------------

/**
 * @typedef {{ label: string, symbol: string, tone: 'pos'|'neu'|'neg'|'unk' }} StatusEntry
 * @type {Record<string, StatusEntry>}
 */
export const STATUS_META = {
  yes:     { label: 'Yes',     symbol: '✓', tone: 'pos' },
  partial: { label: 'Partial', symbol: '~', tone: 'neu' },
  paid:    { label: 'Paid',    symbol: '$', tone: 'neu' },
  no:      { label: 'No',      symbol: '✗', tone: 'neg' },
  unknown: { label: 'Unknown', symbol: '?', tone: 'unk' },
}

// Tones → Tailwind colour groups (used by CompareFeatureMatrix to build class strings)
export const TONE_CLASSES = {
  pos: { bg: 'bg-emerald-400/10', border: 'border-emerald-400/25', text: 'text-emerald-400' },
  neu: { bg: 'bg-amber-400/10',   border: 'border-amber-400/25',   text: 'text-amber-400' },
  neg: { bg: 'bg-red-400/10',     border: 'border-red-400/25',     text: 'text-red-400' },
  unk: { bg: 'bg-ink-800/60',     border: 'border-ink-700',        text: 'text-ink-500' },
}

// ---------------------------------------------------------------------------
// Manifest loading (React-safe: no module-top fetch)
// ---------------------------------------------------------------------------

/** @type {Promise<object>|null} */
let _manifestPromise = null

/**
 * Fetch (or return cached) /compare-manifest.json.
 * Always resolves — never rejects.
 * Does NOT execute at module evaluation time.
 *
 * @returns {Promise<{version: number, items: object[]}>}
 */
export function loadManifest() {
  if (_manifestPromise !== null) return _manifestPromise
  _manifestPromise = (async () => {
    try {
      const res = await fetch('/compare-manifest.json')
      if (!res.ok) {
        console.warn(`compareFeatures.loadManifest: HTTP ${res.status}`)
        return { version: 2, items: [] }
      }
      const json = await res.json()
      if (!json || !Array.isArray(json.items)) {
        console.warn('compareFeatures.loadManifest: unexpected shape')
        return { version: 2, items: [] }
      }
      return json
    } catch (err) {
      console.warn('compareFeatures.loadManifest: fetch/parse error —', err?.message ?? err)
      return { version: 2, items: [] }
    }
  })()
  return _manifestPromise
}

/**
 * Reset the module-level cache (useful in tests).
 */
export function _resetLoadManifestCache() {
  _manifestPromise = null
}

// ---------------------------------------------------------------------------
// featuresByDomain
// ---------------------------------------------------------------------------

/**
 * Given one manifest item (with a `features` array), return a Map keyed by
 * domain code → array of feature rows.
 *
 * @param {object} item - manifest item with optional features array
 * @returns {Map<string, object[]>}
 */
export function featuresByDomain(item) {
  const map = new Map()
  const features = item?.features
  if (!Array.isArray(features)) return map
  for (const row of features) {
    const code = row?.domain
    if (!code) continue
    if (!map.has(code)) map.set(code, [])
    map.get(code).push(row)
  }
  return map
}

// ---------------------------------------------------------------------------
// pivotByDomain
// ---------------------------------------------------------------------------

/** Status preference order for conflict resolution (higher index = less preferred) */
const STATUS_PREF = ['yes', 'partial', 'paid', 'no', 'unknown']

function preferStatus(a, b) {
  const ia = STATUS_PREF.indexOf(a ?? 'unknown')
  const ib = STATUS_PREF.indexOf(b ?? 'unknown')
  if (ia === -1) return b ?? 'unknown'
  if (ib === -1) return a ?? 'unknown'
  return ia <= ib ? a : b
}

/**
 * Given the full items array and a domain code, return a pivot table:
 * {
 *   features: Map<featureName, {
 *     kerf: string (status),
 *     competitors: { [slug]: string (status) }
 *   }>
 * }
 *
 * Only CADs that have at least one feature in this domain are included.
 * Kerf status is taken from item.features[row].kerf.status.
 * If multiple items disagree on kerf status, prefer yes>partial>paid>no>unknown.
 *
 * @param {object[]} items - manifest items
 * @param {string} domainCode - e.g. 'D1'
 * @returns {{ features: Map<string, { kerf: string, competitors: Record<string, string> }>, cadSlugs: string[] }}
 */
export function pivotByDomain(items, domainCode) {
  // features map: featureName → { kerf, competitors: { [slug]: status } }
  const features = new Map()
  const cadSlugsSet = new Set()

  for (const item of items) {
    if (!Array.isArray(item?.features)) continue
    const domainRows = item.features.filter((r) => r?.domain === domainCode)
    if (domainRows.length === 0) continue
    cadSlugsSet.add(item.slug)

    for (const row of domainRows) {
      const featureName = row.feature
      if (!featureName) continue
      if (!features.has(featureName)) {
        features.set(featureName, { kerf: 'unknown', competitors: {} })
      }
      const entry = features.get(featureName)

      // Update kerf status (prefer more specific)
      const kerfStatus = row?.kerf?.status ?? 'unknown'
      entry.kerf = preferStatus(entry.kerf, kerfStatus)

      // Update competitor status
      const compStatus = row?.competitor?.status ?? 'unknown'
      const compSlug = item.slug
      if (!(compSlug in entry.competitors)) {
        entry.competitors[compSlug] = compStatus
      } else {
        entry.competitors[compSlug] = preferStatus(entry.competitors[compSlug], compStatus)
      }
    }
  }

  return { features, cadSlugs: [...cadSlugsSet] }
}
