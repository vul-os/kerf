/**
 * Page-object model for /workshop (cloud-only Workshop listing).
 *
 * Workshop is a cloud-enabled feature (gated behind `cloudEnabled`). These
 * selectors are scaffolded for future specs — the actual workshop tests are
 * marked test.skip() until cloud mode is wired into the e2e environment.
 */

import { Page, Locator, expect } from '@playwright/test'

export class WorkshopPage {
  readonly page: Page
  readonly heading: Locator
  readonly listingGrid: Locator

  constructor(page: Page) {
    this.page = page
    this.heading = page.getByRole('heading', { name: /workshop/i })
    this.listingGrid = page.locator('[class*="grid"]').first()
  }

  async goto() {
    await this.page.goto('/workshop')
    await expect(this.heading).toBeVisible({ timeout: 15_000 })
  }

  async expectListingVisible(name: string) {
    await expect(this.page.getByText(name, { exact: true })).toBeVisible()
  }
}
