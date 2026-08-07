/**
 * Page-object model for /workshop (the distributed DMTAP-PUB Workshop
 * browser — a core MIT node capability present unconditionally, not gated
 * behind any flag). These selectors are scaffolded for future specs; the
 * live coverage today is `tests/e2e/specs/workshop.spec.ts`, which drives
 * the page directly rather than through this object.
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
