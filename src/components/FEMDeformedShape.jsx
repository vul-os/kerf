// Deformed-shape 3-D overlay for FEM results.
//
// Renders a wireframe/surface of the mesh morphed by node_displacements * scale,
// coloured by displacement magnitude or von-Mises stress (DG0 per-cell values
// broadcast to vertices for display).
//
// Because FEM results don't include vertex connectivity (we only get the flat
// node_displacements array), this component renders a point cloud as a proxy
// when no mesh geometry is available.  When the parent eventually passes a
// BufferGeometry (via a `geometry` prop), the full morphed surface is shown.
//
// Props:
//   nodeDisplacements  [{ux,uy,uz,mag}, ...] per-node
//   stresses           [float, ...]          per-cell von-Mises (DG0)
//   scale              number                visual scale factor (1–200)
//   colorMode          'displacement'|'vonmises'
//   maxDisplacement    number                used to normalise colour bar
//   maxStress          number                used to normalise colour bar
//   geometry           THREE.BufferGeometry  optional; if absent → point cloud

import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import {
  applyDisplacementScale,
  displacementMagnitudes,
  buildDisplacementColors,
  scalarToRGB,
} from '../lib/femDisplacement.js'

export default function DeformedShapeOverlay({
  nodeDisplacements,
  stresses,
  scale,
  colorMode,
  maxDisplacement,
  maxStress,
  geometry: externalGeometry,
}) {
  const canvasRef = useRef(null)
  const stateRef = useRef({})

  // Bootstrap Three.js once
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true })
    renderer.setPixelRatio(window.devicePixelRatio)
    renderer.setSize(canvas.clientWidth, canvas.clientHeight)

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(45, canvas.clientWidth / canvas.clientHeight, 0.001, 1000)
    camera.position.set(0, 0, 3)

    // Simple orbit: drag to rotate
    let isDragging = false
    let lastX = 0
    let lastY = 0
    const euler = new THREE.Euler(0.2, 0.3, 0, 'YXZ')

    function onMouseDown(e) { isDragging = true; lastX = e.clientX; lastY = e.clientY }
    function onMouseUp() { isDragging = false }
    function onMouseMove(e) {
      if (!isDragging) return
      euler.y += (e.clientX - lastX) * 0.01
      euler.x += (e.clientY - lastY) * 0.01
      lastX = e.clientX; lastY = e.clientY
      scene.rotation.setFromEuler(euler)
    }
    canvas.addEventListener('mousedown', onMouseDown)
    window.addEventListener('mouseup', onMouseUp)
    window.addEventListener('mousemove', onMouseMove)

    let animId
    function animate() {
      animId = requestAnimationFrame(animate)
      renderer.render(scene, camera)
    }
    animate()

    stateRef.current = { renderer, scene, camera, euler }

    return () => {
      cancelAnimationFrame(animId)
      renderer.dispose()
      canvas.removeEventListener('mousedown', onMouseDown)
      window.removeEventListener('mouseup', onMouseUp)
      window.removeEventListener('mousemove', onMouseMove)
    }
  }, [])

  // Rebuild mesh/point-cloud whenever data or settings change
  useEffect(() => {
    const { scene } = stateRef.current
    if (!scene || !nodeDisplacements?.length) return

    // Remove previous mesh
    scene.clear()

    // Add ambient + directional light
    scene.add(new THREE.AmbientLight(0xffffff, 0.6))
    const dir = new THREE.DirectionalLight(0xffffff, 0.8)
    dir.position.set(1, 2, 3)
    scene.add(dir)

    const n = nodeDisplacements.length

    // Build original positions array.
    // Without external geometry we use the displacement vectors themselves
    // as approximate relative positions (ux,uy,uz are small but nonzero near
    // loaded regions — this is a degenerate proxy; the real use-case is when
    // the caller passes geometry from the mesh viewer).
    let origPositions
    if (externalGeometry) {
      origPositions = externalGeometry.attributes.position.array
    } else {
      // Proxy: place nodes on a unit sphere using their index.
      // The morphed shape shows relative displacement topology even without
      // mesh coordinates — clearly not physically accurate, labelled as proxy.
      origPositions = new Float32Array(n * 3)
      for (let i = 0; i < n; i++) {
        const theta = (i / n) * Math.PI * 2
        const phi = Math.acos(1 - (2 * i) / n)
        origPositions[i * 3 + 0] = Math.sin(phi) * Math.cos(theta)
        origPositions[i * 3 + 1] = Math.cos(phi)
        origPositions[i * 3 + 2] = Math.sin(phi) * Math.sin(theta)
      }
    }

    const morphedPositions = applyDisplacementScale(origPositions, nodeDisplacements, scale)

    // Build vertex colours
    let colors
    if (colorMode === 'vonmises' && stresses?.length > 0) {
      // DG0 per-cell → broadcast to vertices.
      // If stresses.length !== n we replicate per-node using index mod stresses.length.
      const norm = maxStress > 0 ? 1 / maxStress : 1
      colors = new Float32Array(n * 3)
      for (let i = 0; i < n; i++) {
        const s = stresses[i % stresses.length] || 0
        const [r, g, b] = scalarToRGB(s * norm)
        colors[i * 3 + 0] = r
        colors[i * 3 + 1] = g
        colors[i * 3 + 2] = b
      }
    } else {
      colors = buildDisplacementColors(nodeDisplacements, maxDisplacement || 1)
    }

    // If we have external geometry with index buffer use a mesh, otherwise points
    if (externalGeometry?.index) {
      const geo = new THREE.BufferGeometry()
      geo.setAttribute('position', new THREE.BufferAttribute(morphedPositions, 3))
      geo.setAttribute('color', new THREE.BufferAttribute(colors, 3))
      geo.setIndex(externalGeometry.index)
      geo.computeVertexNormals()
      const mat = new THREE.MeshPhongMaterial({
        vertexColors: true,
        wireframe: false,
        side: THREE.DoubleSide,
        transparent: true,
        opacity: 0.85,
      })
      scene.add(new THREE.Mesh(geo, mat))

      // Wireframe on top
      const wfMat = new THREE.MeshBasicMaterial({ color: 0x000000, wireframe: true, transparent: true, opacity: 0.15 })
      scene.add(new THREE.Mesh(geo, wfMat))
    } else {
      // Point cloud proxy
      const geo = new THREE.BufferGeometry()
      geo.setAttribute('position', new THREE.BufferAttribute(morphedPositions, 3))
      geo.setAttribute('color', new THREE.BufferAttribute(colors, 3))
      const mat = new THREE.PointsMaterial({ size: 0.03, vertexColors: true })
      scene.add(new THREE.Points(geo, mat))
    }

    // Camera auto-fit: compute bounding sphere of morphed positions
    const tmpGeo = new THREE.BufferGeometry()
    tmpGeo.setAttribute('position', new THREE.BufferAttribute(morphedPositions, 3))
    tmpGeo.computeBoundingSphere()
    const sphere = tmpGeo.boundingSphere
    if (sphere) {
      const { scene: sc, camera } = stateRef.current
      camera.position.copy(sphere.center).addScaledVector(new THREE.Vector3(0, 0, 1), sphere.radius * 3)
      camera.lookAt(sphere.center)
    }
  }, [nodeDisplacements, stresses, scale, colorMode, maxDisplacement, maxStress, externalGeometry])

  return (
    <div style={{ position: 'relative', marginTop: 4 }}>
      <canvas
        ref={canvasRef}
        width={320}
        height={220}
        style={{ width: '100%', height: 220, borderRadius: 5, border: '1px solid #1f2937', display: 'block' }}
      />
      {!externalGeometry && nodeDisplacements?.length > 0 && (
        <div style={{
          position: 'absolute', bottom: 6, left: 8,
          fontSize: 10, color: '#6b7280',
          background: '#111827cc', padding: '1px 5px', borderRadius: 3,
        }}>
          proxy layout (no mesh coords)
        </div>
      )}
      <ColorBar
        colorMode={colorMode}
        maxValue={colorMode === 'vonmises' ? maxStress : maxDisplacement}
      />
    </div>
  )
}

