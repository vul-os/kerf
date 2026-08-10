#!/usr/bin/env node
// build-parity-site.mjs — generate the static comparison pages under site/.
//
// WHY THIS EXISTS
// ---------------
// `public/compare/*.md` holds 57 hand-written, source-cited comparisons against real CAD tools —
// 1,397 capability rows in total. The React app renders them (src/routes/CompareMd.tsx +
// CompareFeatureMatrix.tsx), but the marketing site at site/ is plain static HTML and had no way
// to show any of it. This closes that gap without adding a build step or a framework: read the
// manifest the docs pipeline already produces, emit HTML that uses site/index.html's own tokens.
//
// Two outputs:
//   site/parity.html          — index, grouped by category, one card per tool with a coverage bar
//   site/parity/<slug>.html   — one page per tool, full capability table with sources
//
// NO PRICING. The old React landing carried Kerf pricing tiers; there is no cloud offering now, so
// nothing here quotes a price, a plan or a seat. The competitor `paid` status IS kept, because it
// is a capability qualifier rather than a price: "behind a paid tier" and "included" are not the
// same answer to "can this tool do X", and collapsing them would overstate the competition's
// coverage. It renders as a neutral "paid tier" chip with no number attached.

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
// The frontend moved to web/ (commit 290d3318); the manifest now lives at web/public/, not public/.
const manifest = JSON.parse(readFileSync(join(ROOT, 'web', 'public', 'compare-manifest.json'), 'utf8'))

const esc = (s) =>
  String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

// Competitor status strings are free text ("✅ Full — compound walls, …"), so classify on the
// leading token and keep the prose as the detail line.
function classify(raw) {
  const s = String(raw ?? '').trim()
  const head = s.split(/[\s—-]/)[0].toLowerCase()
  if (head === 'yes' || head === '✅') return 'yes'
  if (head === 'partial' || head === '⚠️') return 'partial'
  if (head === 'paid') return 'paid'
  if (head === 'no' || head === '❌') return 'no'
  return 'unknown'
}

const CATEGORY_LABELS = {
  'bim': 'BIM & AEC',
  'cad-architecture': 'Architecture',
  'cad-electronic': 'Electronics',
  'cad-electronics': 'Electronics',
  'cad-firmware': 'Firmware',
  'cad-mechanical': 'Mechanical',
  'cad-silicon': 'Silicon & EDA',
  'cad-sim': 'Simulation',
  'dcc': 'DCC & rendering',
  'drafting': 'Drafting',
  'hvac-energy': 'HVAC & energy',
  'jewelry-nurbs': 'Jewellery & NURBS',
}

// Same D1–D14 domain codes the old React CompareFeatureMatrix grouped rows under. Kept here so a
// per-tool page can present rows as named, collapsible sections instead of one long flat table.
const DOMAIN_TITLES = {
  D1: 'Geometry & core CAD',
  D2: 'Structural / FEA',
  D3: 'Machine elements',
  D4: 'Thermal / fluid / HVAC',
  D5: 'Aero / marine / space',
  D6: 'Electronics / EDA / silicon',
  D7: 'Manufacturing / CAM',
  D8: 'Civil / infrastructure / geo',
  D9: 'Dynamics / motion / controls',
  D10: 'Electrical / energy / PLC',
  D11: 'Tolerancing / metrology / QA',
  D12: 'Optics / acoustics',
  D13: 'Verticals',
  D14: 'Cost / materials / LCA',
}

// ── shared chrome ────────────────────────────────────────────────────────────

const MARK = '<svg viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="#0a0b0d"/><rect x="7" y="6" width="3.5" height="20" fill="#ffd633"/><polygon points="10.5,16 26,6 26,13" fill="#ffd633"/><polygon points="10.5,16 26,19 26,26" fill="#ffd633"/></svg>'

const GH_ICON = '<svg viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>'

const nav = (base) => `
<nav class="nav">
  <a href="${base}index.html" class="nav-logo">${MARK} kerf</a>
  <div class="nav-links">
    <a href="${base}index.html#domains" class="hide-sm">domains</a>
    <a href="${base}parity.html" class="active">parity</a>
    <a href="${base}index.html#workshop" class="hide-sm">workshop</a>
    <a href="${base}docs.html">docs</a>
    <a href="https://github.com/vul-os/kerf" target="_blank" rel="noreferrer" class="gh">${GH_ICON}<span>github</span></a>
    <a href="${base}index.html#install" class="nav-cta">install</a>
    <a class="vulos-home" href="https://vulos.org" target="_blank" rel="noopener" title="Vulos — open, self-hostable software" aria-label="Vulos — open, self-hostable software"><img src="${base}assets/vulos-logo.png" alt="" width="22" height="22"></a>
  </div>
</nav>`

