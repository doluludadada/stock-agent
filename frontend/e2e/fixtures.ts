import { test as base, expect, type APIRequestContext, type Page } from '@playwright/test'

/**
 * The accounts the suite signs in with. accounts.spec.ts creates the administrator through the first-time setup on a
 * fresh backend (the setup code is in E2E_SETUP_CODE, from the server's console) and registers the user; the other
 * specs sign in as them.
 */
export const ADMIN = {
  username: process.env.E2E_ADMIN_USERNAME ?? 'e2e-admin',
  email: 'e2e-admin@example.com',
  password: process.env.E2E_ADMIN_PASSWORD ?? 'e2e administrator pass',
}
export const MEMBER = { username: 'e2e-mei', email: 'e2e-mei@example.com', password: 'e2e member password' }
export const SETUP_CODE = process.env.E2E_SETUP_CODE ?? ''

/** The header every write carries; the API refuses a write without it (403). */
export const APP_HEADER = { 'X-Requested-With': 'stock-agent' }

/** A refused request the page shows as a state, not a script error: the session probe answers 401 to a visitor. */
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

/**
 * The first administrator, set up through the API when the backend has none yet; accounts.spec.ts drives the same
 * setup through the page. The same browser context then holds the session cookie.
 */
export async function ensureAdministrator(request: APIRequestContext) {
  const status = (await (await request.get('/v1/auth/status')).json()) as { needs_first_administrator: boolean }
  if (!status.needs_first_administrator) return
  expect(SETUP_CODE, 'E2E_SETUP_CODE: the code the server printed at start').not.toBe('')
  const setup = await request.post('/v1/auth/setup', { headers: APP_HEADER, data: { setup_code: SETUP_CODE, ...ADMIN } })
  expect(setup.status(), 'the first administrator').toBe(201)
}

/** Signs this page's browser context in through the API: the server sets the HttpOnly session cookie. */
export async function signIn(page: Page, account: { username: string; password: string } = ADMIN) {
  await ensureAdministrator(page.request)
  const answer = await page.request.post('/v1/auth/sign-in', { headers: APP_HEADER, data: { identifier: account.username, password: account.password } })
  expect(answer.ok(), `sign-in of ${account.username} answered ${answer.status()}`).toBe(true)
}

/** The server's own answer, read with this context's session, for asserting what was really saved. */
export async function apiGet(page: Page, path: string) {
  const response = await page.request.get(path)
  expect(response.ok(), `${path} answered ${response.status()}`).toBe(true)
  return response.json()
}

/** A write as the page would send it, with the app header and this context's session. */
export async function apiWrite(page: Page, method: 'post' | 'put' | 'patch', path: string, data: unknown) {
  const response = await page.request.fetch(path, { method: method.toUpperCase(), headers: APP_HEADER, data })
  expect(response.ok(), `${method.toUpperCase()} ${path} answered ${response.status()}`).toBe(true)
  return response.json()
}
