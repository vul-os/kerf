/**
 * GmatTrajectoryViewer.jsx — 3D spacecraft trajectory viewer.
 *
 * Renders a Three.js scene containing:
 *   - Earth (blue sphere, R = 6 378 km)
 *   - Moon (grey sphere at ~384 400 km from Earth in X direction for illustration)
 *   - Sun (point light + small emissive yellow sphere far away)
 *   - Trajectory polyline colour-coded by mission phase
 *   - Animated spacecraft dot that can be scrubbed / played along the track
 *
 * Camera: manual orbit controls (drag to rotate, scroll to zoom).
 * No three/examples/jsm imports — built on raw Three.js primitives, matching
 * the existing OrbitViewer.jsx approach.
 *
 * Props
 * ─────
 * trajectory  {Array<{t,x,y,z,vx,vy,vz}>}  State vectors in km / km·s⁻¹ (ECI).
 *                                            Defaults to built-in Apollo-TLI fixture.
 * events      {Array<{t, label, type}>}       Mission events (burns, flybys, etc.).
 *                                            Defaults to built-in fixture events.
 * width       {number}  Canvas width px.  Default 900.
 * height      {number}  Canvas height px. Default 560.
 * onLoadMission {Function} Called when user clicks "Load Mission" (no args).
 *                          Parent should fetch POST /api/llm-tools/aerospace_load_gmat_trajectory
 *                          and pass response into trajectory + events props.
 *
 * Usage
 * ─────
 * <GmatTrajectoryViewer trajectory={traj} events={evts} onLoadMission={handleLoad} />
 */

import { useEffect, useRef, useState, useCallback } from 'react'
import * as THREE from 'three'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const R_EARTH_KM = 6_378.137
const R_MOON_KM  = 1_737.4
const MOON_DIST_KM = 384_400   // Earth–Moon distance used for static display
const SUN_DIST_KM  = 800_000   // compressed for scene — real is 150e6 km

// Phase colour palette (6 phases max)
const PHASE_COLORS = [
  '#f0c040',   // gold  — parking orbit
  '#40c0ff',   // cyan  — TLI burn
  '#ff6060',   // red   — translunar coast
  '#80ff80',   // lime  — LOI burn
  '#ff80ff',   // pink  — lunar orbit
  '#ffa040',   // orange — TEI / return
]

// ---------------------------------------------------------------------------
// Apollo TLI fixture (~50 sample points, simplified geometry)
// ---------------------------------------------------------------------------

