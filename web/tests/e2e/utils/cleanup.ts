/**
 * Delete the project a spec created, so it doesn't pile up in the shared DB.
 *
 * Specs leave their projects behind, and projects.spec's grid assertions start
 * failing once enough of them accumulate (see issue #5). Every spec ought to do
 * this; new specs at least shouldn't make it worse.
 *
 * The token lives in the zustand-persisted `kerf.auth` key, which is how the app
 * itself authenticates — no separate bootstrap needed.
 */

import { Page } from '@playwright/test'

/** The project id from a /projects/:id URL, or null if we aren't on one. */
export function projectIdFromUrl(page: Page): string | null {
  const m = /\/projects\/([0-9a-f-]{36})/i.exec(page.url())
  return m ? m[1] : null
}

/** Best-effort delete. Never throws — cleanup must not fail a passing test. */
export async function deleteProject(page: Page, projectId: string | null) {
  if (!projectId) return
  try {
    await page.evaluate(async (id) => {
      const raw = window.localStorage.getItem('kerf.auth')
      const token = raw ? JSON.parse(raw)?.state?.accessToken : null
      if (!token) return
      await fetch(`/api/projects/${id}`, {
        method: 'DELETE',
        headers: { authorization: `Bearer ${token}` },
      })
    }, projectId)
  } catch {
    // Page already closed, or auth gone — nothing to do.
  }
}
