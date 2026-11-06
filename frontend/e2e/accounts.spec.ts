import type { Browser, BrowserContext, Page, Request } from '@playwright/test'
import { ADMIN, apiGet, expect, MEMBER, SETUP_CODE, test } from './fixtures'

/**
 * Accounts on a fresh backend, in order: the first-time setup with the code the server printed, sign-out and
 * sign-in, a registered user who sees no administration, the administrator changing that user's role and
 * deactivating them, each user's own watchlist, and the 401 that sends a deactivated user back to sign-in.
 * Run it on a backend with no user yet: E2E_SETUP_CODE is the code from its console.
 */
test.describe.configure({ mode: 'serial' })

const contexts: BrowserContext[] = []
const pageErrors: string[] = []
async function newPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext({ locale: 'zh-TW', timezoneId: 'Asia/Taipei' })
  contexts.push(context)
  const page = await context.newPage()
  page.on('pageerror', (error) => pageErrors.push(error.message))
  return page
}

test.afterAll(async () => {
  await Promise.all(contexts.map((context) => context.close()))
  expect(pageErrors, 'no uncaught page errors in any session').toEqual([])
})

async function fillAccount(page: Page, account: { username: string; email: string; password: string }) {
  await page.getByLabel('使用者名稱', { exact: true }).fill(account.username)
  await page.getByLabel('電子郵件').fill(account.email)
  await page.getByLabel('密碼', { exact: true }).fill(account.password)
  await page.getByLabel('再次輸入密碼').fill(account.password)
}

async function openAccountMenu(page: Page, name: string) {
  await page.getByRole('button', { name: `${name} 的帳號選單` }).click()
}

async function manualWatchlist(page: Page): Promise<string[]> {
  const entries = (await apiGet(page, '/v1/watchlist')) as { stock_id: string; watchlist_type: string }[]
  return entries.filter((entry) => entry.watchlist_type === 'manual').map((entry) => entry.stock_id)
}

let admin: Page
let member: Page

test('a fresh site opens on the first-time setup, refuses a wrong code and signs the administrator in with the printed one', async ({ browser }) => {
  expect(SETUP_CODE, 'E2E_SETUP_CODE: the code the server printed at start').not.toBe('')
  admin = await newPage(browser)
  await admin.goto('/watchlist')
  await admin.waitForURL('**/setup')
  await expect(admin.getByRole('heading', { name: '建立管理員帳號', level: 1 })).toBeVisible()
  await expect(admin.getByText('伺服器啟動時會在主控台印出這組一次性的設定碼')).toBeVisible()
  await expect(admin.getByText(/token|解鎖/)).toHaveCount(0)

  await admin.getByLabel('設定碼').fill('not-the-code')
  await fillAccount(admin, ADMIN)
  const sent: Request[] = []
  admin.on('request', (request) => request.method() !== 'GET' && request.url().includes('/v1/') && sent.push(request))
  await admin.getByRole('button', { name: '建立帳號並登入' }).click()
  await expect(admin.getByText('設定碼不正確，請對照伺服器主控台印出的那一組。')).toBeVisible()

  await admin.getByLabel('設定碼').fill(SETUP_CODE)
  await admin.getByRole('button', { name: '建立帳號並登入' }).click()
  await admin.waitForURL((url) => url.pathname === '/')
  await expect(admin.getByRole('heading', { name: '分析任務', level: 1 })).toBeVisible()
  expect(sent.length, 'setup, setup again, sign-in').toBe(3)
  for (const request of sent) expect(request.headers()['x-requested-with'], `${request.method()} ${request.url()}`).toBe('stock-agent')

  await openAccountMenu(admin, ADMIN.username)
  const menu = admin.getByRole('menu')
  await expect(menu).toContainText(ADMIN.email)
  await expect(menu).toContainText('管理員')
  await expect(menu.getByRole('menuitem', { name: '使用者管理' })).toBeVisible()
  await admin.keyboard.press('Escape')
  const me = (await apiGet(admin, '/v1/auth/me')) as { role: string; permissions: string[] }
  expect(me.role).toBe('administrator')
  expect(me.permissions).toContain('manage_users')
})

