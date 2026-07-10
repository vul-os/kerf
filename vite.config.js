import { defineConfig, loadEnv } from 'vite'
import { configDefaults } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import pkg from './package.json' with { type: 'json' }

// Build outputs into `dist/` (Vite default). kerf-api serves it via
// StaticFiles at runtime. In dev, Vite serves :5173 directly (HMR) and
// proxies /api + /auth to kerf-server on VITE_API_URL.
// Dev-server-only CSP widening.
//
// index.html ships a strict production Content-Security-Policy whose
// `connect-src` allows same-origin + the hosted API (https://*.kerf.sh). In
// dev and (especially) the Playwright e2e run the browser talks to the API
// cross-origin at VITE_API_URL (e.g. http://localhost:8081), which the prod
// CSP would block — leaving every local-mode spec stuck on the sign-in page
// because /api/config and /auth/bootstrap-local never leave the browser.
//
// This plugin runs ONLY when Vite is serving (`apply: 'serve'`), so it never
// touches the `vite build` output — production keeps its strict CSP. It appends
// the dev API origin (plus localhost ws/http for HMR + any port) to connect-src.
function devCspPlugin(apiOrigin) {
  return {
    name: 'kerf-dev-csp',
    apply: 'serve',
    transformIndexHtml(html) {
      // Anchor on `https://` so we match the real CSP directive and not the
      // explanatory `connect-src 'self'` mention in the comment above it.
      return html.replace(
        /(connect-src 'self'\s+https:\/\/[^;]*)/,
        `$1 ${apiOrigin} http://localhost:* ws://localhost:*`,
      )
    },
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiUrl = env.VITE_API_URL || 'http://localhost:8080'

  return {
    plugins: [react(), tailwindcss(), devCspPlugin(apiUrl)],
    define: {
      __APP_VERSION__: JSON.stringify(pkg.version),
    },
    // Vitest unit tests only. The Playwright e2e specs under tests/e2e/
    // use @playwright/test (their own runner via `npm run test:e2e`) and
    // must not be collected here, or vitest errors on `test.describe`.
    // `.claude/**` is excluded so vitest never scans agent git worktrees
    // (each is a full repo copy — collecting them doubles the suite and
    // surfaces their e2e specs as spurious "@playwright/test not found" fails).
    test: {
      exclude: [...configDefaults.exclude, 'tests/e2e/**', '.claude/**'],
    },
    server: {
      port: 5173,
      proxy: {
        '/api': { target: apiUrl, changeOrigin: true },
        '/auth': { target: apiUrl, changeOrigin: true },
      },
    },
    build: {
      outDir: 'dist',
      emptyOutDir: true,
      rollupOptions: {
        // web-ifc is an optional runtime dep for BIMView; it loads lazily via
        // dynamic import and falls back gracefully when absent (BIMView shows
        // an install-prompt stub). Mark it external so the build doesn't choke
        // when the package isn't installed in the monorepo node_modules.
        external: ['web-ifc'],
        output: {
          // Split the heaviest deps into their own chunks so first paint
          // doesn't drag in Monaco / three.js / JSCAD up-front. occt-import-js,
          // jspdf, and svg2pdf are already dynamically imported and chunk
          // automatically — listing them here would force them eager.
          //
          // Rolldown (Vite 8) requires the function form; the legacy object
          // form throws "manualChunks is not a function".
          manualChunks(id) {
            if (id.includes('node_modules/@monaco-editor/react')) return 'monaco'
            if (id.includes('node_modules/monaco-editor')) return 'monaco'
            if (id.includes('node_modules/occt-import-js')) return 'occt'
            // opencascade.js is the heavyweight Phase 2 OCCT B-rep kernel
            // (~15MB compressed gzipped wasm + glue). Keep it in its own
            // chunk so first paint of non-feature files doesn't drag it in.
            if (id.includes('node_modules/opencascade.js')) return 'opencascade'
            if (id.includes('node_modules/jspdf')) return 'pdf'
            if (id.includes('node_modules/svg2pdf.js')) return 'pdf'
            if (id.includes('node_modules/html2canvas')) return 'pdf'
            // three.js + JSCAD + BVH share a chunk: they're always loaded
            // together by Renderer/jscadRunner.
            if (id.includes('node_modules/three/')) return 'three'
            if (id.includes('node_modules/three-mesh-bvh')) return 'three'
            if (id.includes('node_modules/@jscad/modeling')) return 'three'
            if (id.includes('node_modules/react-markdown')) return 'markdown'
            if (id.includes('node_modules/remark-gfm')) return 'markdown'
            if (id.includes('node_modules/rehype-highlight')) return 'markdown'
            if (id.includes('node_modules/highlight.js')) return 'markdown'
            // tscircuit and its support packages are large (4MB+ uncompressed)
            // and ONLY needed for `.circuit.tsx` files. Both circuit-to-svg
            // (used by SchematicView/PCBView) and the worker's tscircuit
            // import live in this chunk so opening a non-circuit file never
            // drags in the electronics stack. The chunk is lazy-loaded via
            // the worker boundary; SchematicView/PCBView import the much
            // smaller circuit-to-svg directly, so we let it ride along here.
            if (id.includes('node_modules/tscircuit')) return 'tscircuit'
            if (id.includes('node_modules/@tscircuit/')) return 'tscircuit'
            if (id.includes('node_modules/circuit-json')) return 'tscircuit'
            if (id.includes('node_modules/circuit-to-svg')) return 'tscircuit'
            if (id.includes('node_modules/sucrase')) return 'tscircuit'
            return null
          },
        },
      },
    },
    optimizeDeps: {
      include: ['three', '@jscad/modeling'],
      // opencascade.js ships a .wasm asset alongside its JS shim. Vite/Rolldown
      // tries to introspect the package's exports during pre-bundle, follows
      // the binary, and chokes ("Could not load …/opencascade.wasm.wasm").
      // Excluding it from optimizeDeps + treating the .wasm as a static asset
      // (assetsInclude below) lets the worker import the URL via `?url` and
      // hand it to OCCT's `locateFile` hook at runtime.
      //
      // @salusoft89/planegcs has the same shape: emscripten glue + a sibling
      // .wasm. We pass the asset URL through `?url` in sketchSolver.js; mark
      // it excluded from pre-bundling so the dev server doesn't try to evaluate
      // the wasm itself as ESM.
      exclude: ['opencascade.js', '@salusoft89/planegcs'],
    },
    assetsInclude: ['**/*.wasm'],
  }
})
