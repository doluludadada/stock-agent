import { defineConfig, devices } from '@playwright/test'

const PORT = 5199

/**
 * The E2E suite drives the real app against a real backend: start one first (for example
 * `.claude/skills/verify-stock-agent/bin/verify-stock-agent serve <run-id> 8810` from the repository root) and pass
 * its address and tokens through E2E_API_URL, E2E_API_TOKEN and E2E_ADMIN_TOKEN. Nothing here mocks the API.
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180_000,
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