function ColorBar({ colorMode, maxValue }) {
  const stops = 6
  const labels = []
  for (let i = 0; i <= stops; i++) {
    const t = i / stops
    const v = (maxValue || 1) * t
    const [r, g, b] = scalarToRGB(t)
    const hex = '#' +
      Math.round(r * 255).toString(16).padStart(2, '0') +
      Math.round(g * 255).toString(16).padStart(2, '0') +
      Math.round(b * 255).toString(16).padStart(2, '0')
    labels.push({ t, v, hex })
  }

  const gradient = labels.map(l => l.hex).join(', ')

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
      <span style={{ fontSize: 10, color: '#6b7280', whiteSpace: 'nowrap' }}>
        {colorMode === 'vonmises' ? 'σ_vm' : '|u|'}
      </span>
      <div style={{
        flex: 1, height: 10, borderRadius: 3,
        background: `linear-gradient(to right, ${gradient})`,
      }} />
      <span style={{ fontSize: 10, color: '#6b7280', whiteSpace: 'nowrap', fontFamily: 'monospace' }}>
        {maxValue != null ? fmtBar(maxValue, colorMode) : '—'}
      </span>
    </div>
  )
}

function fmtBar(v, mode) {
  if (mode === 'vonmises') return (v / 1e6).toFixed(1) + ' MPa'
  return (v * 1e3).toFixed(3) + ' mm'
}