test('signing out asks a private page to sign in, a wrong password says so, and signing in returns to that page', async () => {
  await openAccountMenu(admin, ADMIN.username)
  await admin.getByRole('menuitem', { name: '登出' }).click()
  await expect(admin.getByRole('banner').getByRole('link', { name: '登入' })).toBeVisible()
  expect((await admin.request.get('/v1/auth/me')).status(), 'the server ended the session').toBe(401)

  await admin.goto('/watchlist')
  await expect(admin.getByText('登入後查看你的觀察清單')).toBeVisible()
  await admin.getByRole('main').getByRole('link', { name: '登入' }).first().click()
  await admin.waitForURL('**/sign-in?next=%2Fwatchlist')

  await admin.getByLabel('使用者名稱或電子郵件').fill(ADMIN.email.toUpperCase())
  await admin.getByLabel('密碼', { exact: true }).fill('not the password at all')
  await admin.getByRole('main').getByRole('button', { name: '登入' }).click()
  await expect(admin.getByRole('alert')).toContainText('帳號或密碼不正確')

  await admin.getByLabel('密碼', { exact: true }).fill(ADMIN.password)
  await admin.getByRole('main').getByRole('button', { name: '登入' }).click()
  await admin.waitForURL('**/watchlist')
  await expect(admin.getByRole('heading', { name: '觀察清單', level: 1 })).toBeVisible()
})

test('a registered user is signed in at once, sees no administration, and a refused administrator request keeps them signed in', async ({ browser }) => {
  member = await newPage(browser)
  await member.goto('/register')
  await expect(member.getByRole('heading', { name: '建立帳號', level: 1 })).toBeVisible()
  await fillAccount(member, MEMBER)
  await member.getByRole('main').getByRole('button', { name: '建立帳號' }).click()
  await member.waitForURL((url) => url.pathname === '/')

  await expect(member.getByRole('navigation', { name: '主要導覽' }).getByRole('link', { name: '使用者' })).toHaveCount(0)
  await expect(member.getByRole('navigation', { name: '主要導覽' }).getByRole('link', { name: '系統設定' })).toHaveCount(0)
  await openAccountMenu(member, MEMBER.username)
  await expect(member.getByRole('menu')).toContainText('一般使用者')
  await expect(member.getByRole('menuitem', { name: '使用者管理' })).toHaveCount(0)
  await member.keyboard.press('Escape')

  await member.goto('/admin/users')
  await expect(member.getByText('這個頁面只開放管理員')).toBeVisible()
  const refused = await member.request.get('/v1/admin/users')
  expect(refused.status(), 'the server refuses the directory').toBe(403)
  expect((await member.request.get('/v1/auth/me')).status(), 'and keeps the session').toBe(200)
  await member.reload()
  await expect(member.getByText('這個頁面只開放管理員')).toBeVisible()
  await expect(member.getByRole('button', { name: `${MEMBER.username} 的帳號選單` })).toBeVisible()
})

test('each user’s watchlist is their own, and every write carries the app header', async () => {
  const writes: Request[] = []
  for (const page of [admin, member]) page.on('request', (request) => request.method() !== 'GET' && request.url().includes('/v1/') && writes.push(request))

  for (const [page, stock] of [
    [admin, '2330'],
    [member, '2317'],
  ] as const) {
    await page.goto(`/stocks/${stock}`)
    await page.getByRole('main').getByRole('button', { name: '加入觀察清單' }).click({ timeout: 120_000 })
    // The first add after a start waits for the backend to load the exchange listing, 15 to 80 s.
    await expect.poll(() => manualWatchlist(page), { timeout: 120_000 }).toContain(stock)
  }
  expect(await manualWatchlist(admin)).toEqual(['2330'])
  expect(await manualWatchlist(member)).toEqual(['2317'])
  expect(writes.length).toBeGreaterThanOrEqual(2)
  for (const request of writes) expect(request.headers()['x-requested-with'], `${request.method()} ${request.url()}`).toBe('stock-agent')

  await member.goto('/watchlist')
  await expect(member.getByRole('main')).toContainText('2317', { timeout: 60_000 })
  await expect(member.getByRole('main')).not.toContainText('2330')
})

