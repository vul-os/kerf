/**
 * BIMView — Three.js viewer for IFC4 files via web-ifc.
 *
 * Props:
 *   ifc_base64  {string}  Base64-encoded .ifc binary (from compile_bim_to_ifc)
 *   className   {string}  Extra CSS classes for the container div
 *
 * web-ifc (npm web-ifc@0.0.77) is the standard browser-side IFC loader. Both it
 * and three are hard dependencies, imported dynamically only to keep the IFC
 * stack out of the initial bundle — so a load failure here means the chunk or
 * its WASM couldn't be fetched, not that the package is missing.
 */
import { useEffect, useImperativeHandle, useRef, useState } from 'react'
import { snapshotCanvas } from '../lib/snapshotHelpers.js'

// web-ifc's emscripten glue resolves its .wasm relative to the executing script,
// which breaks under a hashed bundle. `?url` emits the binary as a static asset
// and hands us its final URL; we feed that to Init()'s locateFile hook below so
// the viewer works offline / air-gapped instead of reaching for a CDN.
import wasmUrl from 'web-ifc/web-ifc.wasm?url'

// Camera framing. FIT_MARGIN pulls back past the exact fit so the model doesn't
// touch the viewport edges.
const FOV_DEG = 60
const FIT_MARGIN = 1.6