const footer = (base) => `
<footer class="site-footer">
  <div class="container">
    <div class="footer-inner">
      <div class="footer-left">${MARK} kerf</div>
      <div class="footer-links">
        <a href="${base}docs.html">docs</a>
        <a href="${base}parity.html">parity</a>
        <a href="https://github.com/vul-os/kerf" target="_blank" rel="noreferrer">github</a>
        <a href="https://github.com/vul-os/kerf/blob/main/ROADMAP.md" target="_blank" rel="noreferrer">roadmap</a>
      </div>
      <a class="vulos-foot" href="https://vulos.org" target="_blank" rel="noopener"><img src="${base}assets/vulos-logo.png" alt="" width="18" height="18"><span>Part of <strong>Vulos</strong> — open, self-hostable software</span></a>
      <div class="footer-right">made in south africa 🇿🇦</div>
    </div>
  </div>
</footer>`

// Shared stylesheet. Kept in one place so the two page types cannot drift apart, and written
// against site/index.html's custom properties so a token change there propagates here.
const STYLE = `
:root {
  --bg:#0a0b0d; --surface:#111318; --elevated:#16181f; --panel:#0f1115;
  --border:#23262f; --border-2:#1a1d24;
  --text:#f5f3ee; --text-2:#a6a9b4; --text-3:#8f94a3; --text-4:#3a3d47;
  --dim:#868a97; --code-dim:#8d95a6;
  --gold:#ffd633; --gold-2:#ffe566; --gold-dim:#cca82a;
  --green:#7BB661; --cyan:#6bd4ff; --violet:#c8a2ff;
  --mono:'SF Mono','JetBrains Mono','Menlo','Consolas',ui-monospace,monospace;
  --sans:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
}
*,*::before,*::after { box-sizing:border-box; }
html { scroll-behavior:smooth; }
body { margin:0; background:var(--bg); color:var(--text); font-family:var(--sans); line-height:1.6; -webkit-font-smoothing:antialiased; overflow-x:hidden; }
a { color:var(--text-2); text-decoration:none; }
a:hover { color:var(--text); }
:focus-visible { outline:2px solid var(--gold); outline-offset:2px; border-radius:3px; }

/* Wider than the landing's 1180px: this page's job is a dense capability table, and on a
   1440px+ display the extra room is the difference between a readable grid and a column. */
.container { max-width:1320px; margin:0 auto; padding:0 1.5rem; }

.nav { max-width:1320px; margin:0 auto; padding:1rem 1.5rem; display:flex; align-items:center; justify-content:space-between; }
.nav-logo { display:flex; align-items:center; gap:.55rem; font-family:var(--mono); font-weight:700; font-size:.95rem; color:var(--text); }
.nav-logo svg { width:22px; height:22px; }
.nav-links { display:flex; align-items:center; gap:1.6rem; font-family:var(--mono); font-size:.85rem; }
.nav-links a.active { color:var(--gold); }
.nav-links .gh { display:flex; align-items:center; gap:.4rem; }
.nav-links .gh svg { width:15px; height:15px; }
.nav-cta { border:1px solid var(--gold-dim); color:var(--gold) !important; border-radius:7px; padding:.34rem .8rem; }
.nav-cta:hover { background:rgba(255,214,51,.1); }
.vulos-home img, .vulos-foot img { display:block; border-radius:5px; }

section { padding:3.5rem 0; }
.hero { padding:3.25rem 0 2.5rem; border-bottom:1px solid var(--border-2); }
/* Two columns. The copy is capped at 46rem for readability, so with the stats stacked
   underneath the right half of the hero sat empty above ~1200px and the page read as one
   narrow column. Stats now occupy that space. */
.hero-grid { display:grid; grid-template-columns:minmax(0,1.15fr) minmax(320px,.85fr); gap:3.5rem; align-items:start; }
@media (max-width:980px) { .hero-grid { grid-template-columns:1fr; gap:2rem; } }
.eyebrow { font-family:var(--mono); font-size:.75rem; letter-spacing:.16em; text-transform:uppercase; color:var(--gold-dim); margin:0 0 .7rem; }
h1 { font-size:clamp(1.9rem,4vw,2.9rem); line-height:1.12; letter-spacing:-.02em; margin:0 0 .9rem; }
h2 { font-size:clamp(1.25rem,2.2vw,1.6rem); letter-spacing:-.01em; margin:0 0 1.1rem; }
.lede { font-size:1.03rem; color:var(--text-3); max-width:46rem; margin:0; line-height:1.72; }

/* Summary strip — auto-fit means it reflows on its own instead of needing a breakpoint each. */
.stat-strip { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:1px; background:var(--border-2); border:1px solid var(--border-2); border-radius:14px; overflow:hidden; }
.hero .stat-strip { grid-template-columns:1fr 1fr; }
.stat { background:var(--surface); padding:1.15rem 1.25rem; }
.stat b { display:block; font-family:var(--mono); font-size:1.65rem; color:var(--gold); font-weight:700; letter-spacing:-.02em; line-height:1.1; }
.stat span { display:block; margin-top:.25rem; font-size:.8rem; color:var(--text-3); line-height:1.45; }

.cat { margin-bottom:2.75rem; }
.cat-head { display:flex; align-items:baseline; gap:.75rem; margin-bottom:1.1rem; padding-bottom:.55rem; border-bottom:1px solid var(--border-2); }
.cat-head h2 { margin:0; }
.cat-head .count { font-family:var(--mono); font-size:.78rem; color:var(--dim); }

.tool-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(310px,1fr)); gap:1rem; }
.tool { display:flex; flex-direction:column; gap:.75rem; border:1px solid var(--border); border-radius:13px; background:var(--surface); padding:1.1rem 1.2rem; transition:border-color .15s, background .15s, transform .15s; }
.tool:hover { border-color:var(--text-4); background:var(--elevated); transform:translateY(-2px); }
.tool h3 { margin:0; font-size:1rem; color:var(--text); letter-spacing:-.01em; }
.tool p { margin:0; font-size:.85rem; color:var(--text-3); line-height:1.6; }
.tool .meta { display:flex; align-items:center; justify-content:space-between; gap:.75rem; font-family:var(--mono); font-size:.72rem; color:var(--dim); margin-top:auto; padding-top:.3rem; }

/* Coverage bar — proportional, with a text equivalent beneath so it is not colour-only. */
.bar { display:flex; height:6px; border-radius:999px; overflow:hidden; background:var(--border-2); }
.bar i { display:block; height:100%; }
.bar .yes { background:var(--green); }
.bar .partial { background:var(--gold); }
.bar .paid { background:var(--violet); }
.bar .no { background:var(--text-4); }
.bar-key { font-family:var(--mono); font-size:.72rem; color:var(--text-3); }

/* Capability table. It scrolls inside its own box rather than pushing the page sideways. */
.table-wrap { overflow-x:auto; border:1px solid var(--border-2); border-radius:12px; background:var(--surface); }
table { border-collapse:collapse; width:100%; min-width:640px; font-size:.88rem; }
thead th { position:sticky; top:0; background:var(--elevated); text-align:left; font-family:var(--mono); font-size:.74rem; letter-spacing:.09em; text-transform:uppercase; color:var(--text-3); font-weight:600; padding:.7rem .9rem; border-bottom:1px solid var(--border); }
tbody td { padding:.72rem .9rem; border-bottom:1px solid var(--border-2); vertical-align:top; color:var(--text-2); }
tbody tr:last-child td { border-bottom:0; }
tbody tr:hover td { background:rgba(255,255,255,.015); }
td.feat { color:var(--text); width:38%; }
td.feat small { display:block; font-family:var(--mono); font-size:.7rem; color:var(--dim); margin-top:.2rem; }
.chip { display:inline-block; font-family:var(--mono); font-size:.72rem; padding:.14rem .5rem; border-radius:999px; border:1px solid transparent; white-space:nowrap; }
.chip.yes { color:var(--green); border-color:rgba(123,182,97,.4); background:rgba(123,182,97,.09); }
.chip.partial { color:var(--gold); border-color:rgba(255,214,51,.35); background:rgba(255,214,51,.08); }
.chip.paid { color:var(--violet); border-color:rgba(200,162,255,.35); background:rgba(200,162,255,.08); }
.chip.no { color:var(--text-3); border-color:var(--border); }
.chip.unknown { color:var(--dim); border-color:var(--border); }
td .note { display:block; margin-top:.3rem; font-size:.8rem; color:var(--text-3); line-height:1.5; }
td .src { font-family:var(--mono); font-size:.71rem; color:var(--code-dim); word-break:break-word; }
td code { font-family:var(--mono); font-size:.74rem; color:var(--code-dim); }

/* Column pinning — the feature name stays put while Kerf / competitor columns scroll under it,
   so a capability is never off-screen while you're reading its verdict. Needs an opaque
   background per row state or the scrolling columns show through. */
td.feat, th.feat { position:sticky; left:0; z-index:1; background:var(--surface); }
thead th.feat { z-index:2; background:var(--elevated); }
tbody tr:hover td.feat { background:#15171d; }

/* Search + category filter (index page only). Vanilla JS, no framework — filters .tool cards by
   name/slug/tagline and by category, matching the old React landing's search box + pill row. */
.filter-bar { display:flex; flex-wrap:wrap; align-items:center; gap:.75rem 1rem; margin:1.6rem 0 .25rem; }
.search-wrap { position:relative; flex:1 1 260px; max-width:22rem; }
.search-wrap svg { position:absolute; left:.8rem; top:50%; transform:translateY(-50%); width:14px; height:14px; color:var(--text-3); pointer-events:none; }
#parity-search { width:100%; background:var(--surface); border:1px solid var(--border); color:var(--text); border-radius:9px; padding:.55rem .9rem .55rem 2.1rem; font-size:.86rem; font-family:var(--sans); }
#parity-search::placeholder { color:var(--text-4); }
#parity-search:focus { border-color:var(--gold-dim); outline:none; }
.pills { display:flex; flex-wrap:wrap; gap:.45rem; }
.pill { font-family:var(--mono); font-size:.74rem; color:var(--text-3); background:var(--surface); border:1px solid var(--border); border-radius:999px; padding:.36rem .8rem; cursor:pointer; transition:border-color .15s,color .15s,background .15s; }
.pill:hover { color:var(--text); border-color:var(--text-4); }
.pill.active { color:var(--gold); border-color:var(--gold-dim); background:rgba(255,214,51,.08); }
.filter-status { font-family:var(--mono); font-size:.78rem; color:var(--dim); margin:.9rem 0 0; min-height:1.2em; }
.filter-status button { font:inherit; color:var(--gold-dim); background:none; border:0; padding:0; cursor:pointer; text-decoration:underline; text-underline-offset:2px; }
.filter-status button:hover { color:var(--gold); }
.tool[hidden], .cat[hidden] { display:none; }
.no-matches { display:none; font-size:.85rem; color:var(--text-3); padding:1.5rem 0; }
.no-matches.show { display:block; }
.scroll-mt { scroll-margin-top:20px; }

/* Per-domain expand/collapse on a tool's detail page — matches the old React matrix's D1–D14
   <details> sections instead of one long flat table. */
.domain { border:1px solid var(--border-2); border-radius:12px; background:var(--surface); overflow:hidden; margin-bottom:.85rem; }
.domain:last-child { margin-bottom:0; }
.domain > summary { display:flex; align-items:center; justify-content:space-between; gap:1rem; padding:.85rem 1.1rem; cursor:pointer; list-style:none; font-family:var(--mono); }
.domain > summary::-webkit-details-marker { display:none; }
.domain > summary:hover { background:var(--elevated); }
.domain-title { display:flex; align-items:baseline; gap:.6rem; font-family:var(--sans); font-size:.92rem; color:var(--text); }
.domain-title .code { font-family:var(--mono); font-size:.72rem; color:var(--text-3); }
.domain-meta { display:flex; align-items:center; gap:.75rem; font-size:.75rem; color:var(--text-3); flex-shrink:0; }
.domain-caret { display:inline-block; color:var(--text-3); transition:transform .15s; }
.domain[open] > summary .domain-caret { transform:rotate(90deg); }
.domain .table-wrap { border:0; border-top:1px solid var(--border-2); border-radius:0; }

.back { display:inline-flex; align-items:center; gap:.4rem; font-family:var(--mono); font-size:.8rem; color:var(--text-3); margin-bottom:1.1rem; }
.legend { display:flex; flex-wrap:wrap; gap:.5rem 1rem; margin:1.4rem 0 0; padding:0; list-style:none; font-family:var(--mono); font-size:.75rem; color:var(--text-3); }

.honest { margin-top:2.25rem; border:1px solid var(--border); border-left:2px solid var(--gold-dim); border-radius:10px; background:var(--panel); padding:1.05rem 1.2rem; }
.honest p { margin:0; font-size:.86rem; color:var(--text-3); line-height:1.68; }

.site-footer { border-top:1px solid var(--border-2); padding:2.25rem 0; margin-top:2rem; }
.footer-inner { display:flex; flex-wrap:wrap; align-items:center; gap:1rem 2rem; font-family:var(--mono); font-size:.8rem; color:var(--dim); }
.footer-left { display:flex; align-items:center; gap:.5rem; color:var(--text); font-weight:700; }
.footer-left svg { width:20px; height:20px; }
.footer-links { display:flex; flex-wrap:wrap; gap:1.2rem; }
.vulos-foot { display:flex; align-items:center; gap:.45rem; }
.footer-right { margin-left:auto; }

@media (max-width:680px) {
  .nav-links { gap:1rem; }
  .nav-links a.hide-sm { display:none; }
  .footer-right { margin-left:0; }
  section { padding:2.5rem 0; }
}
/* Same fix as site/index.html's own nav (commit fa8b6fe5): below ~430px the nav row still has
   more unshrinkable content than the bar can give it — here worse than index.html's, because
   this page keeps its own "parity" link visible (un-hidden, it's the active-page marker) instead
   of hiding it like index.html does. Drop the github WORD and tighten the gap the same way. */
@media (max-width:430px) {
  .nav-links { gap:.6rem; }
  .nav-links .gh { gap:0; }
  .nav-links .gh span { display:none; }
}
@media (prefers-reduced-motion:reduce) {
  html { scroll-behavior:auto; }
  .tool { transition:none; }
  .tool:hover { transform:none; }
}
`

