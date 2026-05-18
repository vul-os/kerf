/**
 * compareMdParser.js — parses YAML front-matter and body from a compare .md file.
 *
 * Mirrors the lightweight pattern in build-docs-manifest.mjs / build-compare-manifest.mjs:
 * no external YAML dep — only the subset of keys we actually consume.
 *
 * Exported functions:
 *   parseFrontmatter(raw: string): { data: Record<string, unknown>, body: string }
 *   parseCompareMd(raw: string): CompareMeta
 *
 * CompareMeta shape:
 *   {
 *     slug: string,
 *     competitor: string,
 *     category: string,
 *     hero_tagline: string,
 *     left: 'kerf',          // always 'kerf' — Kerf is always on the left
 *     right: string,
 *     reviewed_at: string | null,
 *     order: number | null,
 *     title: string | null,
 *     body: string,
 *   }
 */

/**
 * Tiny YAML front-matter parser.
 * Supports: unquoted scalars, single-quoted, double-quoted, integers.
 *
 * @param {string} raw - raw markdown string
 * @returns {{ data: Record<string, unknown>, body: string }}
 */
export function parseFrontmatter(raw) {
  if (!raw || typeof raw !== 'string') return { data: {}, body: raw || '' }
  if (!raw.startsWith('---\n') && !raw.startsWith('---\r\n')) return { data: {}, body: raw }
  const end = raw.indexOf('\n---', 4)
  if (end < 0) return { data: {}, body: raw }
  const block = raw.slice(4, end)
  const after = raw.slice(end + 4).replace(/^\r?\n/, '')
  const data = {}
  for (const line of block.split(/\r?\n/)) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const m = trimmed.match(/^([A-Za-z_][\w-]*)\s*:\s*(.*)$/)
    if (!m) continue
    let v = m[2].trim()
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
      v = v.slice(1, -1)
    }
    if (/^-?\d+$/.test(v)) v = parseInt(v, 10)
    data[m[1]] = v
  }
  return { data, body: after }
}

/**
 * Extract the first H1 from a markdown body.
 * @param {string} md
 * @returns {string | null}
 */
function extractTitle(md) {
  const m = md.match(/^#\s+(.+?)\s*$/m)
  return m ? m[1].replace(/`/g, '').trim() : null
}

/**
 * Parse a full compare .md file into structured CompareMeta.
 *
 * The `left` field is ALWAYS forced to `'kerf'` regardless of what the
 * front-matter says. Kerf is always on the left side of any 1v1 comparison.
 *
 * @param {string} raw - raw .md file contents
 * @param {string} [slugFallback] - slug to use if front-matter omits it
 * @returns {CompareMeta}
 */
export function parseCompareMd(raw, slugFallback = '') {
  const { data: fm, body } = parseFrontmatter(raw)

  return {
    slug: String(fm.slug || slugFallback || ''),
    competitor: String(fm.competitor || ''),
    category: String(fm.category || ''),
    hero_tagline: String(fm.hero_tagline || ''),
    // Rule: Kerf is ALWAYS on the left — hard-coded, not from front-matter.
    left: 'kerf',
    right: String(fm.right || fm.slug || slugFallback || ''),
    reviewed_at: fm.reviewed_at ? String(fm.reviewed_at) : null,
    order: typeof fm.order === 'number' ? fm.order : null,
    title: extractTitle(body),
    body,
  }
}
