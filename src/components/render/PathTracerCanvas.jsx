/**
 * PathTracerCanvas.jsx — WebGPU path-tracer canvas component.
 *
 * Props:
 *   scene        {Scene}   — PathTracerScene.Scene instance
 *   width        {number}  — canvas pixel width  (default 800)
 *   height       {number}  — canvas pixel height (default 600)
 *   onSampleCount {Function(n)} — called each frame with accumulated sample count
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import shader from './shaders/pathtracer.wgsl?raw'
import { buildBVH } from './PathTracerScene.js'

// ─── Matrix helpers (column-major Float32Array, matches WGSL mat4x4<f32>) ───

function mat4Identity() {
  // eslint-disable-next-line no-return-assign
  return new Float32Array([
    1, 0, 0, 0,
    0, 1, 0, 0,
    0, 0, 1, 0,
    0, 0, 0, 1,
  ])
}

function mat4Multiply(a, b) {
  const out = new Float32Array(16)
  for (let i = 0; i < 4; i++) {
    for (let j = 0; j < 4; j++) {
      let s = 0
      for (let k = 0; k < 4; k++) s += a[i + k * 4] * b[k + j * 4]
      out[i + j * 4] = s
    }
  }
  return out
}

function mat4Inverse(m) {
  // Standard 4×4 inverse via cofactors
  const inv = new Float32Array(16)
  inv[0]  =  m[5]*m[10]*m[15] - m[5]*m[11]*m[14] - m[9]*m[6]*m[15] + m[9]*m[7]*m[14] + m[13]*m[6]*m[11] - m[13]*m[7]*m[10]
  inv[4]  = -m[4]*m[10]*m[15] + m[4]*m[11]*m[14] + m[8]*m[6]*m[15] - m[8]*m[7]*m[14] - m[12]*m[6]*m[11] + m[12]*m[7]*m[10]
  inv[8]  =  m[4]*m[9]*m[15]  - m[4]*m[11]*m[13] - m[8]*m[5]*m[15] + m[8]*m[7]*m[13] + m[12]*m[5]*m[11] - m[12]*m[7]*m[9]
  inv[12] = -m[4]*m[9]*m[14]  + m[4]*m[10]*m[13] + m[8]*m[5]*m[14] - m[8]*m[6]*m[13] - m[12]*m[5]*m[10] + m[12]*m[6]*m[9]
  inv[1]  = -m[1]*m[10]*m[15] + m[1]*m[11]*m[14] + m[9]*m[2]*m[15] - m[9]*m[3]*m[14] - m[13]*m[2]*m[11] + m[13]*m[3]*m[10]
  inv[5]  =  m[0]*m[10]*m[15] - m[0]*m[11]*m[14] - m[8]*m[2]*m[15] + m[8]*m[3]*m[14] + m[12]*m[2]*m[11] - m[12]*m[3]*m[10]
  inv[9]  = -m[0]*m[9]*m[15]  + m[0]*m[11]*m[13] + m[8]*m[1]*m[15] - m[8]*m[3]*m[13] - m[12]*m[1]*m[11] + m[12]*m[3]*m[9]
  inv[13] =  m[0]*m[9]*m[14]  - m[0]*m[10]*m[13] - m[8]*m[1]*m[14] + m[8]*m[2]*m[13] + m[12]*m[1]*m[10] - m[12]*m[2]*m[9]
  inv[2]  =  m[1]*m[6]*m[15]  - m[1]*m[7]*m[14]  - m[5]*m[2]*m[15] + m[5]*m[3]*m[14] + m[13]*m[2]*m[7]  - m[13]*m[3]*m[6]
  inv[6]  = -m[0]*m[6]*m[15]  + m[0]*m[7]*m[14]  + m[4]*m[2]*m[15] - m[4]*m[3]*m[14] - m[12]*m[2]*m[7]  + m[12]*m[3]*m[6]
  inv[10] =  m[0]*m[5]*m[15]  - m[0]*m[7]*m[13]  - m[4]*m[1]*m[15] + m[4]*m[3]*m[13] + m[12]*m[1]*m[7]  - m[12]*m[3]*m[5]
  inv[14] = -m[0]*m[5]*m[14]  + m[0]*m[6]*m[13]  + m[4]*m[1]*m[14] - m[4]*m[2]*m[13] - m[12]*m[1]*m[6]  + m[12]*m[2]*m[5]
  inv[3]  = -m[1]*m[6]*m[11]  + m[1]*m[7]*m[10]  + m[5]*m[2]*m[11] - m[5]*m[3]*m[10] - m[9]*m[2]*m[7]   + m[9]*m[3]*m[6]
  inv[7]  =  m[0]*m[6]*m[11]  - m[0]*m[7]*m[10]  - m[4]*m[2]*m[11] + m[4]*m[3]*m[10] + m[8]*m[2]*m[7]   - m[8]*m[3]*m[6]
  inv[11] = -m[0]*m[5]*m[11]  + m[0]*m[7]*m[9]   + m[4]*m[1]*m[11] - m[4]*m[3]*m[9]  - m[8]*m[1]*m[7]   + m[8]*m[3]*m[5]
  inv[15] =  m[0]*m[5]*m[10]  - m[0]*m[6]*m[9]   - m[4]*m[1]*m[10] + m[4]*m[2]*m[9]  + m[8]*m[1]*m[6]   - m[8]*m[2]*m[5]
  const det = m[0]*inv[0] + m[1]*inv[4] + m[2]*inv[8] + m[3]*inv[12]
  if (Math.abs(det) < 1e-12) return mat4Identity()
  const invDet = 1 / det
  for (let i = 0; i < 16; i++) inv[i] *= invDet
  return inv
}

function makePerspective(fovY, aspect, near, far) {
  const f = 1.0 / Math.tan(fovY / 2)
  const nf = 1 / (near - far)
  return new Float32Array([
    f / aspect, 0, 0,                   0,
    0,          f, 0,                   0,
    0,          0, (far + near) * nf,  -1,
    0,          0, 2 * far * near * nf, 0,
  ])
}

function makeView(eye, target, up = [0, 1, 0]) {
  const f = _normalise([target[0]-eye[0], target[1]-eye[1], target[2]-eye[2]])
  const s = _normalise(_cross(f, up))
  const u = _cross(s, f)
  return new Float32Array([
     s[0],  u[0], -f[0], 0,
     s[1],  u[1], -f[1], 0,
     s[2],  u[2], -f[2], 0,
    -_dot(s,eye), -_dot(u,eye), _dot(f,eye), 1,
  ])
}

function _normalise(v) { const l = Math.sqrt(v[0]*v[0]+v[1]*v[1]+v[2]*v[2]); return l<1e-10?[0,1,0]:[v[0]/l,v[1]/l,v[2]/l] }
function _cross(a, b) { return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]] }
function _dot(a, b) { return a[0]*b[0]+a[1]*b[1]+a[2]*b[2] }

// ─── GPU resource helpers ────────────────────────────────────────────────────

function createStorageBuffer(device, data, usage) {
  const buf = device.createBuffer({
    size: Math.max(data.byteLength, 16), // min 16 bytes
    usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST | (usage || 0),
    mappedAtCreation: true,
  })
  new Float32Array(buf.getMappedRange()).set(data)
  buf.unmap()
  return buf
}

function createUniformBuffer(device, size) {
  return device.createBuffer({
    size,
    usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
  })
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function PathTracerCanvas({ scene, width = 800, height = 600, onSampleCount }) {
  const canvasRef   = useRef(null)
  const gpuRef      = useRef(null)   // { device, pipeline, bindGroups, uniformBuf, accumTex, ... }
  const cameraRef   = useRef({
    eye:    [0, 1, 6],
    target: [0, 0, -5],
    fovY:   Math.PI / 4,
  })
  const inputRef    = useRef({ keys: new Set(), mouse: null, lastMouse: null })
  const frameRef    = useRef({ index: 0, rafId: null, dirty: true })
  const [gpuError, setGpuError] = useState(null)

  // ── Reset accumulation ──────────────────────────────────────────────────
  const resetAccum = useCallback(() => {
    if (!gpuRef.current) return
    frameRef.current.index = 0
    frameRef.current.dirty = true
    // Clear accumulation texture by recreating it
    _recreateAccumTex(gpuRef.current, width, height)
  }, [width, height])

  // ── Init WebGPU ─────────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false
    let rafId = null

    async function init() {
      const canvas = canvasRef.current
      if (!canvas) return

      // Feature detection
      if (!navigator.gpu) {
        setGpuError('no-webgpu')
        return
      }
      const adapter = await navigator.gpu.requestAdapter()
      if (!adapter) {
        setGpuError('no-adapter')
        return
      }
      const device = await adapter.requestDevice()
      if (cancelled) return

      const context = canvas.getContext('webgpu')
      const format  = navigator.gpu.getPreferredCanvasFormat()
      context.configure({ device, format, alphaMode: 'opaque' })

      // Build scene GPU buffers
      const spheresBuf   = createStorageBuffer(device, scene.spheresGPU())
      const planesBuf    = createStorageBuffer(device, scene.planesGPU())
      const matsBuf      = createStorageBuffer(device, scene.materialsGPU())
      const lightsBuf    = createStorageBuffer(device, scene.lightsGPU())
      const bvhData      = buildBVH(scene)
      const bvhBuf       = createStorageBuffer(device, bvhData)

      // Camera uniform buffer: mat4(16) + vec3+u32(4) + vec2+vec2(4) = 24 floats = 96 bytes
      const uniformBuf = createUniformBuffer(device, 96)

      // Accumulation texture (rgba32float)
      const accumTex = _createAccumTex(device, width, height)

      // Pipeline
      const shaderModule = device.createShaderModule({ code: shader })

      const bindGroupLayout0 = device.createBindGroupLayout({
        entries: [
          { binding: 0, visibility: GPUShaderStage.VERTEX | GPUShaderStage.FRAGMENT, buffer: { type: 'uniform' } },
          { binding: 1, visibility: GPUShaderStage.FRAGMENT, buffer: { type: 'read-only-storage' } },
          { binding: 2, visibility: GPUShaderStage.FRAGMENT, buffer: { type: 'read-only-storage' } },
          { binding: 3, visibility: GPUShaderStage.FRAGMENT, buffer: { type: 'read-only-storage' } },
          { binding: 4, visibility: GPUShaderStage.FRAGMENT, buffer: { type: 'read-only-storage' } },
          { binding: 5, visibility: GPUShaderStage.FRAGMENT, buffer: { type: 'read-only-storage' } },
        ],
      })

      const bindGroupLayout1 = device.createBindGroupLayout({
        entries: [
          { binding: 0, visibility: GPUShaderStage.FRAGMENT, storageTexture: { access: 'read-write', format: 'rgba32float', viewDimension: '2d' } },
        ],
      })

      const pipelineLayout = device.createPipelineLayout({
        bindGroupLayouts: [bindGroupLayout0, bindGroupLayout1],
      })

      const pipeline = device.createRenderPipeline({
        layout: pipelineLayout,
        vertex: {
          module: shaderModule,
          entryPoint: 'vs_main',
        },
        fragment: {
          module: shaderModule,
          entryPoint: 'fs_main',
          targets: [{ format }],
        },
        primitive: { topology: 'triangle-list' },
      })

      const bindGroup0 = device.createBindGroup({
        layout: bindGroupLayout0,
        entries: [
          { binding: 0, resource: { buffer: uniformBuf } },
          { binding: 1, resource: { buffer: spheresBuf } },
          { binding: 2, resource: { buffer: planesBuf } },
          { binding: 3, resource: { buffer: matsBuf } },
          { binding: 4, resource: { buffer: lightsBuf } },
          { binding: 5, resource: { buffer: bvhBuf } },
        ],
      })

      const bindGroup1 = _makeAccumBindGroup(device, bindGroupLayout1, accumTex)

      const gpu = {
        device, context, format,
        pipeline, pipelineLayout,
        bindGroupLayout0, bindGroupLayout1,
        bindGroup0, bindGroup1,
        uniformBuf,
        accumTex,
        spheresBuf, planesBuf, matsBuf, lightsBuf, bvhBuf,
        width, height,
      }
      gpuRef.current = gpu

      // Render loop
      function frame() {
        if (cancelled) return
        _updateCameraFromInput(cameraRef, inputRef, frameRef, resetAccum)
        _uploadCameraUniform(gpu, cameraRef.current, width, height, frameRef.current.index)
        _renderFrame(gpu)
        frameRef.current.index++
        if (onSampleCount) onSampleCount(frameRef.current.index)
        rafId = requestAnimationFrame(frame)
        frameRef.current.rafId = rafId
      }
      rafId = requestAnimationFrame(frame)
    }

    init().catch((err) => {
      if (!cancelled) setGpuError(err.message || String(err))
    })

    return () => {
      cancelled = true
      if (rafId) cancelAnimationFrame(rafId)
      const gpu = gpuRef.current
      if (gpu) {
        // destroy GPU resources
        gpu.uniformBuf.destroy()
        gpu.spheresBuf.destroy()
        gpu.planesBuf.destroy()
        gpu.matsBuf.destroy()
        gpu.lightsBuf.destroy()
        gpu.bvhBuf.destroy()
        gpu.accumTex.destroy()
        gpuRef.current = null
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene, width, height])

  // ── Mouse / keyboard event listeners ──────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const onMouseDown = (e) => {
      inputRef.current.mouse = { x: e.clientX, y: e.clientY }
      inputRef.current.lastMouse = { x: e.clientX, y: e.clientY }
    }
    const onMouseMove = (e) => {
      if (!inputRef.current.mouse) return
      const dx = e.clientX - inputRef.current.lastMouse.x
      const dy = e.clientY - inputRef.current.lastMouse.y
      inputRef.current.lastMouse = { x: e.clientX, y: e.clientY }
      _orbitCamera(cameraRef.current, dx, dy)
      frameRef.current.index = 0
      if (gpuRef.current) _recreateAccumTex(gpuRef.current, width, height)
    }
    const onMouseUp = () => { inputRef.current.mouse = null }
    const onWheel   = (e) => {
      e.preventDefault()
      _zoomCamera(cameraRef.current, e.deltaY)
      frameRef.current.index = 0
      if (gpuRef.current) _recreateAccumTex(gpuRef.current, width, height)
    }
    const onKeyDown = (e) => inputRef.current.keys.add(e.code)
    const onKeyUp   = (e) => inputRef.current.keys.delete(e.code)

    canvas.addEventListener('mousedown', onMouseDown)
    canvas.addEventListener('mousemove', onMouseMove)
    canvas.addEventListener('mouseup',   onMouseUp)
    canvas.addEventListener('wheel',     onWheel,   { passive: false })
    window.addEventListener('keydown',   onKeyDown)
    window.addEventListener('keyup',     onKeyUp)

    return () => {
      canvas.removeEventListener('mousedown', onMouseDown)
      canvas.removeEventListener('mousemove', onMouseMove)
      canvas.removeEventListener('mouseup',   onMouseUp)
      canvas.removeEventListener('wheel',     onWheel)
      window.removeEventListener('keydown',   onKeyDown)
      window.removeEventListener('keyup',     onKeyUp)
    }
  }, [width, height])

  if (gpuError === 'no-webgpu' || gpuError === 'no-adapter') {
    return (
      <div className="flex flex-col items-center justify-center bg-ink-900 border border-ink-700 rounded-lg text-ink-300 text-sm p-8 gap-3" style={{ width, height }}>
        <span className="text-2xl">WebGPU not available</span>
        <p className="text-ink-500 text-center max-w-md">
          WebGPU is not supported in this browser. Try{' '}
          <a href="https://www.google.com/chrome/" target="_blank" rel="noopener noreferrer" className="text-kerf-300 underline">Chrome 113+</a>{' '}
          or Firefox Nightly with <code className="font-mono text-xs bg-ink-800 px-1 rounded">dom.webgpu.enabled</code> set in{' '}
          <code className="font-mono text-xs bg-ink-800 px-1 rounded">about:config</code>.
        </p>
      </div>
    )
  }

  if (gpuError) {
    return (
      <div className="flex items-center justify-center bg-ink-900 border border-red-900/60 rounded-lg text-red-400 text-sm p-6" style={{ width, height }}>
        WebGPU error: {gpuError}
      </div>
    )
  }

  return (
    <canvas
      ref={canvasRef}
      width={width}
      height={height}
      className="block rounded-lg border border-ink-700 cursor-grab active:cursor-grabbing"
      tabIndex={0}
      title="Drag to orbit · Scroll to zoom · WASD to pan"
    />
  )
}

// ─── GPU helpers ─────────────────────────────────────────────────────────────

function _createAccumTex(device, w, h) {
  return device.createTexture({
    size: [w, h, 1],
    format: 'rgba32float',
    usage: GPUTextureUsage.STORAGE_BINDING | GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_SRC,
  })
}

function _makeAccumBindGroup(device, layout, tex) {
  return device.createBindGroup({
    layout,
    entries: [{ binding: 0, resource: tex.createView() }],
  })
}

function _recreateAccumTex(gpu, w, h) {
  gpu.accumTex.destroy()
  gpu.accumTex = _createAccumTex(gpu.device, w, h)
  gpu.bindGroup1 = _makeAccumBindGroup(gpu.device, gpu.bindGroupLayout1, gpu.accumTex)
}

function _uploadCameraUniform(gpu, cam, w, h, frameIndex) {
  const view = makeView(cam.eye, cam.target)
  const proj = makePerspective(cam.fovY, w / h, 0.01, 1000)
  const vp   = mat4Multiply(proj, view)
  const invVP = mat4Inverse(vp)

  // Layout: mat4(16f) + origin(3f) + frameIndex(u32) + resolution(2f) + pad(2f)
  const data = new Float32Array(24)
  data.set(invVP, 0)
  data[16] = cam.eye[0]
  data[17] = cam.eye[1]
  data[18] = cam.eye[2]
  // frameIndex as u32 via DataView
  const dv = new DataView(data.buffer)
  dv.setUint32(19 * 4, frameIndex, true)
  data[20] = w
  data[21] = h
  // data[22], data[23] = pad

  gpu.device.queue.writeBuffer(gpu.uniformBuf, 0, data)
}

function _renderFrame(gpu) {
  const { device, context, pipeline, bindGroup0, bindGroup1 } = gpu
  const encoder = device.createCommandEncoder()
  const pass = encoder.beginRenderPass({
    colorAttachments: [{
      view: context.getCurrentTexture().createView(),
      loadOp: 'clear',
      clearValue: { r: 0, g: 0, b: 0, a: 1 },
      storeOp: 'store',
    }],
  })
  pass.setPipeline(pipeline)
  pass.setBindGroup(0, bindGroup0)
  pass.setBindGroup(1, bindGroup1)
  pass.draw(3) // full-screen triangle
  pass.end()
  device.queue.submit([encoder.finish()])
}

// ─── Camera controls ─────────────────────────────────────────────────────────

const ORBIT_SPEED = 0.005
const ZOOM_SPEED  = 0.01
const PAN_SPEED   = 0.05

function _orbitCamera(cam, dx, dy) {
  const [ex, ey, ez] = cam.eye
  const [tx, ty, tz] = cam.target
  const rx = ex - tx, ry = ey - ty, rz = ez - tz
  const r  = Math.sqrt(rx*rx + ry*ry + rz*rz)
  let theta = Math.atan2(rx, rz) + dx * ORBIT_SPEED
  let phi   = Math.acos(Math.max(-0.99, Math.min(0.99, ry / r))) + dy * ORBIT_SPEED
  phi = Math.max(0.05, Math.min(Math.PI - 0.05, phi))
  cam.eye = [
    tx + r * Math.sin(phi) * Math.sin(theta),
    ty + r * Math.cos(phi),
    tz + r * Math.sin(phi) * Math.cos(theta),
  ]
}

function _zoomCamera(cam, delta) {
  const dir = cam.eye.map((v, i) => v - cam.target[i])
  const r   = Math.sqrt(dir.reduce((s, v) => s + v * v, 0))
  const scale = Math.max(0.2, 1.0 + delta * ZOOM_SPEED)
  cam.eye = cam.eye.map((v, i) => cam.target[i] + (dir[i] / r) * r * scale)
}

function _updateCameraFromInput(cameraRef, inputRef, frameRef, resetAccum) {
  const keys = inputRef.current.keys
  if (keys.size === 0) return
  const cam = cameraRef.current
  const fwd = _normalise([cam.target[0]-cam.eye[0], 0, cam.target[2]-cam.eye[2]])
  const right = _normalise(_cross(fwd, [0,1,0]))
  const move = (dx, dy, dz) => {
    cam.eye    = [cam.eye[0]+dx, cam.eye[1]+dy, cam.eye[2]+dz]
    cam.target = [cam.target[0]+dx, cam.target[1]+dy, cam.target[2]+dz]
  }
  let moved = false
  if (keys.has('KeyW')) { move(fwd[0]*PAN_SPEED, 0, fwd[2]*PAN_SPEED); moved = true }
  if (keys.has('KeyS')) { move(-fwd[0]*PAN_SPEED, 0, -fwd[2]*PAN_SPEED); moved = true }
  if (keys.has('KeyA')) { move(-right[0]*PAN_SPEED, 0, -right[2]*PAN_SPEED); moved = true }
  if (keys.has('KeyD')) { move(right[0]*PAN_SPEED, 0, right[2]*PAN_SPEED); moved = true }
  if (keys.has('Space'))     { move(0,  PAN_SPEED, 0); moved = true }
  if (keys.has('ShiftLeft')) { move(0, -PAN_SPEED, 0); moved = true }
  if (moved) {
    frameRef.current.index = 0
    resetAccum()
  }
}

