// Walks `public/compare/*.md` and writes `public/compare-manifest.json`.
//
// Each .md file must have a YAML frontmatter block with at least:
//   slug         — URL slug (e.g. "fusion")
//   competitor   — human-readable tool name (e.g. "Autodesk Fusion 360")
//   category     — one of: cad-mechanical | cad-electronic | bim | jewelry-nurbs | dcc | drafting | cad-sim
//   left         — left-hand label (usually "kerf")
//   right        — right-hand label (tool slug, e.g. "fusion")
//   hero_tagline — one-line subtitle for the compare hub card
//
// Optional frontmatter:
//   order        — integer sort key within category (default: Infinity → alpha)
//   reviewed_at  — YYYY-MM-DD ISO date string
//   features     — structured feature-matrix list (see public/compare/_schema.md)
//
// The generated JSON shape:
//   { "version": 2, "generatedAt": "<ISO>", "items": [...] }
//
// Wired into `predev` and `prebuild:compare` so the SPA always has a fresh
// copy. Works against an empty dir (writes empty items array, exit 0).

import { readdirSync, readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { join } from 'node:path'

const ROOT = process.cwd()

// ---------------------------------------------------------------------------
// YAML frontmatter parser — handles scalars + the `features:` nested list.
//
// Supported subset:
//   foo: value                 → scalar
//   foo: "quoted"              → scalar (quotes stripped)
//   features:                  → start of list
//     - key1: v                  →   new list item
//       key2: v                  →     props at same indent
//       sub:                     →     start of nested object
//         k: v                   →       prop of nested object
//
// We do NOT support inline flow-syntax, anchors, refs, or multi-line strings.
// ---------------------------------------------------------------------------

function parseFrontmatter(md) {
  if (!md.startsWith('---\n') && !md.startsWith('---\r\n')) return { data: {}, body: md }
  const end = md.indexOf('\n---', 4)
  if (end < 0) return { data: {}, body: md }
  const block = md.slice(4, end)
  const after = md.slice(end + 4).replace(/^\r?\n/, '')
  const lines = block.split(/\r?\n/)
  return { data: parseYamlBlock(lines), body: after }
}

function parseYamlBlock(lines) {
  const data = {}
  let i = 0
  while (i < lines.length) {
    const raw = lines[i]
    const line = raw
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) { i++; continue }
    const indent = leadingSpaces(line)
    if (indent !== 0) { i++; continue }
    const m = trimmed.match(/^([A-Za-z_][\w-]*)\s*:\s*(.*)$/)
    if (!m) { i++; continue }
    const key = m[1]
    const val = m[2].trim()
    if (val === '') {
      const block = collectIndentedBlock(lines, i + 1)
      i = block.nextIndex
      if (block.lines.length === 0) {
        data[key] = null
      } else if (block.lines[0].trim().startsWith('- ')) {
        data[key] = parseList(block.lines)
      } else {
        data[key] = parseMapBlock(block.lines)
      }
    } else {
      data[key] = parseScalar(val)
      i++
    }
  }
  return data
}

function leadingSpaces(s) {
  const m = s.match(/^( *)/)
  return m ? m[1].length : 0
}

function collectIndentedBlock(lines, start) {
  const result = []
  let i = start
  while (i < lines.length) {
    const ln = lines[i]
    const trimmed = ln.trim()
    if (trimmed === '' || trimmed.startsWith('#')) { i++; continue }
    const indent = leadingSpaces(ln)
    if (indent === 0) break
    result.push(ln)
    i++
  }
  return { lines: result, nextIndex: i }
}

function parseList(lines) {
  const items = []
  const baseIndent = leadingSpaces(lines[0])
  let i = 0
  while (i < lines.length) {
    const ln = lines[i]
    const indent = leadingSpaces(ln)
    if (indent !== baseIndent || !ln.slice(baseIndent).startsWith('- ')) { i++; continue }
    const itemLines = []
    const firstContent = ln.slice(baseIndent + 2)
    itemLines.push(' '.repeat(baseIndent + 2) + firstContent)
    let j = i + 1
    while (j < lines.length) {
      const lnj = lines[j]
      const trimmedJ = lnj.trim()
      if (trimmedJ === '' || trimmedJ.startsWith('#')) { j++; continue }
      const indj = leadingSpaces(lnj)
      if (indj <= baseIndent) break
      itemLines.push(lnj)
      j++
    }
    items.push(parseMapBlock(itemLines))
    i = j
  }
  return items
}

