/**
 * OrbitViewer.jsx — 3D orbital trajectory viewer using Three.js.
 *
 * Renders a small Three.js scene containing:
 *   - A sphere representing Earth (radius = 6378 km in scene units)
 *   - A line strip tracing the satellite trajectory from propagated IJK points
 *
 * Camera controls: orbit (left-drag), pan (right-drag / middle-drag),
 * zoom (scroll wheel) — implemented via manual pointer event handling to
 * avoid importing three/examples/jsm (which requires a deeper import path).
 *
 * Props
 * -----
 * trajectory  {Array<{x, y, z}>}  Trajectory points in km (IJK/ECI frame).
 *                                  If empty / null, only Earth is shown.
 * width       {number}             Container width in pixels. Default 600.
 * height      {number}             Container height in pixels. Default 400.
 * earthColor  {string}             Earth sphere colour. Default '#1a6fa8'.
 * orbitColor  {string}             Trajectory line colour. Default '#f0c040'.
 *
 * Usage
 * -----
 * <OrbitViewer trajectory={result.trajectory} width={800} height={500} />
 */

import { useEffect, useRef } from 'react'
import * as THREE from 'three'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const R_EARTH_KM = 6_378.137  // km — matches backend

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function OrbitViewer({
  trajectory = [],
  width = 600,
  height = 400,
  earthColor = '#1a6fa8',
  orbitColor = '#f0c040',
}) {
  const mountRef = useRef(null)
  // Keep a ref to the renderer so we can dispose on unmount / re-render
  const stateRef = useRef(null)

  useEffect(() => {
    const mount = mountRef.current
    if (!mount) return

    // ------------------------------------------------------------------
    // Scene
    // ------------------------------------------------------------------
    const scene = new THREE.Scene()
    scene.background = new THREE.Color('#0a0a14')

    // ------------------------------------------------------------------
    // Camera
    // ------------------------------------------------------------------
    const camera = new THREE.PerspectiveCamera(45, width / height, 10, 1_000_000)
    // Start the camera at 3× Earth radius
    camera.position.set(0, 0, R_EARTH_KM * 3)
    camera.lookAt(0, 0, 0)

    // ------------------------------------------------------------------
    // Renderer
    // ------------------------------------------------------------------
    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setSize(width, height)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    mount.appendChild(renderer.domElement)

    // ------------------------------------------------------------------
    // Lighting
    // ------------------------------------------------------------------
    const ambient = new THREE.AmbientLight(0xffffff, 0.4)
    scene.add(ambient)

    const sun = new THREE.DirectionalLight(0xffffff, 1.2)
    sun.position.set(50_000, 30_000, 80_000)
    scene.add(sun)

    // ------------------------------------------------------------------
    // Earth sphere
    // ------------------------------------------------------------------
    const earthGeo = new THREE.SphereGeometry(R_EARTH_KM, 64, 32)
    const earthMat = new THREE.MeshPhongMaterial({
      color: earthColor,
      shininess: 40,
    })
    const earthMesh = new THREE.Mesh(earthGeo, earthMat)
    scene.add(earthMesh)

    // Equator ring (visual reference)
    const ringGeo = new THREE.TorusGeometry(R_EARTH_KM, 30, 8, 120)
    const ringMat = new THREE.MeshBasicMaterial({ color: '#334455', opacity: 0.4, transparent: true })
    const ring = new THREE.Mesh(ringGeo, ringMat)
    ring.rotation.x = Math.PI / 2
    scene.add(ring)

    // ------------------------------------------------------------------
    // Orbit trajectory line
    // ------------------------------------------------------------------
    if (trajectory && trajectory.length >= 2) {
      const pts = trajectory.map(({ x, y, z }) => new THREE.Vector3(x, y, z))
      // Close the loop visually if start and end are close
      const start = pts[0]
      const end = pts[pts.length - 1]
      if (start.distanceTo(end) < R_EARTH_KM * 0.01) {
        pts.push(start.clone())
      }
      const lineGeo = new THREE.BufferGeometry().setFromPoints(pts)
      const lineMat = new THREE.LineBasicMaterial({ color: orbitColor, linewidth: 2 })
      const line = new THREE.Line(lineGeo, lineMat)
      scene.add(line)

      // Satellite dot at trajectory[0]
      const dotGeo = new THREE.SphereGeometry(80, 12, 8)
      const dotMat = new THREE.MeshBasicMaterial({ color: '#ff4444' })
      const dot = new THREE.Mesh(dotGeo, dotMat)
      dot.position.copy(pts[0])
      scene.add(dot)
    }

    // ------------------------------------------------------------------
    // Minimal orbit controls (no OrbitControls import needed)
    // ------------------------------------------------------------------
    let isPointerDown = false
    let lastPointer = { x: 0, y: 0 }
    let spherical = {
      theta: 0,       // azimuth (rad)
      phi: Math.PI / 2, // polar (rad)  π/2 = equatorial view
      radius: R_EARTH_KM * 3,
    }

    function updateCamera() {
      const { theta, phi, radius } = spherical
      camera.position.set(
        radius * Math.sin(phi) * Math.sin(theta),
        radius * Math.cos(phi),
        radius * Math.sin(phi) * Math.cos(theta),
      )
      camera.lookAt(0, 0, 0)
    }

    function onPointerDown(e) {
      isPointerDown = true
      lastPointer = { x: e.clientX, y: e.clientY }
    }

    function onPointerMove(e) {
      if (!isPointerDown) return
      const dx = e.clientX - lastPointer.x
      const dy = e.clientY - lastPointer.y
      lastPointer = { x: e.clientX, y: e.clientY }

      spherical.theta -= dx * 0.005
      spherical.phi   -= dy * 0.005
      // Clamp polar angle
      spherical.phi = Math.max(0.05, Math.min(Math.PI - 0.05, spherical.phi))
      updateCamera()
    }

    function onPointerUp() {
      isPointerDown = false
    }

    function onWheel(e) {
      e.preventDefault()
      const factor = e.deltaY > 0 ? 1.1 : 0.9
      spherical.radius = Math.max(R_EARTH_KM * 1.05, spherical.radius * factor)
      updateCamera()
    }

    const canvas = renderer.domElement
    canvas.addEventListener('pointerdown', onPointerDown)
    canvas.addEventListener('pointermove', onPointerMove)
    canvas.addEventListener('pointerup', onPointerUp)
    canvas.addEventListener('pointerleave', onPointerUp)
    canvas.addEventListener('wheel', onWheel, { passive: false })

    // ------------------------------------------------------------------
    // Animation loop
    // ------------------------------------------------------------------
    let animId
    function animate() {
      animId = requestAnimationFrame(animate)
      // Slow auto-rotation when not interacting
      if (!isPointerDown) {
        spherical.theta += 0.002
        updateCamera()
      }
      renderer.render(scene, camera)
    }
    animate()

    // Store for cleanup
    stateRef.current = { renderer, animId, canvas,
      onPointerDown, onPointerMove, onPointerUp, onWheel }

    // ------------------------------------------------------------------
    // Cleanup
    // ------------------------------------------------------------------
    return () => {
      cancelAnimationFrame(animId)
      canvas.removeEventListener('pointerdown', onPointerDown)
      canvas.removeEventListener('pointermove', onPointerMove)
      canvas.removeEventListener('pointerup', onPointerUp)
      canvas.removeEventListener('pointerleave', onPointerUp)
      canvas.removeEventListener('wheel', onWheel)
      renderer.dispose()
      if (mount.contains(canvas)) mount.removeChild(canvas)
    }
  }, [trajectory, width, height, earthColor, orbitColor])

  return (
    <div
      ref={mountRef}
      style={{ width, height, overflow: 'hidden', borderRadius: 8, cursor: 'grab' }}
      aria-label="Orbital trajectory viewer"
      data-testid="orbit-viewer"
    />
  )
}
