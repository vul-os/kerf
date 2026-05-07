// Copies kerf.example.toml → kerf.toml on first run so `npm run dev` works
// without manual setup. Idempotent: refuses to overwrite an existing file.
//
// Also mirrors a couple of wasm assets from node_modules into public/ so the
// dev server can serve them as plain static files. Without this, Vite's
// dev-server scans the package's emscripten glue and trips on the
// `new URL("X.wasm", import.meta.url)` fallback ("ESM integration proposal
// for Wasm not supported"). Mirroring sidesteps that entirely — the package
// is loaded via `make_gcs_wrapper(wasmUrl)` with locateFile pointing at
// /<asset>.wasm, and the fallback line is never reached at runtime.

import { existsSync, copyFileSync, mkdirSync } from 'node:fs'
import { dirname } from 'node:path'

const target = 'kerf.toml'
const source = 'kerf.example.toml'

if (!existsSync(target) && existsSync(source)) {
  copyFileSync(source, target)
  console.log(`init-config: wrote ${target} from ${source}. Edit it to set DB URL, LLM keys, etc.`)
}

// Wasm assets we mirror into public/ for dev-server safety. Add new entries
// here when we adopt another emscripten-built package.
const wasmAssets = [
  {
    src: 'node_modules/@salusoft89/planegcs/dist/planegcs_dist/planegcs.wasm',
    dst: 'public/planegcs.wasm',
  },
]

for (const a of wasmAssets) {
  if (!existsSync(a.src)) continue // package not installed yet — npm install will rerun postinstall
  mkdirSync(dirname(a.dst), { recursive: true })
  copyFileSync(a.src, a.dst)
}
