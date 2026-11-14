import path from 'node:path'
import type { Page } from '@playwright/test'
import { apiGet, expect, test } from './fixtures'

/**
 * Sign-in with Google against a real backend and a stand-in for Google (backend/tests/support/fake_google.py, run as a
 * script), from an installation with no user to an administrator who saves a setting.
 *
 * It runs only with E2E_GOOGLE_ADMIN: an email of the backend's accounts.google_administrator_emails. The backend has
 * no user yet, offers sign-in with Google (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, accounts.public_origin set to this
 * suite's address) and points its Google addresses at the stand-in. Serve the stand-in on `localhost` and the app on
 * `127.0.0.1`: the two names are different sites to a browser, as Google and the site are, so the cookies cross a real
 * site boundary. E2E_EVIDENCE names a folder for the screenshots.
 */
const ADMIN_EMAIL = process.env.E2E_GOOGLE_ADMIN ?? ''
const EVIDENCE = process.env.E2E_EVIDENCE

test.describe.configure({ mode: 'serial' })
test.skip(ADMIN_EMAIL === '', 'E2E_GOOGLE_ADMIN names an administrator email of a backend that offers sign-in with Google')

async function shot(page: Page, name: string) {
  if (EVIDENCE) await page.screenshot({ path: path.join(EVIDENCE, `${name}.png`), fullPage: true })
}

/** The stand-in's page, where a person would sign in to Google: who signs in, and how long ago they authenticated. */
async function signInAtGoogle(page: Page, email: string, authenticatedMinutesAgo = 0) {
  await expect(page.getByRole('heading', { name: 'Fake Google' })).toBeVisible()
  expect(new URL(page.url()).hostname, 'Google is another site than the app').not.toBe(new URL(test.info().project.use.baseURL!).hostname)
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Authenticated minutes ago').fill(String(authenticatedMinutesAgo))
  await page.getByRole('button', { name: 'Sign in' }).click()
}

async function cookieNames(page: Page): Promise<Record<string, { sameSite: string; httpOnly: boolean; path: string }>> {
  const cookies = await page.context().cookies(new URL('/v1/auth/google/callback', page.url()).toString())
  return Object.fromEntries(cookies.map((cookie) => [cookie.name, { sameSite: cookie.sameSite, httpOnly: cookie.httpOnly, path: cookie.path }]))
}

test('an email off the lists is refused on the setup page and creates no account', async ({ page, consoleErrors }) => {
  void consoleErrors
  await page.goto('/')
  await expect(page).toHaveURL(/\/setup$/)
  await shot(page, '1-setup-offers-google')

  await page.getByRole('link', { name: '使用 Google 登入' }).click()
  await signInAtGoogle(page, 'stranger@example.com')

  await expect(page).toHaveURL(/\/setup\?google=not_allowed$/)
  await expect(page.getByRole('alert')).toContainText('不在網站允許的名單內')
  expect(((await apiGet(page, '/v1/auth/status')) as { needs_first_administrator: boolean }).needs_first_administrator).toBe(true)
  expect(Object.keys(await cookieNames(page)), 'no session and no flow cookie is left').toEqual([])
  await shot(page, '2-stranger-refused')
})

test('the administrator email sets up the site through Google and saves a setting after signing in to Google again', async ({ page, consoleErrors }) => {
  void consoleErrors
  await page.goto('/')
  await page.getByRole('link', { name: '使用 Google 登入' }).click()
  await signInAtGoogle(page, ADMIN_EMAIL)

  await expect(page, 'the callback sends the browser to the app').toHaveURL(/\/$/)
  const me = (await apiGet(page, '/v1/auth/me')) as { role: string; email: string; has_password: boolean; user_id: string }
  expect(me).toMatchObject({ role: 'administrator', email: ADMIN_EMAIL, has_password: false, user_id: 'local' })
  expect(await cookieNames(page), 'the session cookie keeps its flags, and the flow cookie is gone').toEqual({
    stock_agent_session: { sameSite: 'Strict', httpOnly: true, path: '/v1' },
  })
  await expect(page.getByRole('button', { name: /帳號選單/ })).toBeVisible()
  await shot(page, '3-signed-in-as-administrator')

  await page.goto('/admin/settings')
  const temperature = page.getByRole('slider', { name: '溫度' })
  await expect(temperature).toBeVisible({ timeout: 60_000 })
  const before = Number(await temperature.inputValue())
  const next = before === 0.4 ? 0.5 : 0.4
  await temperature.fill(String(next))
  await page.getByRole('button', { name: '儲存', exact: true }).click()
  const dialog = page.getByRole('alertdialog', { name: '儲存設定？' })
  await expect(dialog.getByLabel('你的密碼'), 'no password is asked of an account without one').toHaveCount(0)
  await shot(page, '4-confirm-with-google')
  await dialog.getByRole('button', { name: '用 Google 確認' }).click()
  await signInAtGoogle(page, ADMIN_EMAIL, 30)

  await expect(page).toHaveURL(/\/admin\/settings$/)
  await expect(page.getByText(/Google 沒有要求你重新登入/)).toBeVisible()
  await expect(temperature, 'what was typed came back').toHaveValue(String(next))
  const fields = (await apiGet(page, '/v1/admin/settings')) as { path: string; value: unknown }[]
  expect(fields.find((field) => field.path === 'ai.temperature')?.value, 'a stale authentication saved nothing').toBe(before)
  await shot(page, '5-stale-authentication-refused')

  await page.getByRole('button', { name: '儲存', exact: true }).click()
  await page.getByRole('alertdialog', { name: '儲存設定？' }).getByRole('button', { name: '用 Google 確認' }).click()
  await signInAtGoogle(page, ADMIN_EMAIL)

  await expect(page.getByText('已儲存，伺服器已改用新設定。')).toBeVisible({ timeout: 60_000 })
  const saved = (await apiGet(page, '/v1/admin/settings')) as { path: string; value: unknown }[]
  expect(saved.find((field) => field.path === 'ai.temperature')?.value, 'the server runs on the saved value').toBe(next)
  await expect(page.getByRole('button', { name: '儲存', exact: true })).toBeDisabled()
  await shot(page, '6-saved-after-fresh-authentication')
})
