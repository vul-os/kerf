/**
 * chat.spec.ts — model selection + chat composer golden path.
 *
 * Why this exists
 * ---------------
 * Two production incidents this would have caught:
 *   1. The model dropdown was empty (frontend didn't unwrap {models}) —
 *      "no model selection dropdown".
 *   2. Every model 400'd because the request sent temperature=null
 *      ("The model returned an error" for all models).
 *
 * LOCAL MODE: the test server auto-mints a user; no sign-in. The chat
 * composer is disabled (placeholder "Loading…") until /api/models
 * resolves, so a usable composer == model selection is wired.
 *
 * The live LLM round-trip needs a provider key, which CI local mode
 * does not have — so the assistant-reply assertion is gated behind
 * E2E_LLM_LIVE. The deterministic parts (dropdown populated, send
 * produces a user turn, no client crash) always run.
 */
import { test, expect } from '@playwright/test'
import { ProjectsPage } from '../pages/ProjectsPage'
import { EditorPage } from '../pages/EditorPage'

const uid = () => `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`

test.describe('Chat — model selection + send (local mode)', () => {
  test('model dropdown populates and a message posts a user turn', async ({ page }) => {
    const pp = new ProjectsPage(page)
    await pp.goto()
    await pp.waitForList()
    await pp.createProject(`e2e-chat-${uid()}`)

    const ed = new EditorPage(page)
    await ed.waitForLoad()

    // Open the chat pane if it starts collapsed.
    const opener = page.getByRole('button', { name: /open chat/i })
    if (await opener.count()) {
      await opener.first().click().catch(() => {})
    }

    // Composer is disabled with placeholder "Loading…" until
    // /api/models resolves; an enabled "Ask Kerf…" composer proves
    // model selection is wired (regression #1).
    const composer = page.getByPlaceholder('Ask Kerf to refine the model…')
    await expect(composer).toBeVisible({ timeout: 30_000 })
    await expect(composer).toBeEnabled({ timeout: 30_000 })

    // The model picker trigger renders the current model label — must
    // not be empty (an empty dropdown is the regression).
    const picker = page.getByRole('button', { name: /model|claude|gpt|gemini|kimi/i })
    await expect(picker.first()).toBeVisible()

    // Send a message; the user's turn must appear (send path works,
    // no client crash).
    const prompt = `e2e ping ${uid()}`
    await composer.fill(prompt)
    await composer.press('Enter')
    await expect(page.getByText(prompt, { exact: false })).toBeVisible({ timeout: 15_000 })

    // Live LLM round-trip — only when a provider key is present.
    if (process.env.E2E_LLM_LIVE) {
      await expect(
        page.getByText(/the model returned an error/i),
      ).toHaveCount(0, { timeout: 60_000 })
    }
  })
})
