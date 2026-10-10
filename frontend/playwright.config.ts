import { defineConfig } from '@playwright/test'

// Same variable the server script reads (scripts/e2e_server.py).
const port = Number(process.env.MAESTRO_E2E_PORT || 6620)

export default defineConfig({
  testDir: './e2e',
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
