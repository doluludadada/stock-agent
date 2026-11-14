import { readFileSync, realpathSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import type { Browser, Locator, Page } from '@playwright/test'
import { ADMIN, APP_HEADER, apiGet, expect, signIn, test } from './fixtures'

/**
 * The administrator's settings form against a real backend: every setting as a choice and no YAML, saves with the
 * password that the server runs on at once, values the app would refuse held at their field, a member kept out, and an
 * edit made on disk that the running server loads.
 *
 * The test that edits a file on disk needs E2E_SETTINGS_DIR: the config/ folder of the disposable backend the suite
 * runs against. It refuses this repository's own config/.
 */
test.describe.configure({ mode: 'serial' })

type Field = { path: string; kind: string; value: unknown; restart_only: boolean }

const SETTINGS_DIR = process.env.E2E_SETTINGS_DIR ? realpathSync(process.env.E2E_SETTINGS_DIR) : null
const REPOSITORY_CONFIG = path.resolve(import.meta.dirname, '..', '..', 'config')

function onDisk(): string {
  expect(SETTINGS_DIR, 'E2E_SETTINGS_DIR names a disposable backend’s config/').not.toBeNull()
  expect(SETTINGS_DIR, 'never this repository’s own settings').not.toBe(REPOSITORY_CONFIG)
  return path.join(SETTINGS_DIR!, 'appsetting.yaml')
}

async function valueOf(page: Page, setting: string): Promise<unknown> {
  const fields = (await apiGet(page, '/v1/admin/settings')) as Field[]
  return fields.find((field) => field.path === setting)?.value
}

/** The row of one setting: its label, help, control and problems. */
const row = (page: Page, setting: string): Locator => page.locator(`[id="setting-${setting}"]`)

async function openForm(page: Page) {
  await signIn(page)
  await page.goto('/admin/settings')
  await expect(page.getByRole('switch', { name: '開放註冊' })).toBeVisible({ timeout: 60_000 })
}

async function saveWithPassword(page: Page, password = ADMIN.password) {
  await page.getByRole('button', { name: '儲存', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '儲存設定？' })
  await dialog.getByLabel('你的密碼').fill(password)
  await dialog.getByRole('button', { name: '儲存並套用' }).click()
  return dialog
}

const SAVED = '已儲存，伺服器已改用新設定。'

/** The operator's typed settings stay folded until asked for. */
async function openAdvanced(page: Page) {
  await page.getByRole('navigation', { name: '跳到設定分類' }).getByRole('button', { name: '進階設定' }).click()
}

test('an administrator changes the AI temperature, saves it with the password, and the server runs on it at once', async ({ page, consoleErrors }) => {
  void consoleErrors
  await openForm(page)
  const current = await valueOf(page, 'ai.temperature')
  const next = current === 0.4 ? 0.5 : 0.4

  await expect(page.getByText(/appsetting\.yaml|YAML/), 'the page shows no YAML').toHaveCount(0)
  await expect(page.getByRole('spinbutton'), 'no number is typed').toHaveCount(0)
  await page.getByRole('slider', { name: '溫度' }).fill(String(next))
  await saveWithPassword(page)

  await expect(page.getByText(SAVED)).toBeVisible({ timeout: 60_000 })
  expect(await valueOf(page, 'ai.temperature'), 'the server answers the saved value').toBe(next)
  await expect(page.getByRole('slider', { name: '溫度' })).toHaveValue(String(next))
  await expect(page.getByRole('button', { name: '儲存', exact: true })).toBeDisabled()
  if (SETTINGS_DIR) {
    const text = readFileSync(onDisk(), 'utf8')
    expect(text, 'the file holds the value').toContain(`temperature: ${next}`)
    expect(text, 'and keeps its comments').toContain('# claude reads ANTHROPIC_API_KEY')
  }
})

test('a wrong password saves nothing and keeps the session; the right one saves a map edited as JSON', async ({ page, consoleErrors }) => {
  void consoleErrors
  await openForm(page)
  const models = (await valueOf(page, 'ai.available_models')) as Record<string, string>
  const grok = models.grok === 'grok-4.7' ? 'grok-4.8' : 'grok-4.7'

  await openAdvanced(page)
  const box = row(page, 'ai.available_models').getByRole('textbox')
  await box.fill(JSON.stringify({ ...models, grok }, null, 2))
  const dialog = await saveWithPassword(page, 'not the administrator password')
  await expect(dialog.getByText('密碼不正確，沒有儲存任何內容。')).toBeVisible({ timeout: 60_000 })
  expect(await valueOf(page, 'ai.available_models'), 'nothing was saved').toEqual(models)
  expect((await page.request.get('/v1/auth/me')).status(), 'a wrong password keeps the session').toBe(200)

  await dialog.getByLabel('你的密碼').fill(ADMIN.password)
  await dialog.getByRole('button', { name: '儲存並套用' }).click()
  await expect(page.getByText(SAVED)).toBeVisible({ timeout: 60_000 })
  expect(await valueOf(page, 'ai.available_models')).toEqual({ ...models, grok })
})

test('a value the app would refuse is held at its field: JSON that does not parse in the browser, a model without its key by the server', async ({ page, consoleErrors }) => {
  void consoleErrors
  await openForm(page)

  await openAdvanced(page)
  await row(page, 'ai.available_models').getByRole('textbox').fill('{"grok": ')
  await expect(row(page, 'ai.available_models')).toContainText('必須是有效的 JSON。')
  await expect(page.getByRole('button', { name: '儲存', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: '放棄修改' }).click()

  const offered = (await valueOf(page, 'ai.user_selectable')) as string[]
  await row(page, 'ai.user_selectable').getByRole('checkbox', { name: 'OpenAI' }).click()
  await saveWithPassword(page)
  await expect(page.getByText(/OPENAI_API_KEY/).first(), 'the server’s refusal shows in the reader’s words').toBeVisible({ timeout: 60_000 })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(await valueOf(page, 'ai.user_selectable'), 'nothing was saved').toEqual(offered)
  await page.getByRole('button', { name: '放棄修改' }).click()
})

test('the environment and the audience show as text with why, and offer no control', async ({ page, consoleErrors }) => {
  void consoleErrors
  await openForm(page)

  for (const setting of ['environment', 'audience']) {
    await expect(row(page, setting)).toContainText('重新啟動應用程式後才會改變。')
    await expect(row(page, setting).getByRole('radiogroup')).toHaveCount(0)
    await expect(row(page, setting).getByRole('combobox')).toHaveCount(0)
  }
})

test('a member is told the page is for administrators, and the server refuses them the settings while they stay signed in', async ({ browser }) => {
  const member = await memberPage(browser)
  await member.goto('/admin/settings')

  await expect(member.getByText('這個頁面只開放管理員')).toBeVisible()
  await expect(member.getByRole('textbox')).toHaveCount(0)
  await expect(member.getByRole('navigation', { name: '主要導覽' }).getByRole('link', { name: '系統設定' })).toHaveCount(0)
  expect((await member.request.get('/v1/admin/settings')).status(), 'the server refuses the settings').toBe(403)
  expect((await member.request.get('/v1/auth/me')).status(), 'and keeps the session').toBe(200)
  await member.context().close()
})

test('an edit made on disk is loaded by the running server, and the form shows it', async ({ page, consoleErrors }) => {
  void consoleErrors
  test.skip(SETTINGS_DIR === null, 'E2E_SETTINGS_DIR is not set')
  const file = onDisk()
  const original = readFileSync(file, 'utf8')
  await openForm(page)
  const current = /^ {2}temperature: ([\d.]+)$/m.exec(original)![1]!
  const edited = current === '0.6' ? '0.5' : '0.6'

  try {
    writeFileSync(file, original.replace(`  temperature: ${current}`, `  temperature: ${edited}`))
    await expect.poll(() => valueOf(page, 'ai.temperature'), { message: 'the server reads the file it found', timeout: 60_000 }).toBe(Number(edited))
    await page.reload()
    await expect(page.getByRole('slider', { name: '溫度' })).toHaveValue(edited, { timeout: 60_000 })
  } finally {
    writeFileSync(file, original)
  }
})

const MEMBER = { username: 'e2e-settings-member', email: 'e2e-settings-member@example.com', password: 'e2e member pass phrase' }

/** A signed-in user of the role user, registered through the API the first time; registering does not sign in. */
async function memberPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext({ locale: 'zh-TW', timezoneId: 'Asia/Taipei' })
  const page = await context.newPage()
  const registered = await page.request.post('/v1/auth/register', { headers: APP_HEADER, data: MEMBER })
  expect([201, 409], `registering the member answered ${registered.status()}`).toContain(registered.status())
  const signedIn = await page.request.post('/v1/auth/sign-in', { headers: APP_HEADER, data: { identifier: MEMBER.username, password: MEMBER.password } })
  expect(signedIn.ok(), `the member signs in (${signedIn.status()})`).toBe(true)
  return page
}