function _generateApolloFixture() {
  const pts = []
  const evts = []
  const N = 50

  // Phase 1: Low-Earth parking orbit (circular, 0-10 steps)
  const r_park = R_EARTH_KM + 185  // 185 km parking altitude
  for (let i = 0; i <= 10; i++) {
    const theta = (i / 10) * Math.PI * 1.2  // ~216° arc
    pts.push({
      t: i * 90,         // seconds
      x: r_park * Math.cos(theta),
      y: r_park * Math.sin(theta),
      z: 0,
      vx: -7.8 * Math.sin(theta),
      vy:  7.8 * Math.cos(theta),
      vz: 0,
      phase: 0,
    })
  }
  evts.push({ t: 0, label: 'Launch / MECO', type: 'burn' })

  // Phase 2: TLI burn (10-12)
  const r_tli_start = r_park
  for (let i = 0; i <= 2; i++) {
    const frac = i / 2
    const r = r_tli_start + frac * 2000
    const theta = Math.PI * 1.2 + frac * 0.3
    pts.push({
      t: 10 * 90 + i * 300,
      x: r * Math.cos(theta),
      y: r * Math.sin(theta),
      z: 0,
      vx: -10.4 * Math.sin(theta),
      vy:  10.4 * Math.cos(theta),
      vz: 0,
      phase: 1,
    })
  }
  evts.push({ t: 10 * 90, label: 'TLI Burn Ignition', type: 'burn' })
  evts.push({ t: 10 * 90 + 360, label: 'TLI Burn Cutoff', type: 'burn' })

  // Phase 3: Translunar coast (12-40 steps, elongated ellipse toward Moon)
  for (let i = 0; i <= 28; i++) {
    const frac = i / 28
    const r = r_tli_start + 2000 + frac * (MOON_DIST_KM * 0.95 - r_tli_start - 2000)
    const theta = Math.PI * 1.5 + frac * 2.2
    pts.push({
      t: 10 * 90 + 600 + i * 9000,
      x: r * Math.cos(theta),
      y: r * Math.sin(theta),
      z: r * 0.05 * Math.sin(frac * Math.PI),
      vx: 0,
      vy: 0,
      vz: 0,
      phase: 2,
    })
  }

  // Phase 4: LOI burn (40-42)
  const moon_x = MOON_DIST_KM * 0.6
  const moon_y = MOON_DIST_KM * 0.8
  evts.push({ t: 10 * 90 + 600 + 25 * 9000, label: 'LOI Burn', type: 'burn' })
  for (let i = 0; i <= 2; i++) {
    pts.push({
      t: 10 * 90 + 600 + 28 * 9000 + i * 600,
      x: moon_x + (R_MOON_KM + 100) * Math.cos(i * 0.5),
      y: moon_y + (R_MOON_KM + 100) * Math.sin(i * 0.5),
      z: 0,
      vx: 0, vy: 0, vz: 0,
      phase: 3,
    })
  }

  // Phase 5: Lunar orbit (42-48)
  for (let i = 0; i <= 5; i++) {
    const theta = i * 0.6
    pts.push({
      t: 10 * 90 + 600 + 28 * 9000 + 1200 + i * 3600,
      x: moon_x + (R_MOON_KM + 100) * Math.cos(theta),
      y: moon_y + (R_MOON_KM + 100) * Math.sin(theta),
      z: 0,
      vx: 0, vy: 0, vz: 0,
      phase: 4,
    })
  }

  // Phase 6: TEI (48-50)
  evts.push({ t: 10 * 90 + 600 + 28 * 9000 + 19200 + 3 * 3600, label: 'TEI Burn', type: 'burn' })
  for (let i = 0; i <= 2; i++) {
    const frac = i / 2
    pts.push({
      t: 10 * 90 + 600 + 28 * 9000 + 21600 + i * 3600,
      x: moon_x + (R_MOON_KM + 100 + frac * 50000) * Math.cos(3 + frac * 1),
      y: moon_y + (R_MOON_KM + 100 + frac * 50000) * Math.sin(3 + frac * 1),
      z: frac * -5000,
      vx: 0, vy: 0, vz: 0,
      phase: 5,
    })
  }

  return { pts, evts }
}

const APOLLO_FIXTURE = _generateApolloFixture()
const DEFAULT_TRAJECTORY = APOLLO_FIXTURE.pts
const DEFAULT_EVENTS     = APOLLO_FIXTURE.evts

// ---------------------------------------------------------------------------
// Helper: compute altitude + velocity from state vector
// ---------------------------------------------------------------------------

