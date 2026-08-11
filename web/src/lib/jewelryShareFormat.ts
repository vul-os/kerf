/**
 * Display formatting and input validation for the jewelry share page.
 *
 * Split out of JewelryShare.tsx: that module exports a route component, and
 * Vite fast refresh only works when a module exports components alone — one
 * non-component export disables hot reload for the whole route. These were
 * already marked "exported for tests", so a module of their own is where they
 * were headed anyway.
 */

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests)
// ---------------------------------------------------------------------------

/**
 * formatMetal — turn a metal key like '18k_yellow' into a human label.
 * Falls back gracefully to the raw key.
 */
export function formatMetal(key) {
  if (!key) return '—'
  const map = {
    '14k_yellow': '14k Yellow Gold',
    '14k_white':  '14k White Gold',
    '14k_rose':   '14k Rose Gold',
    '18k_yellow': '18k Yellow Gold',
    '18k_white':  '18k White Gold',
    '18k_rose':   '18k Rose Gold',
    platinum_950: 'Platinum 950',
    sterling_925: 'Sterling Silver 925',
  }
  return map[key] ?? key.replace(/_/g, ' ')
}

/**
 * formatPiece — turn a piece key into a label.
 */
export function formatPiece(key) {
  if (!key) return '—'
  const map = { ring: 'Ring', pendant: 'Pendant', earring: 'Earring' }
  return map[key] ?? key.charAt(0).toUpperCase() + key.slice(1)
}

/**
 * formatFinish — turn a finish key into a label.
 */
export function formatFinish(key) {
  if (!key) return '—'
  const map = {
    polish:  'High-polish',
    satin:   'Satin / brushed',
    rhodium: 'Rhodium plating',
    hammer:  'Hammered texture',
  }
  return map[key] ?? key.replace(/_/g, ' ')
}

/**
 * buildSpecRows — turn share metadata into an array of { label, value } rows
 * for display in the spec table.
 */
export function buildSpecRows(meta) {
  if (!meta || typeof meta !== 'object') return []
  const rows = []
  if (meta.piece_type)      rows.push({ label: 'Piece',       value: formatPiece(meta.piece_type) })
  if (meta.metal)           rows.push({ label: 'Metal',       value: formatMetal(meta.metal) })
  if (meta.finish)          rows.push({ label: 'Finish',      value: formatFinish(meta.finish) })
  if (meta.ring_size_us)    rows.push({ label: 'Ring size',   value: `US ${meta.ring_size_us}` })
  if (meta.chain_length_inch) rows.push({ label: 'Chain',     value: `${meta.chain_length_inch}"` })
  if (typeof meta.stones_count === 'number' && meta.stones_count > 0) {
    rows.push({ label: 'Stones', value: `${meta.stones_count} stone${meta.stones_count !== 1 ? 's' : ''}` })
  }
  if (typeof meta.total === 'number') {
    rows.push({ label: 'Estimate', value: `$${meta.total.toFixed(2)}` })
  }
  return rows
}

/**
 * validateComment — returns an error string or null.
 * Exported so the test can exercise it without rendering.
 */
export function validateComment(name, body) {
  if (!name || !name.trim()) return 'Please enter your name.'
  if (!body || !body.trim()) return 'Comment cannot be empty.'
  return null
}

/**
 * validateApproval — returns an error string or null.
 */
export function validateApproval(name) {
  if (!name || !name.trim()) return 'Please enter your name to approve.'
  return null
}
