/**
 * terminal.spec.ts — the terminal tab runs a real shell with `kerf` on PATH.
 *
 * The unit tests cover the pieces: the PTY, the listen-address gate, the URL
 * and frame handling. None of them cover the thing the feature actually is —
 * that opening the tab in a browser gets you a shell you can type into, over a
 * WebSocket, with the CLI already pointed at the node you are looking at.
 *
 * That is a lot of moving parts (xterm.js, a WebSocket upgrade through
 * uvicorn, pty.fork, PATH injection) and any one of them failing leaves the
 * others looking fine, so it is worth one end-to-end pass.
 *
 * Two tests, not six. Every one of them opens a project, mounts xterm and
 * forks a login shell that sources the user's profile — which on a developer
 * machine means nvm and conda — and the extra load was enough to make
 * unrelated specs miss their deadlines. Anything that can share one session
 * does.
 *
 * The test servers bind loopback, so the terminal is available without any
 * opt-in — the same reason it is available on a desktop install, and the case
 * worth testing.
 */
import { test, expect, type Page } from '@playwright/test'
import { ProjectsPage } from '../pages/ProjectsPage'
import { EditorPage } from '../pages/EditorPage'

const uid = () => `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`

/** The terminal is a panel in the editor, so a project has to exist first. */
async function openEditorWithTerminal(page: Page) {
  const pp = new ProjectsPage(page)
  await pp.goto()
  await pp.waitForList()
  await pp.createProject(`e2e-terminal-${uid()}`)
  await page.waitForURL(/\/projects\//, { timeout: 20_000 })

  const ep = new EditorPage(page)
  await ep.waitForLoad()
  await showTerminal(page)
}

async function showTerminal(page: Page) {
  await page.getByTestId('right-drawer-tab-terminal').click()
  // "connected" is the socket's own status line, so waiting on it means the
  // shell exists rather than that a div rendered.
  await expect(page.getByText('connected', { exact: true })).toBeVisible({ timeout: 30_000 })
  await expect(page.locator('.xterm-screen')).toBeVisible()
}

/** Everything currently on screen, whitespace-collapsed. */
async function screen(page: Page): Promise<string> {
  return (await page.locator('.xterm-rows').innerText()).replace(/\s+/g, ' ')
}

/**
 * Type a command and wait for its output.
 *
 * xterm renders into rows of spans and a shell echoes what you type, so the
 * command text appears whether or not it ran. Every probe below therefore
 * greps for something only the *output* can contain — which is why the markers
 * are written with an empty string spliced in.
 */
async function run(page: Page, command: string, expected: RegExp) {
  await page.locator('.xterm-screen').click()
  // Paced, not blasted: xterm turns each keypress into a separate WebSocket
  // frame, and typing 20-odd of them in as many milliseconds is not something
  // a person does. The client holds input across a reconnect now, so nothing
  // is lost either way — this just keeps the test typing at human speed.
  await page.keyboard.type(`${command}\n`, { delay: 15 })
  await expect.poll(() => screen(page), { timeout: 30_000 }).toMatch(expected)
}

test.describe('Terminal (local mode)', () => {
  // The suite default is 120s, and the first test alone makes four shell
  // round-trips that each wait up to 30s — a budget that cannot hold its own
  // contents. Every probe is a real fork/exec/echo through a WebSocket, which
  // is slow in a way no amount of tuning fixes.
  test.setTimeout(240_000)

  test('opens a shell with kerf on PATH and pointed at this node', async ({ page }) => {
    await openEditorWithTerminal(page)

    // It is a shell, and it runs things.
    await run(page, 'echo kerf-e2e""-probe', /kerf-e2e-probe/)

    // KERF_TERMINAL is what a prompt or a script keys off to know where it is.
    await run(page, 'echo "marker:$KERF_TERMINAL"', /marker:1/)

    // Without KERF_API_URL, `kerf tools list` inside this terminal talks to
    // the hosted endpoint and asks for a token — a confusing thing to meet in
    // a terminal running inside the node you meant. Never a wildcard: that is
    // a bind address, not something a client can dial.
    await run(page, 'echo "api:$KERF_API_URL"', /api:http:\/\/(127\.0\.0\.1|localhost):\d+/)

    // The whole point of the feature. A desktop build's server is a frozen
    // binary and a pip install may sit in an unactivated venv; in neither case
    // is `kerf` on the user's login-shell PATH by default.
    await run(page, 'command -v kerf >/dev/null && echo "cli:found" || echo "cli:missing"', /cli:found/)
  })

  test('the shell survives closing and re-opening the panel', async ({ page }) => {
    // Sessions outlive their socket so that closing a laptop does not kill a
    // running build. Switching tabs unmounts the panel, which is the cheapest
    // way to drop the socket without dropping the session.
    await openEditorWithTerminal(page)
    await run(page, 'REMEMBERED=kerf-e2e""-persisted; echo stored', /stored/)

    await page.getByTestId('right-drawer-tab-chat').click()
    await expect(page.locator('.xterm-screen')).toHaveCount(0)

    await showTerminal(page)

    // Re-attaching clears the screen and replays the scrollback. Typing into
    // the middle of that replay puts the command on screen and then wipes it,
    // so wait for the replay to land before asking the shell anything.
    await expect.poll(() => screen(page), { timeout: 30_000 }).toMatch(/stored/)

    // A variable set before the socket dropped: only the same shell has it.
    await run(page, 'echo "var:$REMEMBERED"', /var:kerf-e2e-persisted/)
  })
})