// ---------------------------------------------------------------------------
// Lazy dep loader — dynamic import so the IFC stack chunks separately
// ---------------------------------------------------------------------------
async function tryLoadDeps() {
  try {
    const [webifc, three] = await Promise.all([
      import('web-ifc'),
      import('three'),
    ])
    return { deps: { IfcAPI: webifc.IfcAPI, THREE: three } }
  } catch (err) {
    return { loadError: err.message || String(err) }
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function BIMView({ ifc_base64, className = '', viewRef }) {
  const canvasRef = useRef(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [depsError, setDepsError] = useState(null)

  // Editor thumbnail capture: pull whatever's currently on the WebGL
  // canvas. We don't force a render here because the IFC scene already
  // re-renders every frame via animate(); reading the buffer between
  // frames is enough.
  useImperativeHandle(viewRef, () => ({
    snapshot: (opts) => snapshotCanvas(canvasRef.current, opts),
  }), [])

  useEffect(() => {
    let cancelled = false
    let renderer = null
    let animFrame = null

    async function init() {
      setLoading(true)
      setError(null)

      const { deps, loadError } = await tryLoadDeps()
      if (cancelled) return
      setDepsError(loadError ?? null)

      if (!deps || !ifc_base64) {
        setLoading(false)
        return
      }

      const { IfcAPI, THREE } = deps

      try {
        // Decode base64 → Uint8Array
        const binary = atob(ifc_base64)
        const bytes = new Uint8Array(binary.length)
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)

        // Initialise IfcAPI
        const api = new IfcAPI()
        // forceSingleThread: when the page is crossOriginIsolated, Init() would
        // otherwise pick the multi-threaded build and ask for web-ifc-mt.wasm —
        // a different binary we don't bundle. Pin the single-threaded one so the
        // locateFile hook below always hands back a matching module.
        await api.Init(() => wasmUrl, true)
        const modelId = api.OpenModel(bytes)

        // Three.js scene
        const canvas = canvasRef.current
        if (!canvas || cancelled) return

        renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true })
        renderer.setSize(canvas.clientWidth, canvas.clientHeight)
        renderer.setPixelRatio(window.devicePixelRatio)

        const scene = new THREE.Scene()
        scene.background = new THREE.Color(0x0a0a0f)

        const camera = new THREE.PerspectiveCamera(
          FOV_DEG,
          canvas.clientWidth / canvas.clientHeight,
          0.1,
          1000,
        )

        scene.add(new THREE.AmbientLight(0xffffff, 0.5))
        const dir = new THREE.DirectionalLight(0xffffff, 0.9)
        scene.add(dir)

        // Stream all meshes from the IFC model
        const mat = new THREE.MeshLambertMaterial({ color: 0x7799bb, transparent: true, opacity: 0.85 })
        api.StreamAllMeshes(modelId, (flatMesh) => {
          const geoms = flatMesh.geometries
          for (let g = 0; g < geoms.size(); g++) {
            const placedGeom = geoms.get(g)
            const ifcGeom = api.GetGeometry(modelId, placedGeom.geometryExpressID)
            const verts = api.GetVertexArray(ifcGeom.GetVertexData(), ifcGeom.GetVertexDataSize())
            const idxs = api.GetIndexArray(ifcGeom.GetIndexData(), ifcGeom.GetIndexDataSize())

            const positions = new Float32Array(verts.length / 2)
            for (let i = 0; i < verts.length; i += 6) {
              positions[(i / 6) * 3] = verts[i]
              positions[(i / 6) * 3 + 1] = verts[i + 1]
              positions[(i / 6) * 3 + 2] = verts[i + 2]
            }

            const bufGeom = new THREE.BufferGeometry()
            bufGeom.setAttribute('position', new THREE.BufferAttribute(positions, 3))
            bufGeom.setIndex(new THREE.BufferAttribute(idxs, 1))
            bufGeom.computeVertexNormals()

            const mesh3 = new THREE.Mesh(bufGeom, mat)
            // GetVertexArray returns geometry in the element's LOCAL space, in
            // the file's length unit (mm here). placedGeom.flatTransformation is
            // the 4x4 that puts it in the world: it carries the placement, the
            // unit scale (0.001 for mm→m) and the IFC Z-up → three.js Y-up axis
            // swap. Dropping it — as this component did while web-ifc was never
            // actually installed — renders every element 1000x oversized, on its
            // side, and stacked on the origin.
            mesh3.matrix.fromArray(placedGeom.flatTransformation)
            mesh3.matrixAutoUpdate = false
            scene.add(mesh3)
            ifcGeom.delete()
          }
        })

        api.CloseModel(modelId)

        // Frame the model. World units come out of flatTransformation as metres,
        // but a fixed camera would still mis-frame anything that isn't a small
        // building, so fit to the actual bounds instead of hardcoding a pose.
        const box = new THREE.Box3().setFromObject(scene)
        if (!box.isEmpty()) {
          const center = box.getCenter(new THREE.Vector3())
          const size = box.getSize(new THREE.Vector3())
          const extent = Math.max(size.x, size.y, size.z) || 1
          // Distance at which `extent` fills the vertical FOV, with headroom.
          const dist =
            (extent / (2 * Math.tan((FOV_DEG * Math.PI) / 360))) * FIT_MARGIN

          camera.position.set(
            center.x + dist,
            center.y + dist * 0.6,
            center.z + dist,
          )
          camera.near = Math.max(extent / 1000, 0.01)
          camera.far = dist * 10 + extent * 10
          camera.updateProjectionMatrix()
          camera.lookAt(center)

          dir.position.set(
            center.x + extent,
            center.y + extent * 2,
            center.z + extent,
          )
        }

        function animate() {
          if (cancelled) return
          animFrame = requestAnimationFrame(animate)
          renderer.render(scene, camera)
        }
        animate()
        setLoading(false)
      } catch (err) {
        if (!cancelled) {
          setError(err.message || String(err))
          setLoading(false)
        }
      }
    }

    init()
    return () => {
      cancelled = true
      if (animFrame) cancelAnimationFrame(animFrame)
      if (renderer) renderer.dispose()
    }
  }, [ifc_base64])

  // The IFC stack (web-ifc + three) failed to load — a missing chunk, a blocked
  // WASM fetch, or an offline CDN. Nothing the model or the file can fix, so we
  // show the underlying reason rather than a retry the user can't act on.
  if (depsError) {
    return (
      <div
        className={`flex flex-col items-center justify-center gap-3 rounded-lg border border-ink-700 bg-ink-900/50 p-8 text-ink-400 ${className}`}
      >
        <svg className="w-12 h-12 opacity-40" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1}
            d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-2 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"
          />
        </svg>
        <p className="text-sm font-medium">IFC viewer unavailable</p>
        <p className="text-xs text-center max-w-xs opacity-70">
          The 3D viewer failed to load. Check your network connection and reload the page.
        </p>
        <code className="font-mono text-[11px] bg-ink-800 px-2 py-1 rounded max-w-xs truncate">
          {depsError}
        </code>
      </div>
    )
  }

  return (
    <div className={`relative rounded-lg overflow-hidden bg-ink-950 ${className}`}>
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-ink-950/80 z-10">
          <div className="flex flex-col items-center gap-2 text-ink-400">
            <div className="w-6 h-6 border-2 border-kerf-400 border-t-transparent rounded-full animate-spin" />
            <span className="text-xs">Loading IFC model…</span>
          </div>
        </div>
      )}
      {error && (
        <div className="absolute inset-0 flex items-center justify-center bg-ink-950/80 z-10 p-4">
          <div className="text-center text-xs text-red-400 max-w-sm">
            <p className="font-medium mb-1">Render error</p>
            <p className="opacity-70 font-mono">{error}</p>
          </div>
        </div>
      )}
      <canvas
        ref={canvasRef}
        data-testid="bim-canvas"
        className="w-full h-full block"
        style={{ minHeight: 320 }}
      />
    </div>
  )
}
