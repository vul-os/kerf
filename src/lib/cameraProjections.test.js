/**
 * cameraProjections.test.js — Vitest unit tests for src/lib/cameraProjections.js
 *
 * Three.js is mocked so no WebGL context or canvas is required.
 */

import { describe, it, expect, vi } from 'vitest'

// ── Three.js stub ─────────────────────────────────────────────────────────────
// Minimal mock that satisfies the module under test without WebGL.

vi.mock('three', () => {
  class Vector3 {
    constructor(x = 0, y = 0, z = 0) {
      this.x = x; this.y = y; this.z = z
    }
    clone() { return new Vector3(this.x, this.y, this.z) }
    copy(v) { this.x = v.x; this.y = v.y; this.z = v.z; return this }
    sub(v) { this.x -= v.x; this.y -= v.y; this.z -= v.z; return this }
    length() { return Math.sqrt(this.x ** 2 + this.y ** 2 + this.z ** 2) }
    divideScalar(s) { this.x /= s; this.y /= s; this.z /= s; return this }
    addScaledVector(v, s) {
      this.x += v.x * s; this.y += v.y * s; this.z += v.z * s; return this
    }
    toArray() { return [this.x, this.y, this.z] }
  }

  class PerspectiveCamera {
    constructor(fov, aspect, near, far) {
      this.type       = 'PerspectiveCamera'
      this.fov        = fov
      this.aspect     = aspect
      this.near       = near
      this.far        = far
      this.filmOffset = 0
      this.position   = new Vector3(0, 0, 5)
      this.up         = new Vector3(0, 1, 0)
      this.userData   = {}
    }
    lookAt() {}
    updateProjectionMatrix() {}
  }

  class OrthographicCamera {
    constructor(left, right, top, bottom, near, far) {
      this.type     = 'OrthographicCamera'
      this.left     = left
      this.right    = right
      this.top      = top
      this.bottom   = bottom
      this.near     = near
      this.far      = far
      this.zoom     = 1
      this.position = new Vector3(0, 0, 5)
      this.up       = new Vector3(0, 1, 0)
      this.userData = {}
    }
    lookAt() {}
    updateProjectionMatrix() {}
  }

  return { Vector3, PerspectiveCamera, OrthographicCamera }
})

import {
  CAMERA_PROJECTIONS,
  SENSOR_SIZES,
  focalToFov,
  fovToFocal,
  createCamera,
  swapCameraProjection,
} from './cameraProjections.js'

// ── CAMERA_PROJECTIONS ────────────────────────────────────────────────────────

describe('CAMERA_PROJECTIONS', () => {
  it('contains exactly the five expected kinds', () => {
    expect(CAMERA_PROJECTIONS).toEqual([
      'perspective',
      'orthographic',
      'two-point',
      'fisheye',
      'panoramic-360',
    ])
  })
})

// ── SENSOR_SIZES ──────────────────────────────────────────────────────────────

describe('SENSOR_SIZES', () => {
  it('full-frame is 36 mm', () => {
    expect(SENSOR_SIZES['full-frame']).toBe(36)
  })

  it('aps-c is 23.6 mm', () => {
    expect(SENSOR_SIZES['aps-c']).toBe(23.6)
  })

  it('cinema-35 is 24.89 mm', () => {
    expect(SENSOR_SIZES['cinema-35']).toBe(24.89)
  })

  it('micro-4-3 is 17.3 mm', () => {
    expect(SENSOR_SIZES['micro-4-3']).toBe(17.3)
  })
})

// ── focalToFov ────────────────────────────────────────────────────────────────

describe('focalToFov', () => {
  it('50 mm on full-frame (36 mm) equals 2*atan(36/(2*50)) to 1e-12', () => {
    const expected = 2 * Math.atan(36 / (2 * 50))
    expect(focalToFov(50, 36)).toBeCloseTo(expected, 12)
  })

  it('50 mm on full-frame ≈ 39.60° (horizontal, full-frame)', () => {
    const fov_rad = focalToFov(50, 36)
    const fov_deg = fov_rad * (180 / Math.PI)
    // Horizontal FOV of 50mm on 36mm sensor = 2*atan(36/100) ≈ 39.6°
    expect(fov_deg).toBeCloseTo(39.60, 1)
  })

  it('longer focal length gives narrower FOV', () => {
    expect(focalToFov(200, 36)).toBeLessThan(focalToFov(50, 36))
  })

  it('shorter focal length gives wider FOV', () => {
    expect(focalToFov(24, 36)).toBeGreaterThan(focalToFov(50, 36))
  })

  it('100 mm is roughly half the FOV of 50 mm (paraxial approx)', () => {
    const f50  = focalToFov(50, 36)
    const f100 = focalToFov(100, 36)
    expect(f100 / f50).toBeGreaterThan(0.4)
    expect(f100 / f50).toBeLessThan(0.6)
  })
})

