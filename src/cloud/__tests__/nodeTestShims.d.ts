// nodeTestShims.d.ts — minimal ambient types for the node:* builtins a few
// tests in this directory use to read sibling source files by literal path
// (GitPanel.contract.test.tsx, PublishButton.test.tsx, Workshop.test.tsx —
// all run under vitest/Node, never bundled).
//
// This repo's tsconfig.json intentionally does NOT put "node" in
// compilerOptions.types (that's shared toolchain config, T-500's, and out of
// this slice's scope to change) — adding it project-wide pulls in
// @types/node's full ambient global surface (`process`, `Buffer`, a
// conflicting `setTimeout`/`global` shape, etc.), which was tried and does
// regress already-migrated files elsewhere (e.g. src/lib/iesLoader.test.ts's
// existing `process` shim collides with @types/node's). So instead: three
// narrow, scoped declarations for exactly the functions these tests call —
// nothing global-polluting beyond the module specifiers themselves, which
// have no type declarations anywhere else in the program today.
//
// If a later slice adds "node" to tsconfig.json's types (T-521/T-522 or a
// dedicated toolchain task), this file becomes redundant and should be
// deleted rather than left to shadow @types/node's richer declarations.

declare module 'node:fs' {
  export function readFileSync(path: string, encoding: string): string
}

declare module 'node:url' {
  export function fileURLToPath(url: string | URL): string
}

declare module 'node:path' {
  export function dirname(path: string): string
  export function join(...paths: string[]): string
  export function resolve(...paths: string[]): string
}
