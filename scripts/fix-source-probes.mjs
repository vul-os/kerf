#!/usr/bin/env node
// fix-source-probes.mjs — make literal-path "source inspection" probes extension-agnostic.
//
// WHY THIS EXISTS
// ---------------
// Several suites assert on a component's SOURCE TEXT rather than its behaviour:
//
//     const src = readFileSync(resolve(__dirname, '../Renderer.jsx'), 'utf8')
//     expect(src).toContain('useImperativeHandle')
//
// A .jsx -> .tsx migration breaks these with ENOENT. Typecheck cannot see it — the path is just a
// string — so it surfaces only when the suite runs, and only after the component has migrated.
//
// The critical property: **an import specifier ending in `.jsx` is still correct** (bundler
// resolution maps it to the `.tsx` file), so this must rewrite ONLY paths used as filesystem
// arguments, never `from './Foo.jsx'` or `import('./Foo.jsx')`. Getting that distinction wrong
// breaks working modules, which is why this is a script with a stated rule rather than a sed.
//
// Ad-hoc versions of this sweep were run five times during the migration and each one found a
// path SHAPE the previous had missed:
//   1. resolve(__dirname, '../X.jsx')
//   2. a read('components/X.jsx') helper over join(root, p)   — fix the helper, not the sites
//   3. a sibling path with no '../' prefix: resolve(__dirname, 'X.jsx')
//   4. the CommonJS form: require('fs'); readFileSync(resolve(__dirname, '../../routes/X.jsx'))
//   5. root-relative: resolve(ROOT, 'src/routes/X.jsx')
// Rather than chase a sixth by hand, this matches any `.jsx`/`.js` string literal that is NOT an
// import specifier and whose `.tsx`/`.ts` sibling exists on disk.
//
// Rewrites each to try the TS extension first and fall back, so the probe works before AND after
// the subject migrates:
//     existsSync(P('tsx')) ? P('tsx') : P('jsx')
//
// NOTE: this handles only the *path* half of the problem. The other half — assertions coupled to
// UNTYPED SYNTAX, e.g. toContain('const MAP = {') failing once the source reads
// `const MAP: Record<..> = {` — cannot be swept, because the string is a valid match until the
// moment its own subject migrates. Write those patterns to tolerate an annotation up front.

import { readFileSync, writeFileSync, existsSync, readdirSync, statSync } from 'node:fs'
import { join, resolve, dirname } from 'node:path'

const ROOT = process.cwd()
const SRC = join(ROOT, 'src')

// A `.jsx`/`.js` string literal, capturing the quote so we can rebuild it faithfully.
const LITERAL = /(['"])([^'"\n]*?)\.(jsx|js)\1/g

function walk(dir) {
  const out = []
  for (const e of readdirSync(dir)) {
    const p = join(dir, e)
    if (statSync(p).isDirectory()) out.push(...walk(p))
    else if (/\.(test|spec)\.(jsx?|tsx?)$/.test(e)) out.push(p)
  }
  return out
}

// True when the literal is an ES/dynamic import specifier — those must be left alone, since
// `./Foo.jsx` still resolves to Foo.tsx under moduleResolution: bundler.
// True when the literal sits in a path-building call. Without this the sweep would also rewrite
// test DATA that merely looks like a filename — `getEditorMode('App.jsx')` in editorModes.test.ts
// is checking extension-to-mode mapping, and src/App.tsx existing must not turn it into a
// filesystem probe.
function isPathArgument(text, matchStart) {
  const before = text.slice(Math.max(0, matchStart - 60), matchStart)
  return /\b(resolve|join|readFileSync|readFile|existsSync|statSync|realpathSync|pathToFileURL)\s*\([^)]*$/.test(before)
}

function isImportSpecifier(text, matchStart) {
  const before = text.slice(Math.max(0, matchStart - 40), matchStart)
  return /\bfrom\s+$|\bimport\s*\(\s*$|\brequire\s*\(\s*$|\bvi\.mock\s*\(\s*$|\bvi\.doMock\s*\(\s*$/.test(before)
}

// Resolve the literal against the roots a probe plausibly uses, and report the TS sibling if the
// JS file is gone and the TS one exists.
function migratedSibling(literalPath, testFile, _args) {
  const tsExt = literalPath.endsWith('x') ? 'tsx' : 'ts'
  for (const base of [dirname(testFile), SRC, ROOT]) {
    const asJs = resolve(base, literalPath)
    if (existsSync(asJs)) return null // still there — nothing to do
    const asTs = asJs.replace(/\.(jsx|js)$/, '.' + tsExt)
    if (existsSync(asTs)) return tsExt
  }
  return null
}

let files = 0
let sites = 0

// Match the WHOLE path-building call, not just the literal inside it. Wrapping only the literal
// is wrong and fails silently: `existsSync('../routes/Editor.tsx')` resolves against process.cwd(),
// not __dirname, so the probe always takes the .jsx branch and ENOENTs. The existsSync test has to
// see the same fully-resolved path the read will use.
const CALL = /((?:\w+\.)?(?:resolve|join))\(([^()]*?),\s*(['"])([^'"\n]*?)\.(jsx|js)\3\)/g

for (const file of walk(SRC)) {
  const src = readFileSync(file, 'utf8')
  let changed = false

  // `import * as fs from 'node:fs'` means the guard must be `fs.existsSync`, not a bare call.
  const nsFs = src.match(/import \* as (\w+) from '(?:node:)?fs'/)
  const guard = nsFs ? `${nsFs[1]}.existsSync` : 'existsSync'

  const out = src.replace(CALL, (whole, fn, args, quote, stem, ext, offset) => {
    if (isImportSpecifier(src, offset)) return whole
    // Skip sites a previous pass (or an agent) already made extension-agnostic.
    if (/existsSync\s*\($/.test(src.slice(Math.max(0, offset - 120), offset).trimEnd())) return whole
    if (src.slice(Math.max(0, offset - 200), offset).includes(`${stem}.${ext === 'jsx' ? 'tsx' : 'ts'}`)) return whole
    const tsExt = migratedSibling(`${stem}.${ext}`, file, args)
    if (!tsExt) return whole
    sites++
    changed = true
    const call = (e) => `${fn}(${args}, ${quote}${stem}.${e}${quote})`
    return `(${guard}(${call(tsExt)}) ? ${call(tsExt)} : ${call(ext)})`
  })

  if (!changed) continue

  let final = out
  if (!nsFs && !/\bexistsSync\b/.test(src)) {
    const fsImport = final.match(/import\s*\{([^}]*)\}\s*from\s*'(node:fs|fs)'/)
    if (fsImport) {
      final = final.replace(fsImport[0], `import {${fsImport[1].replace(/\s*$/, '')}, existsSync } from '${fsImport[2]}'`)
    } else {
      const req = final.match(/const\s*\{([^}]*)\}\s*=\s*require\('fs'\)/)
      if (req) final = final.replace(req[0], `const {${req[1].replace(/\s*$/, '')}, existsSync } = require('fs')`)
      else { console.error(`SKIP (no fs import to extend): ${file}`); continue }
    }
  }

  writeFileSync(file, final)
  files++
}

console.log(`fix-source-probes: rewrote ${sites} probe site(s) across ${files} file(s)`)
