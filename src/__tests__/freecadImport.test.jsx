// freecadImport.test.jsx — T9 frontend FreeCAD import coverage.
//
// Covers:
//   1. isFCStdFile() extension matching (case-insensitive, non-.FCStd rejected)
//   2. api.importFreecadProject stub — always rejects with T7-pending error
//   3. T7 hook identifier: the stub error.code === 'FREECAD_T7_PENDING' so T7
//      can be detected cleanly when the real endpoint ships.
//
// React component render tests are omitted; @testing-library/react is not
// installed in this project. Component behaviour is covered by the pure-function
// tests here and the stub/error-code contract that FreeCADImportDialog relies on.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { isFCStdFile } from '../components/FreeCADImport.jsx'

// ---- Mock auth store so FreeCADImport can import api.js without crashing ----
vi.mock('../store/auth.js', () => ({
  useAuth: { getState: () => ({ accessToken: 'tok', refreshToken: null }) },
}))

// ---- 1. isFCStdFile extension matching ----------------------------------------

describe('isFCStdFile', () => {
  it('matches .FCStd extension', () => {
    expect(isFCStdFile('bracket.FCStd')).toBe(true)
  })

  it('matches lowercase .fcstd', () => {
    expect(isFCStdFile('bolt.fcstd')).toBe(true)
  })

  it('matches mixed case .FcStD', () => {
    expect(isFCStdFile('gear.FcStD')).toBe(true)
  })

  it('rejects .step files', () => {
    expect(isFCStdFile('model.step')).toBe(false)
  })

  it('rejects .FCStd.zip (double-extension)', () => {
    expect(isFCStdFile('archive.FCStd.zip')).toBe(false)
  })

  it('rejects empty string', () => {
    expect(isFCStdFile('')).toBe(false)
  })

  it('rejects .kicad_sch', () => {
    expect(isFCStdFile('schematic.kicad_sch')).toBe(false)
  })

  it('accepts a File object whose name ends in .FCStd', () => {
    const f = new File([], 'assembly.FCStd', { type: 'application/zip' })
    expect(isFCStdFile(f)).toBe(true)
  })

  it('rejects a File object whose name does not end in .FCStd', () => {
    const f = new File([], 'schematic.kicad_sch')
    expect(isFCStdFile(f)).toBe(false)
  })
})

// ---- 2. api.importFreecadProject stub (T7 pending) ----------------------------

describe('api.importFreecadProject stub', () => {
  let api

  beforeEach(async () => {
    vi.resetModules()
    globalThis.fetch = vi.fn()
    const mod = await import('../lib/api.js')
    api = mod.api
  })

  afterEach(() => {
    vi.restoreAllMocks()
    delete globalThis.fetch
  })

  it('always rejects (never resolves)', async () => {
    await expect(api.importFreecadProject('proj-1', 'blob-1')).rejects.toThrow()
  })

  it('rejects with FREECAD_T7_PENDING code', async () => {
    const err = await api.importFreecadProject('proj-1', 'blob-1').catch((e) => e)
    expect(err.code).toBe('FREECAD_T7_PENDING')
  })

  it('error message mentions T7', async () => {
    const err = await api.importFreecadProject('proj-1', 'blob-1').catch((e) => e)
    expect(err.message).toMatch(/T7/)
  })

  it('error message mentions import_freecad_project', async () => {
    const err = await api.importFreecadProject('proj-1', 'blob-1').catch((e) => e)
    expect(err.message).toMatch(/import_freecad_project/)
  })

  it('does not call fetch (is a pure stub — no HTTP request)', async () => {
    await api.importFreecadProject('proj-1', 'blob-1').catch(() => {})
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })

  it('accepts optional opts argument without throwing', async () => {
    const err = await api
      .importFreecadProject('proj-1', 'blob-1', { importFolder: '/custom', mode: 'project' })
      .catch((e) => e)
    expect(err.code).toBe('FREECAD_T7_PENDING')
  })
})

// ---- 3. T7 hook contract -------------------------------------------------------

describe('T7 hook contract', () => {
  // Documents exactly which identifier T7 must replace in api.js.
  // The real implementation should be:
  //   importFreecadProject: (projectId, fileBlobId, opts = {}) =>
  //     request(`/api/projects/${projectId}/imports/freecad`, {
  //       method: 'POST',
  //       body: {
  //         file_blob_id: fileBlobId,
  //         import_folder: opts.importFolder ?? '/freecad_import',
  //         mode: opts.mode ?? 'project',
  //       },
  //     }),
  //
  // FreeCADImportDialog checks error.code === 'FREECAD_T7_PENDING' to
  // show an honest "awaiting T7" message instead of a generic error.

  it('FREECAD_T7_PENDING sentinel code is stable (changing it breaks the dialog)', async () => {
    vi.resetModules()
    globalThis.fetch = vi.fn()
    const { api: freshApi } = await import('../lib/api.js')
    const err = await freshApi.importFreecadProject('any', 'any').catch((e) => e)
    // This specific string is checked in FreeCADImportDialog.
    expect(err.code).toBe('FREECAD_T7_PENDING')
    delete globalThis.fetch
  })
})
