import { readFileSync, realpathSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import type { Browser, Page } from '@playwright/test'
import { ADMIN, APP_HEADER, apiGet, expect, signIn, test } from './fixtures'

/**
 * The administrator's settings editor against a real backend: edits in the browser's editor, saves with the password,
 * problems at their line and column, text that survives a reload and a visit elsewhere, a member kept out, and edits
 * made on disk that the running server loads, or refuses with its reasons.
 *
 * The tests that edit a file on disk need E2E_SETTINGS_DIR: the config/ folder of the disposable backend the suite
 * runs against. They refuse this repository's own config/.
 */
test.describe.configure({ mode: 'serial' })

type Document = { status: { revision: string; running_revision: string | null }; text: string }

const SETTINGS_DIR = process.env.E2E_SETTINGS_DIR ? realpathSync(process.env.E2E_SETTINGS_DIR) : null
const REPOSITORY_CONFIG = path.resolve(import.meta.dirname, '..', '..', 'config')

function onDisk(): string {
  expect(SETTINGS_DIR, 'E2E_SETTINGS_DIR names a disposable backend’s config/').not.toBeNull()
  expect(SETTINGS_DIR, 'never this repository’s own settings').not.toBe(REPOSITORY_CONFIG)
  return path.join(SETTINGS_DIR!, 'appsetting.yaml')
}

const editor = (page: Page) => page.getByRole('textbox', { name: 'appsetting.yaml 的內容' })

/**
 * Replaces the first `find` through the editor's own search, the way an administrator would. The search field keeps
 * the last query, so it is emptied first, and the replacement is typed only once the match is selected: typed
 * anywhere else, it would edit a comment.
 */
async function replaceInEditor(page: Page, find: string, put: string) {
  await editor(page).click()
  await page.keyboard.press('ControlOrMeta+f')
  const query = page.locator('.cm-search input[name=search]')
  await query.fill('')
  await query.pressSequentially(find)
  await expect(query).toHaveValue(find)
  await query.press('Enter')
  // The caret's line, not the search's own highlight, which can lag behind on a busy machine.
  await expect(page.locator('.cm-activeLine').first(), `the editor selects "${find}"`).toContainText(find, { timeout: 60_000 })
  await page.keyboard.press('Escape')
  await page.keyboard.type(put)
}

async function saveWithPassword(page: Page, password = ADMIN.password) {
  await expect(page.getByText('可以儲存')).toBeVisible({ timeout: 60_000 })
  await page.getByRole('button', { name: '儲存…' }).click()
  const dialog = page.getByRole('dialog', { name: '儲存 appsetting.yaml？' })
  await expect(dialog.getByLabel('你的密碼')).toBeFocused()
  await dialog.getByLabel('你的密碼').fill(password)
  await dialog.getByRole('button', { name: '儲存並套用' }).click()
  return dialog
}

async function discardChanges(page: Page) {
  await page.getByRole('button', { name: '放棄修改' }).first().click()
  await page.getByRole('alertdialog').getByRole('button', { name: '放棄修改' }).click()
}

test('an administrator changes the AI temperature, saves it with the password, and the server runs on it at once', async ({ page, consoleErrors }) => {
  void consoleErrors
  await signIn(page)
  await page.goto('/admin/settings')
  const before = (await apiGet(page, '/v1/admin/settings/appsetting')) as Document
  const current = /temperature: ([\d.]+)/.exec(before.text)![1]!
  const next = current === '0.4' ? '0.5' : '0.4'

  await expect(editor(page)).toContainText('environment: dev')
  await replaceInEditor(page, `temperature: ${current}`, `temperature: ${next}`)
  await expect(page.getByRole('region', { name: '檢查結果' })).toContainText('ai.temperature', { timeout: 60_000 })
  await saveWithPassword(page)

  await expect(page.getByText(/^已於 .* 儲存，伺服器現在以它運作。$/)).toBeVisible({ timeout: 60_000 })
  const after = (await apiGet(page, '/v1/admin/settings/appsetting')) as Document
  expect(after.text).toBe(before.text.replace(`temperature: ${current}`, `temperature: ${next}`))
  expect(after.status.running_revision, 'the server runs on the saved file').toBe(after.status.revision)
  const [entry] = (await apiGet(page, '/v1/admin/audit?limit=1')) as { action: string; settings: string[]; actor_name: string }[]
  expect(entry).toMatchObject({ action: 'save', settings: ['ai.temperature'], actor_name: ADMIN.username })
  await expect(page.getByRole('region', { name: '歷史紀錄' })).toContainText('你儲存了修改')
})

test('a save asks for the password: a wrong one saves nothing and keeps the session, the right one saves, and the version before can be restored', async ({ page, consoleErrors }) => {
  void consoleErrors
  await signIn(page)
  await page.goto('/admin/settings')
  const before = (await apiGet(page, '/v1/admin/settings/appsetting')) as Document

  await replaceInEditor(page, 'order_mode: mock_only', 'order_mode: disabled')
  const dialog = await saveWithPassword(page, 'not the administrator password')
  await expect(dialog.getByText('密碼不正確，沒有儲存任何內容。')).toBeVisible({ timeout: 60_000 })
  expect(((await apiGet(page, '/v1/admin/settings/appsetting')) as Document).text, 'nothing was saved').toBe(before.text)
  expect((await page.request.get('/v1/auth/me')).status(), 'a wrong password keeps the session').toBe(200)

  await dialog.getByLabel('你的密碼').fill(ADMIN.password)
  await dialog.getByRole('button', { name: '儲存並套用' }).click()
  await expect(page.getByText(/^已於 .* 儲存，伺服器現在以它運作。$/)).toBeVisible({ timeout: 60_000 })
  expect(((await apiGet(page, '/v1/admin/settings/appsetting')) as Document).text).toContain('order_mode: disabled')

  const history = page.getByRole('region', { name: '歷史紀錄' })
  await expect(history.getByRole('listitem').first(), 'the history has read this save').toContainText('trading.order_mode', { timeout: 60_000 })
  await history.getByRole('button', { name: '查看修改前的版本' }).first().click()
  const restore = page.getByRole('dialog', { name: /^還原 .* 之前的版本？$/ })
  await expect(restore).toContainText('trading.order_mode', { timeout: 60_000 })
  await restore.getByLabel('你的密碼').fill(ADMIN.password)
  await restore.getByRole('button', { name: '還原並套用' }).click()
  await expect(page.getByText(/^已於 .* 還原 .* 之前的版本，伺服器現在以它運作。$/)).toBeVisible({ timeout: 60_000 })
  expect(((await apiGet(page, '/v1/admin/settings/appsetting')) as Document).text).toBe(before.text)
  const [entry] = (await apiGet(page, '/v1/admin/audit?limit=1')) as { action: string }[]
  expect(entry!.action).toBe('restore')
})

test('invalid YAML is shown at the line and column the server gives, and the text survives a reload and a visit elsewhere', async ({ page, consoleErrors }) => {
  void consoleErrors
  await signIn(page)
  await page.goto('/admin/settings')
  const document = (await apiGet(page, '/v1/admin/settings/appsetting')) as Document
  const broken = document.text.replace('order_mode: mock_only', 'order_mode: [mock_only')
  const check = await page.request.post('/v1/admin/settings/appsetting/preview', { headers: APP_HEADER, data: { revision: document.status.revision, text: broken } })
  const [problem] = ((await check.json()) as { problems: { line: number; column: number }[] }).problems
  expect(problem, 'the server finds the unclosed list').toBeDefined()

  await replaceInEditor(page, 'order_mode: mock_only', 'order_mode: [mock_only')
  const located = page.getByRole('button', { name: new RegExp(`^第 ${problem!.line} 行，第 ${problem!.column} 欄`) })
  await expect(located).toBeVisible({ timeout: 60_000 })
  await expect(page.getByRole('button', { name: '儲存…' })).toBeDisabled()
  await located.click()
  await expect(page.locator('.cm-lineNumbers .cm-activeLineGutter')).toHaveText(String(problem!.line))
  await expect(page.locator('.cm-lintRange-error')).toBeVisible()

  let warned = false
  page.once('dialog', (dialog) => {
    warned = dialog.type() === 'beforeunload'
    void dialog.accept()
  })
  await page.reload()
  expect(warned, 'the browser asks before the reload').toBe(true)
  // The editor draws only the lines in view: the broken text shows through its notice and the problem it still has.
  await expect(page.getByText(/^你在 .* 未儲存的修改還在。$/)).toBeVisible({ timeout: 60_000 })
  await expect(located).toBeVisible({ timeout: 60_000 })

  await page.getByRole('navigation', { name: '主要導覽' }).getByRole('link', { name: '市場總覽' }).click()
  const ask = page.getByRole('alertdialog', { name: '離開這個頁面？' })
  await expect(ask).toContainText('appsetting.yaml 未儲存的修改會保留在這個分頁')
  await ask.getByRole('button', { name: '離開' }).click()
  await page.waitForURL((url) => url.pathname === '/')
  await page.getByRole('navigation', { name: '主要導覽' }).getByRole('link', { name: '系統設定' }).click()
  await expect(page.getByRole('tab', { name: /appsetting\.yaml.*有未儲存的修改/ })).toBeVisible({ timeout: 60_000 })
  await expect(located).toBeVisible({ timeout: 60_000 })

  await discardChanges(page)
  await expect(page.getByText('伺服器正以此檔運作')).toBeVisible()
  await expect(located).toBeHidden()
  expect(((await apiGet(page, '/v1/admin/settings/appsetting')) as Document).text).toBe(document.text)
})

test('a member is told the page is for administrators, and the server refuses them the files while they stay signed in', async ({ browser }) => {
  const member = await memberPage(browser)
  await member.goto('/admin/settings')

  await expect(member.getByText('這個頁面只開放管理員')).toBeVisible()
  await expect(member.getByRole('textbox')).toHaveCount(0)
  await expect(member.getByRole('navigation', { name: '主要導覽' }).getByRole('link', { name: '系統設定' })).toHaveCount(0)
  expect((await member.request.get('/v1/admin/settings')).status(), 'the server refuses the overview').toBe(403)
  expect((await member.request.get('/v1/admin/settings/appsetting')).status(), 'and the file').toBe(403)
  expect((await member.request.get('/v1/auth/me')).status(), 'and keeps the session').toBe(200)
  await member.context().close()
})

test('an edit made on disk is loaded by the running server, and one it would not start with is shown at its line until fixed', async ({ page, consoleErrors }) => {
  void consoleErrors
  test.skip(SETTINGS_DIR === null, 'E2E_SETTINGS_DIR is not set')
  const file = onDisk()
  const original = readFileSync(file, 'utf8')
  await signIn(page)
  await page.goto('/admin/settings')
  await expect(page.getByText('伺服器正以此檔運作')).toBeVisible({ timeout: 60_000 })

  try {
    writeFileSync(file, original.replace('# config/appsetting.yaml', '# config/appsetting.yaml, edited on the server'))
    await expect
      .poll(
        async () => {
          const loaded = (await apiGet(page, '/v1/admin/settings/appsetting')) as Document
          return loaded.text.includes('edited on the server') && loaded.status.running_revision === loaded.status.revision
        },
        { message: 'the running server loads the file it found', timeout: 60_000 },
      )
      .toBe(true)
    await expect(editor(page)).toContainText('edited on the server', { timeout: 60_000 })
    await expect(page.getByText('伺服器正以此檔運作')).toBeVisible({ timeout: 60_000 })

    writeFileSync(file, original.replace('  order_mode: mock_only', '  order_mode: sometimes'))
    const banner = page.getByRole('alert', { name: '磁碟上的修改沒有載入' })
    await expect(banner).toBeVisible({ timeout: 60_000 })
    await expect(banner.getByRole('button', { name: /^第 \d+ 行，第 3 欄.*trading\.order_mode/ })).toBeVisible()
    await expect(page.getByRole('tab', { name: /appsetting\.yaml.*磁碟上的修改未載入/ })).toBeVisible()
    expect((await page.request.get('/v1/watchlist')).status(), 'the server keeps serving on the previous settings').toBe(200)

    await banner.getByRole('button', { name: '再試一次' }).click()
    await expect(banner.getByText(/^已再試一次（.*），仍無法載入。$/)).toBeVisible({ timeout: 60_000 })

    writeFileSync(file, original)
    await expect(banner).toBeHidden({ timeout: 60_000 })
    await expect(page.getByText('伺服器正以此檔運作')).toBeVisible({ timeout: 60_000 })
  } finally {
    writeFileSync(file, original)
  }
})

test('the open text is kept when the file changes on disk, and saving it after keeping it replaces the newer file', async ({ page, consoleErrors }) => {
  void consoleErrors
  test.skip(SETTINGS_DIR === null, 'E2E_SETTINGS_DIR is not set')
  const file = onDisk()
  const original = readFileSync(file, 'utf8')
  await signIn(page)
  await page.goto('/admin/settings')
  await expect(page.getByText('伺服器正以此檔運作')).toBeVisible({ timeout: 60_000 })

  const current = /temperature: ([\d.]+)/.exec(original)![1]!
  const mine = current === '0.6' ? '0.5' : '0.6'

  try {
    await replaceInEditor(page, `temperature: ${current}`, `temperature: ${mine}`)
    await expect(page.getByText('可以儲存')).toBeVisible({ timeout: 60_000 })
    writeFileSync(file, original.replace('# config/appsetting.yaml', '# config/appsetting.yaml, edited on the server'))

    await expect(page.getByText('你開始編輯後，磁碟上的 appsetting.yaml 被修改了')).toBeVisible({ timeout: 60_000 })
    await expect(editor(page)).toContainText(`temperature: ${mine}`)
    await expect(page.getByRole('button', { name: '儲存…' })).toBeDisabled()
    await page.getByRole('button', { name: '保留我的內容' }).click()
    await expect(page.getByText('你的內容來自較舊的檔案')).toBeVisible({ timeout: 60_000 })
    await saveWithPassword(page)

    await expect(page.getByText(/^已於 .* 儲存，伺服器現在以它運作。$/)).toBeVisible({ timeout: 60_000 })
    const saved = (await apiGet(page, '/v1/admin/settings/appsetting')) as Document
    expect(saved.text).toBe(original.replace(`temperature: ${current}`, `temperature: ${mine}`))
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
