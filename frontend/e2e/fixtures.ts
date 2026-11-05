import { test as base, expect, type Page } from '@playwright/test'

export const API_URL = process.env.E2E_API_URL ?? 'http://127.0.0.1:8810'
export const OWNER_TOKEN = process.env.E2E_API_TOKEN ?? 'verify-token'
export const ADMIN_TOKEN = process.env.E2E_ADMIN_TOKEN ?? 'verify-admin-token'

/** A refused request the page shows as a state, not a script error. */
const EXPECTED_HTTP = /Failed to load resource: the server responded with a status of (401|403|404|409|422)/

/** Fails the test on any console error or uncaught page error, except the refusals a test provokes on purpose. */
export const test = base.extend<{ consoleErrors: string[] }>({
  consoleErrors: async ({ page }, use) => {
    const errors: string[] = []
    page.on('console', (message) => {
      if (message.type() === 'error' && !EXPECTED_HTTP.test(message.text())) errors.push(message.text())
    })
    page.on('pageerror', (error) => errors.push(error.message))
    await use(errors)
    expect(errors, 'no console errors').toEqual([])
  },
})

export { expect }

export async function horizontalOverflow(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
}

/** Enters the owner's token in the header's unlock dialog; it lives in this page's memory only. */
export async function unlockOwner(page: Page) {
  await page.getByRole('banner').getByRole('button', { name: '解鎖' }).click()
  await page.getByLabel('API token').fill(OWNER_TOKEN)
  await page.getByRole('dialog').getByRole('button', { name: '解鎖' }).click()
  await expect(page.getByRole('banner').getByRole('button', { name: '上鎖' })).toBeVisible()
}

/** The server's own answer, read with the token, for asserting what was really saved. */
export async function apiGet(page: Page, path: string, token = OWNER_TOKEN) {
  const response = await page.request.get(`${API_URL}${path}`, { headers: { Authorization: `Bearer ${token}` } })
  expect(response.ok(), `${path} answered ${response.status()}`).toBe(true)
  return response.json()
}
