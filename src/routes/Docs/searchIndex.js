// ----------------------------------------------------------------------------
// Tiny client-side search for the docs corpus. ~80 LOC, no deps.
//
// Indexing strategy:
//   * Per-entry, we tokenize title, headings (H1/H2/H3), and body separately.
//   * For each unique token in an entry we keep an occurrence count plus
//     boosted weight depending on which field it appeared in.
//   * The index is just `{ [token]: [{ entry, score, snippet }, ...] }`,
//     sorted by score descending, capped per-token. That's all we need for
//     "type-ahead, ~20 candidates" search.
//
// Query strategy:
//   * Split the query into lowercase tokens.
//   * For each token, look up postings; merge by entry, sum scores, count
//     matched-token coverage. Multi-token coverage gets a 1.5x boost so a
//     two-word query matching both terms outranks a single-term match.
//   * Build a snippet by finding the first body span that contains a query
//     token and returning ±60 chars of context. Highlight all matched
//     tokens in the snippet for the UI to render bold/yellow.
// ----------------------------------------------------------------------------

const TOKEN_RE = /[a-z0-9][a-z0-9'_-]{1,}/gi
const STOP = new Set([
  'the','a','an','and','or','of','to','in','on','for','at','by','with','from',
  'is','are','was','were','be','been','being','it','this','that','these','those',
  'as','if','so','but','not','no','you','your','we','our','i','can','will','any',
])

function tokenize(s) {
  if (!s) return []
  const out = []
  for (const m of String(s).toLowerCase().matchAll(TOKEN_RE)) {
    const t = m[0]
    if (STOP.has(t)) continue
    out.push(t)
  }
  return out
}

function extractHeadings(md) {
  const out = []
  for (const line of md.split('\n')) {
    const m = line.match(/^(#{1,3})\s+(.+?)\s*$/)
    if (m) out.push({ depth: m[1].length, text: m[2].replace(/`/g, '') })
  }
  return out
}

export function buildIndex(entries) {
  const index = new Map() // token → Map(entryIdx → score)
  const meta = entries.map((e, i) => {
    const headings = extractHeadings(e.body)
    const titleTokens = tokenize(e.title)
    const headingTokens = headings.flatMap((h) => tokenize(h.text))
    const bodyTokens = tokenize(e.body)
    const all = [
      [titleTokens, 8],
      [headingTokens, 4],
      [bodyTokens, 1],
    ]
    for (const [tokens, weight] of all) {
      for (const t of tokens) {
        let postings = index.get(t)
        if (!postings) { postings = new Map(); index.set(t, postings) }
        postings.set(i, (postings.get(i) || 0) + weight)
      }
    }
    return { entry: e, headings, summary: e.summary }
  })
  return { index, meta }
}

export function search(query, idx, limit = 12) {
  const tokens = tokenize(query)
  if (!tokens.length) return []
  const scores = new Map() // entryIdx → { score, hits }
  for (const t of tokens) {
    // Exact match plus a single prefix fallback so "draw" finds "drawing".
    const buckets = []
    const exact = idx.index.get(t)
    if (exact) buckets.push(exact)
    if (!exact && t.length >= 3) {
      for (const [k, v] of idx.index) {
        if (k.startsWith(t)) { buckets.push(v); if (buckets.length > 4) break }
      }
    }
    for (const postings of buckets) {
      for (const [entryIdx, score] of postings) {
        const cur = scores.get(entryIdx) || { score: 0, hits: new Set() }
        cur.score += score
        cur.hits.add(t)
        scores.set(entryIdx, cur)
      }
    }
  }
  const ranked = [...scores.entries()]
    .map(([i, { score, hits }]) => ({
      entry: idx.meta[i].entry,
      headings: idx.meta[i].headings,
      score: hits.size === tokens.length && tokens.length > 1 ? score * 1.5 : score,
      hits,
    }))
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
  return ranked.map((r) => ({
    ...r,
    snippet: makeSnippet(r.entry.body, r.hits),
  }))
}

function makeSnippet(body, hits) {
  const lc = body.toLowerCase()
  let bestIdx = -1
  for (const t of hits) {
    const i = lc.indexOf(t)
    if (i >= 0 && (bestIdx < 0 || i < bestIdx)) bestIdx = i
  }
  if (bestIdx < 0) return body.slice(0, 140).replace(/\s+/g, ' ').trim()
  const start = Math.max(0, bestIdx - 60)
  const end = Math.min(body.length, bestIdx + 100)
  let s = body.slice(start, end).replace(/\s+/g, ' ').trim()
  if (start > 0) s = '...' + s
  if (end < body.length) s = s + '...'
  return s
}
