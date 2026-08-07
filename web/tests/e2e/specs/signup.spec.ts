/**
 * signup.spec.ts — sign-up + sign-in flow (cloud project).
 *
 * Runs under the Playwright `cloud` project, which boots a kerf-server
 * with LOCAL_MODE=false (no local singleton auto-login) so the real /signup and
 * /login pages exist. Register returns tokens immediately (no email
 * verification gate), then the app navigates to /projects.
 */

import { test, expect, type Page } from '@playwright/test'

function uniqueEmail(tag: string) {
  return `e2e-${tag}-${Date.now()}-${Math.floor(Math.random() * 1e4)}@kerf.test`
}

const PASSWORD = 'e2e-passw0rd!'

async function expectProjectsPage(page: Page) {
  // After auth the app navigates to /projects then redirects to the
  // workspace-scoped /w/:slug/projects — assert on the UI, not the URL.
  await expect(
    page.getByRole('heading', { name: 'Projects' }),
  ).toBeVisible({ timeout: 20_000 })
}

test.describe('Signup / signin (cloud mode)', () => {
  test('fill signup form and redirect to /projects', async ({ page }) => {
    const email = uniqueEmail('signup')
    await page.goto('/signup')

    await page.getByLabel('Name').fill('E2E Tester')
    await page.getByLabel('Email').fill(email)
    await page.getByLabel('Password').fill(PASSWORD)
    await page.getByRole('button', { name: 'Create account' }).click()

    await expectProjectsPage(page)
  })

  test('login with existing credentials and redirect to /projects', async ({
    page,
  }) => {
    // Seed a user via the API (proxied through Vite → cloud backend).
    const email = uniqueEmail('login')
    const res = await page.request.post('/auth/register', {
      data: { email, password: PASSWORD, name: 'E2E Login' },
    })
    expect(res.status()).toBe(201)

    await page.goto('/login')
    await page.getByLabel('Email').fill(email)
    await page.getByLabel('Password').fill(PASSWORD)
    await page.getByRole('button', { name: 'Sign in' }).click()

    await expectProjectsPage(page)
  })
})
