// Thin accessor for the build-time version global injected by Vite.
// Wrapping it in a function lets call-sites remain testable without
// reaching into the global namespace directly.

/* global __APP_VERSION__ */

// __APP_VERSION__ is a build-time constant injected by Vite's `define` plugin
// (vite.config.js: `define: { __APP_VERSION__: JSON.stringify(pkg.version) }`),
// which does literal identifier substitution — it must stay a bare identifier
// reference below, not a globalThis property access, or the substitution
// won't fire. Not declared in src/types/global.d.ts (T-500's file, no other
// slice needs this), so it's declared locally here instead.
declare const __APP_VERSION__: string

/** Returns the app version string (e.g. "0.1.0"). */
export function appVersion(): string {
  // In tests the global may be set on globalThis directly.
  try {
     
    return __APP_VERSION__
  } catch {
    return (globalThis as { __APP_VERSION__?: string }).__APP_VERSION__ ?? ''
  }
}
