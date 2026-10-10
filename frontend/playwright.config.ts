import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from '@playwright/test'

// Same variable the server script reads (scripts/e2e_server.py). Without it, each worktree gets
// its own port in 6620..6659 (a stable hash of this folder), so runs from different worktrees
// do not collide. It is written back to the environment so the server and the workers, which
// load this file again, land on the same value.
if (!process.env.MAESTRO_E2E_PORT) {
  const dir = dirname(fileURLToPath(import.meta.url))
  const hash = [...dir].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7)
  process.env.MAESTRO_E2E_PORT = String(6620 + (hash % 40))
}
const port = Number(process.env.MAESTRO_E2E_PORT)

export default defineConfig({
  testDir: './e2e',
  forbidOnly: !!process.env.CI,
  // `.e2e.ts` keeps Vitest (which looks for *.test.ts and *.spec.ts) away from these files.
  testMatch: '**/*.e2e.ts',
  // One seeded database, so one worker and no parallel files.
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  expect: { timeout: 10_000 },
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    channel: 'chrome',
    headless: true,
    // The app marks elements with `data-test`, not `data-testid`.
    testIdAttribute: 'data-test',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'uv run python scripts/e2e_server.py',
    cwd: '..',
    // The root serves index.html, so it answers 200 as soon as the app is up.
    url: `http://127.0.0.1:${port}/`,
    // The first run may compile the frontend.
    timeout: 240_000,
    reuseExistingServer: false,
    // Playwright kills the server with SIGKILL by default, which skips its cleanup of the
    // temporary directory. SIGTERM lets scripts/e2e_server.py delete it.
    gracefulShutdown: { signal: 'SIGTERM', timeout: 10_000 },
  },
})
