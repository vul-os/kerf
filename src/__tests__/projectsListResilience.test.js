// projectsListResilience.test.js — the Projects page must not render a
// permanent blank list when the workspace store hasn't resolved yet
// (right after sign-in / create-project). Bailing with setProjects([])
// on null activeWorkspaceId left "i created a project and the list is
// blank". api.listProjects() with no id returns all the user's
// projects, so the page now always fetches and refetches scoped once
// the workspace resolves.

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const src = readFileSync(
  path.resolve(__dirname, '../routes/Projects.jsx'), 'utf8',
)

describe('Projects list resilience', () => {
  it('no longer bails to an empty list when no workspace is resolved', () => {
    expect(src).not.toMatch(/if \(!activeWorkspaceId\)\s*\{\s*setProjects\(\[\]\);\s*return\s*\}/)
  })

  it('fetches projects unscoped when activeWorkspaceId is null', () => {
    expect(src).toContain('listProjects(activeWorkspaceId || undefined)')
  })

  it('shows a loading state (setProjects(null)) while fetching', () => {
    expect(src).toContain('setProjects(null)')
  })
})

describe('Projects page: Import FreeCAD removed', () => {
  it('has no Import FreeCAD button or dialog', () => {
    expect(src).not.toContain('Import FreeCAD')
    expect(src).not.toContain('FreeCADImportDialog')
    expect(src).not.toContain('openFreecadImport')
  })

  it('still has the New project action', () => {
    expect(src).toContain('New project')
  })
})
