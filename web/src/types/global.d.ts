// global.d.ts — ambient declarations for the Kerf frontend.
//
// Ownership note (G1): this file belongs to **T-500** (toolchain). It exists so the compiler
// understands bundler- and platform-level import forms that are not plain ES modules.
// The *domain* types — FeatureNode, SketchJSON, Mesh, worker protocols, API shapes — belong to
// **T-501** and live in sibling files (`geometry.ts`, `workers.ts`, `api.ts`, ...).
// Slice agents append to those; changes to shared domain types are T-501's owner's call.
//
// `vite/client` (wired via compilerOptions.types) already declares the `?raw` and `?url` suffix
// forms the codebase uses — `pathtracer.wgsl?raw`, `web-ifc.wasm?url`,
// `opencascade.wasm.wasm?url` — so those need nothing here.

/// <reference types="vite/client" />
/// <reference types="@webgpu/types" />

// WebGPU is not in TypeScript's bundled lib.dom. `@webgpu/types` supplies GPUDevice,
// GPUAdapter, GPUCanvasContext and friends, but the `navigator.gpu` entry point still needs
// declaring against the DOM Navigator. Already exercised by
// `src/components/render/PathTracerCanvas.jsx`, and load-bearing for all of G4.
interface Navigator {
  readonly gpu?: GPU
}

// `.wgsl` shader sources are imported with `?raw` (covered by vite/client). A bare `.wgsl`
// import is declared here so a future slice can switch to one without a toolchain change.
declare module '*.wgsl' {
  const source: string
  export default source
}

export {}
