// Syncs `site/docs/` — the markdown the standalone static site (site/docs.html)
// fetches at runtime — from the real docs corpus.
//
// WHY THIS EXISTS
// ---------------
// `site/docs.html` is a curated, hand-ordered subset of the docs: it hardcodes
// a nav of `data-slug` values and fetches `./docs/<slug>.md` for whichever one
// the reader clicks. The markdown next to it was, until this script, copied by
// hand. Predictably it rotted: 29 of its 58 files had drifted from their
// sources, and 9 nav entries pointed at slugs the docs corpus no longer had
// under `docs/` at all. A partial mirror nobody diffs is not a snapshot, it is
// a second, quietly wrong copy of the documentation.
//
// So the subset stays curated — that is a real editorial choice, and the static
// site is deliberately smaller than the in-app docs viewer — but the CONTENTS of
// the subset are now derived, never authored:
//
//   site/docs.html's data-slug list   = the curation (edit by hand)
//   site/docs/<slug>.md               = generated from the corpus (never edit)
//
// `scripts/sync-site-docs.test.mjs` is the gate that keeps those two in step; it
// fails when a file drifts, when a nav slug resolves to nothing, or when
// site/docs holds a file the nav does not reference.
//
// Slug -> source path resolution reuses `public/docs-manifest.json`, the same
// map the in-app docs viewer uses, so the static site and the app can never
// disagree about what a slug means. The manifest is regenerated first (it is a
// build artifact of `docs/**` + `packages/kerf-*/llm_docs/**`), so this script
// is always reading a slug map derived from the sources on disk right now.
//
// Usage:
//   node scripts/sync-site-docs.mjs           # write the sync
//   node scripts/sync-site-docs.mjs --check   # report drift, write nothing (exit 1 if drifted)

import { readFileSync, writeFileSync, readdirSync, unlinkSync, existsSync, mkdtempSync, rmSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const SITE_DOCS_HTML = join(ROOT, 'site', 'docs.html')
const SITE_DOCS_DIR = join(ROOT, 'site', 'docs')
// web/public, not public: the frontend moved out of the repo root and this
// path did not follow it, so every run since died on ENOENT before syncing a
// single file. Nothing in CI calls this script, so it failed unobserved —
// build-docs-manifest.mjs already resolves the same directory this way.
const MANIFEST = join(ROOT, 'web', 'public', 'docs-manifest.json')

export function navSlugs(html) {
  // Strip HTML comments first: the nav carries a maintenance note that spells
  // out the `data-slug` attribute, and a comment must not read as curation.
  const live = html.replace(/<!--[\s\S]*?-->/g, '')
  const slugs = [...live.matchAll(/data-slug="([^"]+)"/g)].map((m) => m[1])
  const seen = new Set()
  const dupes = slugs.filter((s) => (seen.has(s) ? true : (seen.add(s), false)))
  if (dupes.length) {
    throw new Error(`site/docs.html lists duplicate data-slug values: ${[...new Set(dupes)].join(', ')}`)
  }
  return slugs
}

export function slugToPath(manifest) {
  const map = new Map()
  for (const item of manifest.items || []) {
    if (item && item.slug && item.path) map.set(item.slug, item.path)
  }
  return map
}

/**
 * Regenerate the docs manifest so "did site/docs drift" is a question about
 * the SOURCES on disk right now, not a stale build artifact — the same call
 * `predev` / `prebuild:web` make. Returns the parsed manifest object.
 *
 * In --check mode this must not touch the tracked public/docs-manifest.json:
 * that file embeds a `generatedAt` timestamp that changes on every run, so
 * writing it unconditionally made a read-only check dirty the tree on every
 * single invocation (confirmed live: two consecutive `--check` runs produced
 * two different committed-file hashes with no source change — a mutation a
 * check must not make). Instead it is regenerated into a throwaway temp file,
 * read, and the temp file removed before returning — the real manifest is
 * never opened for writing during a check.
 */
export function regenerateManifest({ check = false } = {}) {
  if (!check) {
    execFileSync('node', ['scripts/build-docs-manifest.mjs'], { cwd: ROOT, stdio: 'pipe' })
    return JSON.parse(readFileSync(MANIFEST, 'utf8'))
  }
  const dir = mkdtempSync(join(tmpdir(), 'kerf-docs-manifest-'))
  try {
    const out = join(dir, 'docs-manifest.json')
    execFileSync('node', ['scripts/build-docs-manifest.mjs'], {
      cwd: ROOT,
      stdio: 'pipe',
      env: { ...process.env, DOCS_MANIFEST_OUT: out },
    })
    return JSON.parse(readFileSync(out, 'utf8'))
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

// plan() -> { copies: [{slug, from, to, current, desired}], orphans: [], unresolved: [] }
export function plan({ html, manifest }) {
  const slugs = navSlugs(html)
  const map = slugToPath(manifest)

  const unresolved = slugs.filter((s) => !map.has(s))
  const copies = []
  for (const slug of slugs) {
    const rel = map.get(slug)
    if (!rel) continue
    const from = join(ROOT, rel)
    const to = join(SITE_DOCS_DIR, `${slug}.md`)
    const desired = readFileSync(from, 'utf8')
    const current = existsSync(to) ? readFileSync(to, 'utf8') : null
    copies.push({ slug, from, to, rel, current, desired })
  }

  const present = existsSync(SITE_DOCS_DIR)
    ? readdirSync(SITE_DOCS_DIR).filter((f) => f.endsWith('.md')).map((f) => f.slice(0, -3))
    : []
  const wanted = new Set(slugs)
  const orphans = present.filter((s) => !wanted.has(s))

  return { slugs, copies, orphans, unresolved }
}

function main() {
  const check = process.argv.includes('--check')
  const manifest = regenerateManifest({ check })
  const html = readFileSync(SITE_DOCS_HTML, 'utf8')
  const { slugs, copies, orphans, unresolved } = plan({ html, manifest })

  if (unresolved.length) {
    console.error(
      `site/docs.html references ${unresolved.length} slug(s) that no doc provides: ${unresolved.join(', ')}\n` +
        'Either the doc was deleted (remove the nav entry) or its slug changed (repoint it). ' +
        'This script will not invent a page for a slug the corpus does not have.',
    )
    process.exitCode = 1
    return
  }

  const drifted = copies.filter((c) => c.current !== c.desired)

  if (check) {
    if (drifted.length || orphans.length) {
      for (const c of drifted) {
        console.error(`DRIFT  site/docs/${c.slug}.md != ${c.rel}${c.current === null ? ' (missing)' : ''}`)
      }
      for (const o of orphans) console.error(`ORPHAN site/docs/${o}.md is not referenced by site/docs.html`)
      console.error(`\n${drifted.length} drifted, ${orphans.length} orphaned, out of ${slugs.length} curated slugs.`)
      console.error('Run: node scripts/sync-site-docs.mjs')
      process.exitCode = 1
    } else {
      console.log(`site/docs is in sync: ${slugs.length} curated slugs, 0 drifted, 0 orphaned.`)
    }
    return
  }

  for (const c of drifted) writeFileSync(c.to, c.desired)
  for (const o of orphans) unlinkSync(join(SITE_DOCS_DIR, `${o}.md`))
  console.log(
    `site/docs synced: ${slugs.length} curated slugs, ${drifted.length} rewritten, ${orphans.length} orphan(s) removed.`,
  )
}

if (process.argv[1] && process.argv[1].endsWith('sync-site-docs.mjs')) main()
