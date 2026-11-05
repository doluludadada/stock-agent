import { defineConfig, devices } from '@playwright/test'

const PORT = 5199

/**
 * The E2E suite drives the real app against a real backend: start one first (for example
 * `.claude/skills/verify-stock-agent/bin/verify-stock-agent serve <run-id> 8810` from the repository root) and pass
 * its address through E2E_API_URL. On a backend with no user yet, E2E_SETUP_CODE is the setup code it printed on its
 * console: accounts.spec.ts sets up the administrator with it, and the other specs sign in as that administrator.
 * E2E_SETTINGS_DIR is that backend's own disposable config/ folder: settings.spec.ts edits a file there the way an
 * administrator with a shell would, and skips those tests without it. Nothing here mocks the API.
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180_000,
  // A save through the real backend can take several seconds on a busy machine.
  expect: { timeout: 15_000 },
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    locale: 'zh-TW',
    timezoneId: 'Asia/Taipei',
    colorScheme: 'dark',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
  webServer: {
    command: `bun run dev --port ${PORT} --strictPort`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: true,
    timeout: 60_000,
    env: { STOCK_AGENT_API_URL: process.env.E2E_API_URL ?? 'http://127.0.0.1:8810' },
  },
})