// ── fovToFocal ────────────────────────────────────────────────────────────────

describe('fovToFocal', () => {
  it('round-trips 50 mm full-frame to 1e-12 precision', () => {
    const fov  = focalToFov(50, 36)
    const back = fovToFocal(fov, 36)
    expect(back).toBeCloseTo(50, 12)
  })

  it('round-trips 24 mm APS-C', () => {
    const sensor = SENSOR_SIZES['aps-c']
    const fov    = focalToFov(24, sensor)
    expect(fovToFocal(fov, sensor)).toBeCloseTo(24, 10)
  })

  it('round-trips 200 mm cinema-35', () => {
    const sensor = SENSOR_SIZES['cinema-35']
    const fov    = focalToFov(200, sensor)
    expect(fovToFocal(fov, sensor)).toBeCloseTo(200, 10)
  })

  it('is the exact inverse of focalToFov across a range of focal lengths', () => {
    const focals = [14, 24, 35, 50, 85, 135, 200]
    const sensor = 36
    focals.forEach((f) => {
      const fov = focalToFov(f, sensor)
      expect(fovToFocal(fov, sensor)).toBeCloseTo(f, 10)
    })
  })
})

// ── createCamera ──────────────────────────────────────────────────────────────

describe('createCamera', () => {
  describe('perspective', () => {
    it('returns a PerspectiveCamera', () => {
      const cam = createCamera('perspective', { aspect: 16 / 9, focal_mm: 50, sensor: 'full-frame' })
      expect(cam.type).toBe('PerspectiveCamera')
    })

    it('is not wrapped in a tuple', () => {
      const result = createCamera('perspective')
      expect(result.camera).toBeUndefined()
    })
  })

  describe('orthographic', () => {
    it('returns an OrthographicCamera', () => {
      const cam = createCamera('orthographic', { aspect: 16 / 9, focal_mm: 50, sensor: 'full-frame' })
      expect(cam.type).toBe('OrthographicCamera')
    })

    it('has left < 0 and right > 0', () => {
      const cam = createCamera('orthographic', { aspect: 16 / 9 })
      expect(cam.left).toBeLessThan(0)
      expect(cam.right).toBeGreaterThan(0)
    })

    it('is not wrapped in a tuple', () => {
      const result = createCamera('orthographic')
      expect(result.camera).toBeUndefined()
    })
  })

  describe('two-point', () => {
    it('returns a PerspectiveCamera', () => {
      const cam = createCamera('two-point', { aspect: 16 / 9, focal_mm: 50, sensor: 'full-frame' })
      expect(cam.type).toBe('PerspectiveCamera')
    })

    it('sets userData.twoPoint = true', () => {
      const cam = createCamera('two-point')
      expect(cam.userData.twoPoint).toBe(true)
    })

    it('is not wrapped in a tuple', () => {
      const result = createCamera('two-point')
      expect(result.camera).toBeUndefined()
    })
  })

  describe('fisheye', () => {
    it('returns a {camera, postProcessor} tuple', () => {
      const result = createCamera('fisheye')
      expect(result).toHaveProperty('camera')
      expect(result).toHaveProperty('postProcessor')
    })

    it('inner camera is a PerspectiveCamera', () => {
      const { camera } = createCamera('fisheye')
      expect(camera.type).toBe('PerspectiveCamera')
    })

    it('postProcessor.type is fisheye-stereographic', () => {
      const { postProcessor } = createCamera('fisheye')
      expect(postProcessor.type).toBe('fisheye-stereographic')
    })

    it('postProcessor has captureFov uniform equal to π', () => {
      const { postProcessor } = createCamera('fisheye')
      expect(postProcessor.uniforms.captureFov).toBeDefined()
      expect(postProcessor.uniforms.captureFov.value).toBeCloseTo(Math.PI)
    })

    it('inner camera userData.kind is fisheye', () => {
      const { camera } = createCamera('fisheye')
      expect(camera.userData.kind).toBe('fisheye')
    })
  })

  describe('panoramic-360', () => {
    it('returns a {camera, postProcessor} tuple', () => {
      const result = createCamera('panoramic-360')
      expect(result).toHaveProperty('camera')
      expect(result).toHaveProperty('postProcessor')
    })

    it('inner camera is a PerspectiveCamera', () => {
      const { camera } = createCamera('panoramic-360')
      expect(camera.type).toBe('PerspectiveCamera')
    })

    it('postProcessor.type is equirectangular', () => {
      const { postProcessor } = createCamera('panoramic-360')
      expect(postProcessor.type).toBe('equirectangular')
    })

    it('postProcessor hFov uniform is 2π (full 360°)', () => {
      const { postProcessor } = createCamera('panoramic-360')
      expect(postProcessor.uniforms.hFov.value).toBeCloseTo(2 * Math.PI)
    })

    it('postProcessor vFov uniform is π (full 180°)', () => {
      const { postProcessor } = createCamera('panoramic-360')
      expect(postProcessor.uniforms.vFov.value).toBeCloseTo(Math.PI)
    })

    it('inner camera userData.kind is panoramic-360', () => {
      const { camera } = createCamera('panoramic-360')
      expect(camera.userData.kind).toBe('panoramic-360')
    })
  })

  it('throws on an unknown kind', () => {
    expect(() => createCamera('pinhole')).toThrow(/unknown projection kind/)
  })

  it('accepts sensor as a raw number', () => {
    const cam = createCamera('perspective', { sensor: 24, focal_mm: 50 })
    expect(cam.type).toBe('PerspectiveCamera')
  })

  it('accepts sensor as a string key', () => {
    const cam = createCamera('perspective', { sensor: 'aps-c', focal_mm: 35 })
    expect(cam.type).toBe('PerspectiveCamera')
  })
})