test('the administrator changes the user’s role and back; a demoted page refuses the next change and stays signed in', async () => {
  await admin.goto('/admin/users')
  const row = admin.getByRole('row', { name: new RegExp(MEMBER.username) })
  await expect(row).toBeVisible()
  await row.getByRole('button', { name: `${MEMBER.username} 的操作` }).click()
  await admin.getByRole('menuitem', { name: '設為管理員' }).click()
  await admin.getByRole('alertdialog').getByRole('button', { name: '設為管理員' }).click()
  await expect(row.getByText('管理員', { exact: true }).filter({ visible: true })).toBeVisible()

  await member.goto('/admin/users')
  await expect(member.getByRole('row', { name: new RegExp(ADMIN.username) })).toBeVisible()

  await row.getByRole('button', { name: `${MEMBER.username} 的操作` }).click()
  await admin.getByRole('menuitem', { name: '改為一般使用者' }).click()
  await admin.getByRole('alertdialog').getByRole('button', { name: '改為一般使用者' }).click()
  await expect(row.getByText('一般使用者', { exact: true }).filter({ visible: true })).toBeVisible()

  const theirAdminRow = member.getByRole('row', { name: new RegExp(ADMIN.username) })
  await theirAdminRow.getByRole('button', { name: `${ADMIN.username} 的操作` }).click()
  const deactivate = member.getByRole('menuitem', { name: '停用帳號' })
  await deactivate.click()
  await member.getByRole('alertdialog').getByRole('button', { name: '停用帳號' }).click()
  await expect(member.getByText('伺服器拒絕這個操作。').or(member.getByText(/帳號沒有變更/)).first()).toBeVisible()
  expect((await member.request.get('/v1/auth/me')).status(), 'a 403 keeps the session').toBe(200)
  await member.reload()
  await expect(member.getByText('這個頁面只開放管理員')).toBeVisible()
})

test('a deactivated user is signed out at their next request and returns to sign-in, where the old password no longer works', async () => {
  const row = admin.getByRole('row', { name: new RegExp(MEMBER.username) })
  await row.getByRole('button', { name: `${MEMBER.username} 的操作` }).click()
  await admin.getByRole('menuitem', { name: '停用帳號' }).click()
  await admin.getByRole('alertdialog').getByRole('button', { name: '停用帳號' }).click()
  await expect(row.getByText('已停用').filter({ visible: true }).first()).toBeVisible()

  await member.getByRole('navigation', { name: '主要導覽' }).getByRole('link', { name: '觀察清單' }).click()
  await expect(member.getByText('你已經登出了')).toBeVisible({ timeout: 30_000 })
  await expect(member.getByRole('banner').getByRole('link', { name: '登入' })).toBeVisible()
  await member.getByRole('banner').getByRole('link', { name: '登入' }).click()
  await member.waitForURL('**/sign-in**')
  await member.getByLabel('使用者名稱或電子郵件').fill(MEMBER.username)
  await member.getByLabel('密碼', { exact: true }).fill(MEMBER.password)
  await member.getByRole('main').getByRole('button', { name: '登入' }).click()
  await expect(member.getByRole('alert')).toContainText('帳號或密碼不正確')

  await row.getByRole('button', { name: `${MEMBER.username} 的操作` }).click()
  await admin.getByRole('menuitem', { name: '重新啟用' }).click()
  await expect(row.getByText('啟用中').filter({ visible: true }).first()).toBeVisible()
})
