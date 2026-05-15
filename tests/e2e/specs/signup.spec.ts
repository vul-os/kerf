/**
 * signup.spec.ts — sign-up + sign-in flow (cloud mode only).
 *
 * These tests only apply when KERF_LOCAL_MODE is NOT set (cloud build).
 * In local mode the app auto-bootstraps a singleton user and the /signup
 * route redirects immediately to /projects, making these assertions vacuous.
 *
 * TODO: wire up a real cloud-mode e2e environment (separate DATABASE_URL,
 * SMTP stub, etc.) then remove the skip.
 */

import { test } from '@playwright/test'

test.describe('Signup / signin (cloud mode)', () => {
  test.skip(
    !process.env.KERF_CLOUD_MODE,
    'signup tests require KERF_CLOUD_MODE=true — skipped in local mode',
  )

  test('fill signup form and redirect to /projects', async ({ page }) => {
    await page.goto('/signup')
    // TODO: implement
  })

  test('login with existing credentials and redirect to /projects', async ({ page }) => {
    await page.goto('/login')
    // TODO: implement
  })
})
