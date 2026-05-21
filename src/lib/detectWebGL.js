/**
 * detectWebGL — returns true when WebGL (1 or 2) is available in this browser.
 *
 * Checks webgl2, webgl, then experimental-webgl in order, confirming the
 * returned context is a real WebGLRenderingContext by probing createBuffer.
 *
 * Safe to call in SSR-like / non-DOM environments: returns false if
 * document.createElement is unavailable or throws.
 *
 * T-C4: centralised from JewelryShare.jsx (T-J1 local guard) so all 3D
 * viewports can share a single implementation and test suite.
 */
export function detectWebGL() {
  try {
    if (typeof globalThis.document === 'undefined') return false
    const canvas = globalThis.document.createElement('canvas')
    const ctx =
      canvas.getContext('webgl2') ||
      canvas.getContext('webgl') ||
      canvas.getContext('experimental-webgl')
    if (!ctx) return false
    // Confirm it is a real WebGLRenderingContext, not a stub
    return typeof ctx.createBuffer === 'function'
  } catch {
    return false
  }
}