function page({ title, description, base, body }) {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="dark">
<title>${esc(title)}</title>
<meta name="description" content="${esc(description)}">
<meta property="og:title" content="${esc(title)}">
<meta property="og:description" content="${esc(description)}">
<meta property="og:type" content="website">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='6' fill='%230a0b0d'/%3E%3Crect x='7' y='6' width='3.5' height='20' fill='%23ffd633'/%3E%3C/svg%3E">
<style>${STYLE}</style>
</head>
<body>
${nav(base)}
<main>
${body}
</main>
${footer(base)}
</body>
</html>
`
}

// ── coverage ─────────────────────────────────────────────────────────────────

function coverage(item) {
  const kerf = { yes: 0, partial: 0, no: 0, unknown: 0 }
  const comp = { yes: 0, partial: 0, paid: 0, no: 0, unknown: 0 }
  for (const f of item.features) {
    const k = classify(f.kerf?.status)
    kerf[k === 'paid' ? 'yes' : k] += 1   // Kerf has no paid tier; the status never occurs.
    comp[classify(f.competitor?.status)] += 1
  }
  return { kerf, comp, total: item.features.length }
}

function bar(counts, total) {
  const seg = (cls) => {
    const n = counts[cls] || 0
    return n ? `<i class="${cls}" style="width:${((n / total) * 100).toFixed(2)}%"></i>` : ''
  }
  return `<div class="bar" role="img" aria-label="${counts.yes || 0} of ${total} supported">${seg('yes')}${seg('partial')}${seg('paid')}${seg('no')}</div>`
}

// ── index page ───────────────────────────────────────────────────────────────

const items = [...manifest.items].sort((a, b) => a.competitor.localeCompare(b.competitor))
const byCat = new Map()
for (const it of items) {
  const key = CATEGORY_LABELS[it.category] || it.category
  if (!byCat.has(key)) byCat.set(key, [])
  byCat.get(key).push(it)
}
const totalRows = items.reduce((n, it) => n + it.features.length, 0)

// Category filter pills — one per distinct category id, sorted the same way the section headers
// below are (largest group first), so the pill order matches the page order it filters.
const catIds = new Map() // category id -> { label, count }
for (const it of items) {
  const label = CATEGORY_LABELS[it.category] || it.category
  const cur = catIds.get(it.category) || { label, count: 0 }
  cur.count += 1
  catIds.set(it.category, cur)
}
const pillList = [...catIds.entries()].sort((a, b) => b[1].count - a[1].count)

// Kerf's own gaps. Surfaced deliberately: with the rows drawn from Kerf's capability list it
// scores "yes" on 98.9% of them, so a page that does not lead with the exceptions is marketing.
const shortfalls = []
for (const it of items) {
  for (const f of it.features) {
    const st = f.kerf?.status
    if (st !== 'yes') shortfalls.push({ tool: it.competitor, slug: it.slug, name: f.name, status: st })
  }
}
const kerfNo = shortfalls.filter((s) => s.status === 'no').length
const kerfPartial = shortfalls.filter((s) => s.status !== 'no').length

const catSections = [...byCat.entries()]
  .sort((a, b) => b[1].length - a[1].length)
  .map(([label, list]) => {
    const catId = list[0]?.category ?? ''
    const cards = list.map((it) => {
      const { kerf, comp, total } = coverage(it)
      // Search haystack: competitor name + slug + tagline, lowercased once at build time so the
      // filter script does a plain substring test with no runtime normalisation.
      const q = esc(`${it.competitor} ${it.slug} ${it.hero_tagline || ''}`.toLowerCase())
      return `
        <a class="tool" href="./parity/${esc(it.slug)}.html" data-cat="${esc(catId)}" data-q="${q}">
          <h3>Kerf vs ${esc(it.competitor)}</h3>
          <p>${esc(it.hero_tagline || '')}</p>
          ${bar(kerf, total)}
          <span class="bar-key">${comp.yes} of these ${total} are included in ${esc(it.competitor)}${comp.paid ? `, ${comp.paid} behind a paid tier` : ''}</span>
          <span class="meta"><span>${total} capabilities</span><span>reviewed ${esc(it.reviewed_at || '—')}</span></span>
        </a>`
    }).join('')
    return `
      <div class="cat" data-cat="${esc(catId)}">
        <div class="cat-head"><h2>${esc(label)}</h2><span class="count">${list.length} tool${list.length === 1 ? '' : 's'}</span></div>
        <div class="tool-grid">${cards}</div>
      </div>`
  }).join('')

const searchIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>'

const filterBar = `
<div class="filter-bar">
  <div class="search-wrap">
    ${searchIcon}
    <input id="parity-search" type="search" placeholder="Search tools… (e.g. FreeCAD, SPICE, BIM)" aria-label="Search comparisons">
  </div>
  <div class="pills" role="group" aria-label="Filter by category">
    <button type="button" class="pill active" data-cat="">All</button>
    ${pillList.map(([id, meta]) => `<button type="button" class="pill" data-cat="${esc(id)}">${esc(meta.label)}</button>`).join('')}
  </div>
</div>
<p class="filter-status" id="parity-filter-status" role="status"></p>`

// Vanilla JS — this is a static site with no framework, so search + category filtering (the old
// React landing's two headline interactions) has to be plain DOM manipulation. It only touches
// the "by tool" card grid below; the "Read this first" intro and "Where Kerf falls short" table
// are unaffected by any filter state.
const filterScript = `
<script>
(function () {
  var search = document.getElementById('parity-search')
  var pills = Array.prototype.slice.call(document.querySelectorAll('.pill'))
  var cats = Array.prototype.slice.call(document.querySelectorAll('.cat[data-cat]'))
  var status = document.getElementById('parity-filter-status')
  var noMatches = document.getElementById('parity-no-matches')
  var activeCat = ''

  function apply() {
    var q = search.value.trim().toLowerCase()
    var shown = 0
    cats.forEach(function (cat) {
      var catMatches = !activeCat || cat.getAttribute('data-cat') === activeCat
      var anyVisible = false
      Array.prototype.slice.call(cat.querySelectorAll('.tool')).forEach(function (tool) {
        var visible = catMatches && (!q || tool.getAttribute('data-q').indexOf(q) !== -1)
        tool.hidden = !visible
        if (visible) { anyVisible = true; shown++ }
      })
      cat.hidden = !anyVisible
    })
    noMatches.classList.toggle('show', shown === 0)
    var filtering = q.length > 0 || activeCat !== ''
    if (!filtering) {
      status.innerHTML = ''
    } else {
      var label = activeCat ? (pills.filter(function (p) { return p.getAttribute('data-cat') === activeCat })[0] || {}).textContent : ''
      var bits = [shown === 0 ? 'No results' : (shown + ' comparison' + (shown === 1 ? '' : 's'))]
      if (q) bits.push('for "' + search.value.trim() + '"')
      if (label) bits.push('in ' + label)
      status.innerHTML = bits.join(' ') + ' — <button type="button" id="parity-clear">clear</button>'
      var clear = document.getElementById('parity-clear')
      if (clear) clear.addEventListener('click', function () {
        search.value = ''
        activeCat = ''
        pills.forEach(function (p) { p.classList.toggle('active', p.getAttribute('data-cat') === '') })
        apply()
      })
    }
  }

  search.addEventListener('input', apply)
  pills.forEach(function (pill) {
    pill.addEventListener('click', function () {
      activeCat = pill.getAttribute('data-cat')
      pills.forEach(function (p) { p.classList.toggle('active', p === pill) })
      apply()
    })
  })
})()
</script>`

const indexBody = `
<section class="hero">
  <div class="container hero-grid">
    <div>
      <p class="eyebrow">Feature parity</p>
      <h1>Feature parity, line by line</h1>
      <p class="lede">Every row is a specific capability, checked against the competitor's own documentation and against a named file in this repository. Each claim links to its source.</p>
      <p class="lede" style="margin-top:.9rem"><strong style="color:var(--text-2)">Read this first:</strong> the rows are <em>Kerf's</em> capability list, so this measures how much of what Kerf does a given tool also does — not how much of that tool Kerf replaces. Every one of these products does things Kerf has no answer for at all, and those things are not rows here. Treat it as a coverage map, never as a score.</p>
    </div>
    <div class="stat-strip">
      <div class="stat"><b>${items.length}</b><span>tools surveyed</span></div>
      <div class="stat"><b>${totalRows.toLocaleString('en')}</b><span>sourced capability rows</span></div>
      <div class="stat"><b>${byCat.size}</b><span>disciplines</span></div>
      <div class="stat"><b>${kerfNo + kerfPartial}</b><span>rows Kerf does not fully cover</span></div>
    </div>
  </div>
</section>
<section>
  <div class="container">
    <div class="cat">
      <div class="cat-head"><h2>Where Kerf falls short</h2><span class="count">${shortfalls.length} of ${totalRows} rows</span></div>
      <p class="lede" style="margin:0 0 1.1rem">These are every row across all ${items.length} reports where Kerf is not a straight yes. It is a short list because of how the rows were chosen, not because the gaps are small — see the note above.</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th class="feat">Capability</th><th>Kerf</th><th>Surfaced comparing against</th></tr></thead>
          <tbody>${shortfalls.map((g) => `
            <tr>
              <td class="feat">${esc(g.name)}</td>
              <td><span class="chip ${g.status === 'no' ? 'no' : 'partial'}">${esc(g.status || 'unknown')}</span></td>
              <td><a href="./parity/${esc(g.slug)}.html">${esc(g.tool)}</a></td>
            </tr>`).join('')}</tbody>
        </table>
      </div>
    </div>
    <div class="honest">
      <p><strong>How to read this.</strong> A competitor row marked <em>paid tier</em> means the tool does have the capability, but behind an extension, add-on or metered service — a different answer to “can I do this today” than “included”, so it is counted separately rather than folded into either. Kerf has no tiers, so its rows are only yes, partial or no.</p>
      <p style="margin-top:.8rem"><strong>What this page is not.</strong> It is not a verdict, and the totals are not scores. The rows were written from Kerf's feature set, which is why Kerf is a yes on ${((totalRows - shortfalls.length) / totalRows * 100).toFixed(1)}% of them — that number says something about how the list was built, not about the products. A tool scoring low here may be far better than Kerf at the work you actually do. If you are choosing between them, read the rows in your discipline and ignore the counts.</p>
    </div>
  </div>
</section>
<section id="by-tool" class="scroll-mt">
  <div class="container">
    <div class="cat-head" style="border-bottom:0; margin-bottom:.5rem; padding-bottom:0"><h2>Browse by tool</h2></div>
    <p class="lede" style="margin:0">Search or filter by discipline — every card still opens the same full, sourced capability table.</p>
    ${filterBar}
    <div class="no-matches" id="parity-no-matches">No comparisons match your search.</div>
    ${catSections}
  </div>
</section>${filterScript}`

mkdirSync(join(ROOT, 'site', 'parity'), { recursive: true })
writeFileSync(
  join(ROOT, 'site', 'parity.html'),
  page({
    title: 'Kerf — feature parity against 57 CAD tools',
    description: `Kerf compared against ${items.length} CAD, EDA and simulation tools across ${totalRows} specific capabilities, each with a documentation source.`,
    base: './',
    body: indexBody,
  }),
)

// ── detail pages ─────────────────────────────────────────────────────────────

for (const it of items) {
  const { kerf, comp, total } = coverage(it)

  const byDomain = new Map()
  for (const f of it.features) {
    const d = f.domain || '—'
    if (!byDomain.has(d)) byDomain.set(d, [])
    byDomain.get(d).push(f)
  }

  // Domain rows in D1..D14 order (falling back to encounter order for any unrecognised code),
  // each its own collapsible <details> section with a "N of M matched" count — matching the old
  // React CompareFeatureMatrix's per-CAD layout instead of one long flat table.
  const domainKeys = [...byDomain.keys()].sort((a, b) => {
    const ai = Object.keys(DOMAIN_TITLES).indexOf(a)
    const bi = Object.keys(DOMAIN_TITLES).indexOf(b)
    if (ai === -1 && bi === -1) return a.localeCompare(b)
    if (ai === -1) return 1
    if (bi === -1) return -1
    return ai - bi
  })

  const domainSections = domainKeys.map((domain) => {
    const feats = byDomain.get(domain)
    const matched = feats.filter((f) => classify(f.kerf?.status) === 'yes' && classify(f.competitor?.status) === 'yes').length
    const rows = feats.map((f) => {
      const kc = classify(f.kerf?.status)
      const cc = classify(f.competitor?.status)
      // Keep the competitor's own prose after the leading token — it is the substance of the claim.
      const compProse = String(f.competitor?.status ?? '').replace(/^\S+\s*[—-]?\s*/, '').trim()
      const src = f.competitor?.source
      return `
        <tr>
          <td class="feat">${esc(f.name)}</td>
          <td>
            <span class="chip ${kc}">${kc}</span>
            ${f.kerf?.evidence ? `<code class="note">${esc(f.kerf.evidence)}</code>` : ''}
          </td>
          <td>
            <span class="chip ${cc}">${cc === 'paid' ? 'paid tier' : cc}</span>
            ${compProse ? `<span class="note">${esc(compProse)}</span>` : ''}
            ${src ? `<a class="src" href="${esc(src)}" target="_blank" rel="noreferrer nofollow">source ↗</a>` : ''}
          </td>
        </tr>`
    }).join('')
    const title = DOMAIN_TITLES[domain] || domain
    return `
      <details class="domain">
        <summary>
          <span class="domain-title"><span class="code">${esc(domain)}</span> ${esc(title)}</span>
          <span class="domain-meta"><span>${matched} of ${feats.length} matched</span><span class="domain-caret" aria-hidden="true">›</span></span>
        </summary>
        <div class="table-wrap">
          <table>
            <thead><tr><th class="feat">Capability</th><th>Kerf</th><th>${esc(it.competitor)}</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </details>`
  }).join('')

  const body = `
<section class="hero">
  <div class="container">
    <a class="back" href="../parity.html">← all parity reports</a>
    <p class="eyebrow">${esc(CATEGORY_LABELS[it.category] || it.category)}</p>
    <h1>Kerf vs ${esc(it.competitor)}</h1>
    <p class="lede">${esc(it.hero_tagline || '')}</p>
    <div class="stat-strip">
      <div class="stat"><b>${kerf.yes}/${total}</b><span>in Kerf today</span></div>
      <div class="stat"><b>${comp.yes}/${total}</b><span>in ${esc(it.competitor)} (included)</span></div>
      <div class="stat"><b>${comp.paid}</b><span>behind a paid tier</span></div>
      <div class="stat"><b>${esc(it.reviewed_at || '—')}</b><span>last reviewed</span></div>
    </div>
  </div>
</section>
<section>
  <div class="container">
    <p class="lede" style="margin:0 0 1.1rem">Grouped by discipline (D1–D14), same as Kerf's own capability list. Click a section to expand it.</p>
    ${domainSections}
    <ul class="legend">
      <li><span class="chip yes">yes</span> shipped</li>
      <li><span class="chip partial">partial</span> works with limits</li>
      <li><span class="chip paid">paid tier</span> present, but behind an add-on or meter</li>
      <li><span class="chip no">no</span> not available</li>
    </ul>
    <div class="honest">
      <p><strong>Corrections welcome.</strong> These rows are read off published documentation on the date shown and go stale as products ship. If a row is wrong, <a href="https://github.com/vul-os/kerf/issues" target="_blank" rel="noreferrer">open an issue</a> — the source file is <code>public/compare/${esc(it.slug)}.md</code> and every claim in it carries a link.</p>
    </div>
  </div>
</section>`

  writeFileSync(
    join(ROOT, 'site', 'parity', `${it.slug}.html`),
    page({
      title: `Kerf vs ${it.competitor} — feature parity`,
      description: `${total} specific capabilities compared between Kerf and ${it.competitor}, each with a documentation source.`,
      base: '../',
      body,
    }),
  )
}

console.log(`build-parity-site: wrote site/parity.html + ${items.length} detail pages (${totalRows} rows)`)