function _stateInfo(pt) {
  if (!pt) return null
  const r = Math.sqrt(pt.x ** 2 + pt.y ** 2 + pt.z ** 2)
  const alt = r - R_EARTH_KM
  const v   = Math.sqrt((pt.vx || 0) ** 2 + (pt.vy || 0) ** 2 + (pt.vz || 0) ** 2)
  // Vis-viva eccentricity proxy (not a real osculating-element solver — display only)
  const mu  = 398_600.4418  // km³/s²
  const e_display = v > 0 ? Math.abs((r * v * v / mu) - 1).toFixed(4) : 'N/A'
  return {
    alt:  alt.toFixed(1),
    v:    v.toFixed(3),
    e:    e_display,
    t:    pt.t,
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function GmatTrajectoryViewer({
  trajectory = DEFAULT_TRAJECTORY,
  events     = DEFAULT_EVENTS,
  width      = 900,
  height     = 560,
  onLoadMission,
}) {
  const mountRef = useRef(null)
  const stateRef = useRef(null)

  // Playback state
  const [frameIdx, setFrameIdx]   = useState(0)
  const [playing,  setPlaying]    = useState(false)
  const playingRef = useRef(false)
  const frameIdxRef = useRef(0)

  // Sync refs so animation loop sees latest values without stale closure
  useEffect(() => { playingRef.current  = playing },  [playing])
  useEffect(() => { frameIdxRef.current = frameIdx }, [frameIdx])

  // Current state info for side panel
  const curPt   = trajectory[frameIdx] || trajectory[0] || null
  const stInfo  = _stateInfo(curPt)

  // Build / rebuild Three.js scene whenever trajectory changes
  useEffect(() => {
    const mount = mountRef.current
    if (!mount) return

    // ── Scene ───────────────────────────────────────────────────────────────
    const scene = new THREE.Scene()
    scene.background = new THREE.Color('#040a14')

    // Subtle star field
    {
      const starGeo = new THREE.BufferGeometry()
      const starCount = 800
      const pos = new Float32Array(starCount * 3)
      for (let i = 0; i < starCount; i++) {
        const r = 1_500_000
        pos[i*3]   = (Math.random() - 0.5) * r
        pos[i*3+1] = (Math.random() - 0.5) * r
        pos[i*3+2] = (Math.random() - 0.5) * r
      }
      starGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3))
      const starMat = new THREE.PointsMaterial({ color: '#ffffff', size: 600, sizeAttenuation: true, opacity: 0.5, transparent: true })
      scene.add(new THREE.Points(starGeo, starMat))
    }

    // ── Camera ──────────────────────────────────────────────────────────────
    const camera = new THREE.PerspectiveCamera(45, width / height, 100, 2_000_000)
    camera.position.set(0, 0, R_EARTH_KM * 5)
    camera.lookAt(0, 0, 0)

    // ── Renderer ────────────────────────────────────────────────────────────
    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setSize(width, height)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    mount.appendChild(renderer.domElement)

    // ── Lighting ────────────────────────────────────────────────────────────
    const ambient = new THREE.AmbientLight(0xffffff, 0.25)
    scene.add(ambient)

    const sunLight = new THREE.PointLight(0xfff4e0, 2.5, 0)
    sunLight.position.set(SUN_DIST_KM, 100_000, 0)
    scene.add(sunLight)

    // Sun visual
    const sunGeo = new THREE.SphereGeometry(12000, 16, 8)
    const sunMat = new THREE.MeshBasicMaterial({ color: '#fff480' })
    const sunMesh = new THREE.Mesh(sunGeo, sunMat)
    sunMesh.position.set(SUN_DIST_KM, 100_000, 0)
    scene.add(sunMesh)

    // ── Earth ───────────────────────────────────────────────────────────────
    const earthGeo = new THREE.SphereGeometry(R_EARTH_KM, 64, 32)
    const earthMat = new THREE.MeshPhongMaterial({
      color: '#1a6fa8',
      emissive: '#091a2a',
      shininess: 60,
    })
    scene.add(new THREE.Mesh(earthGeo, earthMat))

    // Equator ring
    const ringGeo = new THREE.TorusGeometry(R_EARTH_KM, 40, 6, 120)
    const ringMat = new THREE.MeshBasicMaterial({ color: '#334455', opacity: 0.35, transparent: true })
    const ring = new THREE.Mesh(ringGeo, ringMat)
    ring.rotation.x = Math.PI / 2
    scene.add(ring)

    // ── Moon ────────────────────────────────────────────────────────────────
    const moonGeo = new THREE.SphereGeometry(R_MOON_KM * 3, 24, 16)  // ×3 for visibility
    const moonMat = new THREE.MeshPhongMaterial({ color: '#888880', shininess: 10 })
    const moonMesh = new THREE.Mesh(moonGeo, moonMat)
    // Position Moon in scene using trajectory endpoint if available, else default axis
    const lastPt = trajectory[trajectory.length - 1]
    if (lastPt && Math.sqrt(lastPt.x**2+lastPt.y**2+lastPt.z**2) > MOON_DIST_KM * 0.5) {
      moonMesh.position.set(
        trajectory[trajectory.length - 1].x * 0.9,
        trajectory[trajectory.length - 1].y * 0.9,
        trajectory[trajectory.length - 1].z * 0.9,
      )
    } else {
      moonMesh.position.set(MOON_DIST_KM * 0.6, MOON_DIST_KM * 0.8, 0)
    }
    scene.add(moonMesh)

    // ── Trajectory lines (colour by phase) ──────────────────────────────────
    // Group consecutive points by phase
    let currentPhase = (trajectory[0]?.phase ?? 0) % PHASE_COLORS.length
    let segPts = []

    function flushSegment() {
      if (segPts.length < 2) { segPts = []; return }
      const geo = new THREE.BufferGeometry().setFromPoints(
        segPts.map(p => new THREE.Vector3(p.x, p.y, p.z))
      )
      const mat = new THREE.LineBasicMaterial({
        color: PHASE_COLORS[currentPhase],
        linewidth: 2,
      })
      scene.add(new THREE.Line(geo, mat))
      segPts = []
    }

    for (const pt of trajectory) {
      const ph = (pt.phase ?? 0) % PHASE_COLORS.length
      if (ph !== currentPhase) {
        // Include last point of previous segment as first of new for continuity
        const last = segPts[segPts.length - 1]
        flushSegment()
        currentPhase = ph
        if (last) segPts.push(last)
      }
      segPts.push(pt)
    }
    flushSegment()

    // ── Spacecraft dot (animated position) ──────────────────────────────────
    const scDotGeo = new THREE.SphereGeometry(200, 12, 8)
    const scDotMat = new THREE.MeshBasicMaterial({ color: '#ff4444' })
    const scDot    = new THREE.Mesh(scDotGeo, scDotMat)
    if (trajectory[0]) {
      scDot.position.set(trajectory[0].x, trajectory[0].y, trajectory[0].z)
    }
    scene.add(scDot)

    // ── Camera orbit controls ────────────────────────────────────────────────
    let isDown = false
    let lastPtr = { x: 0, y: 0 }
    let spherical = {
      theta:  0,
      phi:    Math.PI / 2.2,
      radius: R_EARTH_KM * 5,
    }

    function _updateCamera() {
      const { theta, phi, radius } = spherical
      camera.position.set(
        radius * Math.sin(phi) * Math.sin(theta),
        radius * Math.cos(phi),
        radius * Math.sin(phi) * Math.cos(theta),
      )
      camera.lookAt(0, 0, 0)
    }

    const canvas = renderer.domElement

    function onDown(e) { isDown = true; lastPtr = { x: e.clientX, y: e.clientY } }
    function onMove(e) {
      if (!isDown) return
      const dx = e.clientX - lastPtr.x
      const dy = e.clientY - lastPtr.y
      lastPtr = { x: e.clientX, y: e.clientY }
      spherical.theta -= dx * 0.005
      spherical.phi    = Math.max(0.05, Math.min(Math.PI - 0.05, spherical.phi - dy * 0.005))
      _updateCamera()
    }
    function onUp() { isDown = false }
    function onWheel(e) {
      e.preventDefault()
      spherical.radius = Math.max(
        R_EARTH_KM * 1.1,
        spherical.radius * (e.deltaY > 0 ? 1.12 : 0.88)
      )
      _updateCamera()
    }

    canvas.addEventListener('pointerdown',  onDown)
    canvas.addEventListener('pointermove',  onMove)
    canvas.addEventListener('pointerup',    onUp)
    canvas.addEventListener('pointerleave', onUp)
    canvas.addEventListener('wheel',        onWheel, { passive: false })

    // ── Animation loop ───────────────────────────────────────────────────────
    let animId
    let lastTime = performance.now()
    let accumMs = 0

    function animate(now) {
      animId = requestAnimationFrame(animate)
      const dt = now - lastTime
      lastTime = now

      // Update spacecraft dot position
      const idx = frameIdxRef.current
      const pt  = trajectory[idx]
      if (pt) scDot.position.set(pt.x, pt.y, pt.z)

      // Auto-advance when playing (1 step every 200 ms)
      if (playingRef.current) {
        accumMs += dt
        if (accumMs >= 200) {
          accumMs = 0
          const next = (frameIdxRef.current + 1) % trajectory.length
          frameIdxRef.current = next
          setFrameIdx(next)
        }
      } else {
        accumMs = 0
      }

      // Slow auto-rotate when not dragging
      if (!isDown) {
        spherical.theta += 0.001
        _updateCamera()
      }

      renderer.render(scene, camera)
    }
    animate(performance.now())

    stateRef.current = { renderer, animId, canvas, onDown, onMove, onUp, onWheel }

    return () => {
      cancelAnimationFrame(animId)
      canvas.removeEventListener('pointerdown',  onDown)
      canvas.removeEventListener('pointermove',  onMove)
      canvas.removeEventListener('pointerup',    onUp)
      canvas.removeEventListener('pointerleave', onUp)
      canvas.removeEventListener('wheel',        onWheel)
      renderer.dispose()
      if (mount.contains(canvas)) mount.removeChild(canvas)
    }
  // Re-build scene on trajectory / size change only
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trajectory, width, height])

  // Format time label
  function _fmtTime(s) {
    const h = Math.floor(s / 3600)
    const m = Math.floor((s % 3600) / 60)
    return `T+${h}h${m.toString().padStart(2,'0')}m`
  }

  const scrubMax = Math.max(0, trajectory.length - 1)

  return (
    <div style={{ display: 'flex', gap: 0, background: '#040a14', color: '#cce4ff', fontFamily: 'monospace', fontSize: 13 }}>
      {/* 3D canvas */}
      <div
        ref={mountRef}
        style={{ width, height, overflow: 'hidden', borderRadius: '8px 0 0 8px', cursor: 'grab', flexShrink: 0 }}
        aria-label="GMAT 3D trajectory viewer"
        data-testid="gmat-trajectory-viewer"
      />

      {/* Side panel */}
      <div style={{
        width: 260,
        height,
        background: '#080f1e',
        borderRadius: '0 8px 8px 0',
        border: '1px solid #1a2a4a',
        borderLeft: 'none',
        display: 'flex',
        flexDirection: 'column',
        padding: '12px 14px',
        gap: 12,
        overflowY: 'auto',
      }}>
        {/* Header */}
        <div style={{ borderBottom: '1px solid #1a2a4a', paddingBottom: 8 }}>
          <div style={{ color: '#80c0ff', fontWeight: 700, fontSize: 14, letterSpacing: 1 }}>
            GMAT TRAJECTORY
          </div>
          <div style={{ color: '#405878', fontSize: 11, marginTop: 2 }}>
            ASTROGATOR / ECI frame
          </div>
        </div>

        {/* Load mission button */}
        {onLoadMission && (
          <button
            onClick={onLoadMission}
            style={{
              background: '#1a3a6a',
              border: '1px solid #2a5a9a',
              color: '#80c0ff',
              borderRadius: 4,
              padding: '6px 10px',
              cursor: 'pointer',
              fontSize: 12,
              letterSpacing: 0.5,
            }}
          >
            Load Mission
          </button>
        )}

        {/* Time scrubber */}
        <div>
          <div style={{ color: '#405878', fontSize: 11, marginBottom: 4 }}>EPOCH SCRUB</div>
          <input
            type="range"
            min={0}
            max={scrubMax}
            value={frameIdx}
            onChange={e => { setFrameIdx(+e.target.value); setPlaying(false) }}
            style={{ width: '100%', accentColor: '#40a0ff' }}
          />
          <div style={{ color: '#60a0e0', fontSize: 12, marginTop: 2 }}>
            {curPt ? _fmtTime(curPt.t) : '—'}
            <span style={{ color: '#405878', marginLeft: 4 }}>({frameIdx + 1}/{trajectory.length})</span>
          </div>
        </div>

        {/* Play / Pause */}
        <button
          onClick={() => setPlaying(p => !p)}
          style={{
            background: playing ? '#2a1a4a' : '#1a3a2a',
            border: `1px solid ${playing ? '#6a40a0' : '#2a6a3a'}`,
            color: playing ? '#c080ff' : '#60d080',
            borderRadius: 4,
            padding: '5px 10px',
            cursor: 'pointer',
            fontSize: 12,
          }}
        >
          {playing ? 'Pause' : 'Play'}
        </button>

        {/* Spacecraft state */}
        <div>
          <div style={{ color: '#405878', fontSize: 11, marginBottom: 4 }}>SPACECRAFT STATE</div>
          {stInfo ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              <_StateRow label="Altitude"  value={`${stInfo.alt} km`} />
              <_StateRow label="Velocity"  value={`${stInfo.v} km/s`} />
              <_StateRow label="|e| proxy" value={stInfo.e} />
            </div>
          ) : (
            <div style={{ color: '#405878' }}>No state vector</div>
          )}
        </div>

        {/* Phase legend */}
        <div>
          <div style={{ color: '#405878', fontSize: 11, marginBottom: 4 }}>PHASE LEGEND</div>
          {PHASE_COLORS.map((c, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
              <div style={{ width: 14, height: 4, background: c, borderRadius: 2 }} />
              <span style={{ color: '#607898', fontSize: 11 }}>
                {['Parking Orbit','TLI Burn','Trans-Lunar Coast','LOI Burn','Lunar Orbit','TEI/Return'][i] || `Phase ${i}`}
              </span>
            </div>
          ))}
        </div>

        {/* Mission events */}
        <div style={{ flexGrow: 1 }}>
          <div style={{ color: '#405878', fontSize: 11, marginBottom: 4 }}>MISSION EVENTS</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 150, overflowY: 'auto' }}>
            {events.map((ev, i) => (
              <button
                key={i}
                onClick={() => {
                  // Jump to nearest trajectory point
                  let bestIdx = 0
                  let bestDiff = Infinity
                  trajectory.forEach((pt, idx) => {
                    const d = Math.abs(pt.t - ev.t)
                    if (d < bestDiff) { bestDiff = d; bestIdx = idx }
                  })
                  setFrameIdx(bestIdx)
                  setPlaying(false)
                }}
                style={{
                  background: 'transparent',
                  border: '1px solid #1a2a4a',
                  borderLeft: `3px solid ${ev.type === 'burn' ? '#ff6060' : '#40c0ff'}`,
                  color: '#80a0c0',
                  borderRadius: 3,
                  padding: '4px 8px',
                  cursor: 'pointer',
                  textAlign: 'left',
                  fontSize: 11,
                  lineHeight: 1.4,
                }}
              >
                <div style={{ color: '#a0c8e8' }}>{ev.label}</div>
                <div style={{ color: '#405878' }}>{_fmtTime(ev.t)}</div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sub-component: state row
// ---------------------------------------------------------------------------

function _StateRow({ label, value }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
      <span style={{ color: '#405878' }}>{label}</span>
      <span style={{ color: '#a0d8f0', fontVariantNumeric: 'tabular-nums' }}>{value}</span>
    </div>
  )
}