function parseMapBlock(lines) {
  const data = {}
  if (lines.length === 0) return data
  const baseIndent = leadingSpaces(lines[0])
  let i = 0
  while (i < lines.length) {
    const ln = lines[i]
    const trimmed = ln.trim()
    if (trimmed === '' || trimmed.startsWith('#')) { i++; continue }
    const indent = leadingSpaces(ln)
    if (indent !== baseIndent) { i++; continue }
    const m = trimmed.match(/^([A-Za-z_][\w-]*)\s*:\s*(.*)$/)
    if (!m) { i++; continue }
    const key = m[1]
    const val = m[2].trim()
    if (val === '') {
      const block = collectDeeperBlock(lines, i + 1, baseIndent)
      i = block.nextIndex
      if (block.lines.length === 0) {
        data[key] = null
      } else if (block.lines[0].trim().startsWith('- ')) {
        data[key] = parseList(block.lines)
      } else {
        data[key] = parseMapBlock(block.lines)
      }
    } else {
      data[key] = parseScalar(val)
      i++
    }
  }
  return data
}

function collectDeeperBlock(lines, start, parentIndent) {
  const result = []
  let i = start
  while (i < lines.length) {
    const ln = lines[i]
    const trimmed = ln.trim()
    if (trimmed === '' || trimmed.startsWith('#')) { i++; continue }
    const indent = leadingSpaces(ln)
    if (indent <= parentIndent) break
    result.push(ln)
    i++
  }
  return { lines: result, nextIndex: i }
}

function parseScalar(v) {
  if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
    return v.slice(1, -1)
  }
  if (/^-?\d+$/.test(v)) return parseInt(v, 10)
  if (/^-?\d*\.\d+$/.test(v)) return parseFloat(v)
  // Schema status values use 'yes'/'no' as strings; do NOT cast to boolean.
  return v
}

// ---------------------------------------------------------------------------
// Collect
// ---------------------------------------------------------------------------

const compareDir = join(ROOT, 'public', 'compare')
const items = []

if (existsSync(compareDir)) {
  let files
  try {
    files = readdirSync(compareDir, { withFileTypes: true })
  } catch {
    files = []
  }

  for (const ent of files) {
    if (!ent.isFile() || !ent.name.endsWith('.md')) continue
    if (ent.name.startsWith('_')) continue
    const fullPath = join(compareDir, ent.name)
    let raw
    try {
      raw = readFileSync(fullPath, 'utf8')
    } catch {
      continue
    }
    const { data: fm } = parseFrontmatter(raw)

    const { slug, competitor, category, left, right, hero_tagline } = fm
    if (!slug || !competitor || !category || !left || !right || !hero_tagline) {
      console.warn(`build-compare-manifest: skipping ${ent.name} — missing required frontmatter field(s)`)
      continue
    }

    const item = {
      slug: String(slug),
      competitor: String(competitor),
      category: String(category),
      left: String(left),
      right: String(right),
      hero_tagline: String(hero_tagline),
    }
    if (typeof fm.order === 'number') item.order = fm.order
    if (fm.reviewed_at) item.reviewed_at = String(fm.reviewed_at)
    if (Array.isArray(fm.features) && fm.features.length > 0) {
      item.features = fm.features
    }
    items.push(item)
  }
}

items.sort((a, b) => {
  const ca = a.category.localeCompare(b.category)
  if (ca !== 0) return ca
  const ao = a.order ?? Number.POSITIVE_INFINITY
  const bo = b.order ?? Number.POSITIVE_INFINITY
  if (ao !== bo) return ao - bo
  return a.slug.localeCompare(b.slug)
})

const outputItems = items.map(({ order: _order, ...rest }) => rest)

const outDir = join(ROOT, 'public')
mkdirSync(outDir, { recursive: true })
const outPath = join(outDir, 'compare-manifest.json')

const totalFeatures = outputItems.reduce(
  (sum, it) => sum + (Array.isArray(it.features) ? it.features.length : 0),
  0,
)

const payload = {
  version: 2,
  generatedAt: new Date().toISOString(),
  items: outputItems,
}

writeFileSync(outPath, JSON.stringify(payload, null, 2))

console.log(
  `compare-manifest: wrote ${outputItems.length} CAD(s), ${totalFeatures} feature row(s) to ${outPath}`,
)