// ── swapCameraProjection ──────────────────────────────────────────────────────

// Minimal old-camera stub that satisfies swapCameraProjection without THREE.
function makeOldCam(pos = [0, 0, 100]) {
  return {
    type: 'PerspectiveCamera',
    position: {
      x: pos[0], y: pos[1], z: pos[2],
      clone() { return { x: this.x, y: this.y, z: this.z } },
    },
    up: {
      x: 0, y: 1, z: 0,
      clone() { return { x: 0, y: 1, z: 0, copy() {} } },
      copy() {},
    },
    userData: {},
  }
}

describe('swapCameraProjection', () => {
  it('preserves the orbit target position field after swap', () => {
    const oldCam = makeOldCam([0, 0, 100])
    const result = swapCameraProjection(oldCam, 'perspective', {
      target: [10, 20, 30],
      distance: 50,
    })
    const newCam = result?.camera ?? result
    expect(newCam.userData.orbitTarget).toBeDefined()
    expect(newCam.userData.orbitTarget.x).toBeCloseTo(10)
    expect(newCam.userData.orbitTarget.y).toBeCloseTo(20)
    expect(newCam.userData.orbitTarget.z).toBeCloseTo(30)
  })

  it('returns an OrthographicCamera when swapping to orthographic', () => {
    const oldCam = makeOldCam()
    const result = swapCameraProjection(oldCam, 'orthographic', { target: [0, 0, 0] })
    const cam = result?.camera ?? result
    expect(cam.type).toBe('OrthographicCamera')
  })

  it('returns a {camera, postProcessor} tuple when swapping to fisheye', () => {
    const oldCam = makeOldCam()
    const result = swapCameraProjection(oldCam, 'fisheye', { target: [0, 0, 0] })
    expect(result).toHaveProperty('camera')
    expect(result).toHaveProperty('postProcessor')
  })

  it('returns a {camera, postProcessor} tuple when swapping to panoramic-360', () => {
    const oldCam = makeOldCam()
    const result = swapCameraProjection(oldCam, 'panoramic-360', { target: [0, 0, 0] })
    expect(result).toHaveProperty('camera')
    expect(result).toHaveProperty('postProcessor')
  })

  it('inherits orbitTarget from oldCam.userData.orbitTarget when present', () => {
    const oldCam = makeOldCam([0, 0, 100])
    // Attach a pre-existing orbitTarget (simulating what OrbitControls would store).
    // Must have clone/sub/length/divideScalar/addScaledVector to satisfy swapCameraProjection.
    oldCam.userData.orbitTarget = {
      x: 5, y: 10, z: 15,
      clone() {
        const t = { ...this }
        t.clone = this.clone
        t.sub = this.sub
        t.length = this.length
        t.divideScalar = this.divideScalar
        t.addScaledVector = this.addScaledVector
        return t
      },
      sub(v) { this.x -= v.x; this.y -= v.y; this.z -= v.z; return this },
      length() { return Math.sqrt(this.x ** 2 + this.y ** 2 + this.z ** 2) },
      divideScalar(s) { this.x /= s; this.y /= s; this.z /= s; return this },
      addScaledVector(v, s) {
        this.x += v.x * s; this.y += v.y * s; this.z += v.z * s; return this
      },
    }
    const result = swapCameraProjection(oldCam, 'two-point', {})
    const cam = result?.camera ?? result
    expect(cam.userData.orbitTarget.x).toBeCloseTo(5)
    expect(cam.userData.orbitTarget.y).toBeCloseTo(10)
    expect(cam.userData.orbitTarget.z).toBeCloseTo(15)
  })

  it('returns a PerspectiveCamera for two-point projection', () => {
    const oldCam = makeOldCam()
    const result = swapCameraProjection(oldCam, 'two-point', { target: [0, 0, 0] })
    const cam = result?.camera ?? result
    expect(cam.type).toBe('PerspectiveCamera')
  })
})
