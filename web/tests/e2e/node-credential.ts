/**
 * node-credential.ts — the password the suite claims each test node with.
 *
 * Kept out of auth.setup.ts because Playwright refuses to let one test file
 * import another, and the specs that seed data over the API need this value
 * too: with accounts gone, signing in with the node password is the only way
 * to get a token.
 */
import path from 'node:path'

/** Not a secret: these nodes are ephemeral, loopback-only and rebuilt per run. */
export const E2E_NODE_PASSWORD = 'e2e-node-passw0rd'

/**
 * Where auth.setup.ts writes a stack's signed-in browser state.
 *
 * Beside the suite, not the cwd: playwright may be invoked from either the
 * repo root or tests/e2e, and a state file that lands in a different place
 * each time is a state file the projects cannot find.
 */
export function storageStatePath(stack: string): string {
  return path.join(__dirname, '.auth', `${stack}.json`)
}
