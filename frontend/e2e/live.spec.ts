import type { Page } from '@playwright/test'
import { ADMIN_TOKEN, API_URL, apiGet, expect, horizontalOverflow, OWNER_TOKEN, test, unlockOwner } from './fixtures'

/**
 * The live app against a real backend and a disposable database: every assertion about saved data reads the
 * server's own answer. The backend runs with a placeholder AI key, so no paid AI call succeeds.
 */

const SHOTS = process.env.E2E_SHOTS ?? 'docs/screenshots'

type Strategy = { strategy_id: string; name: string; rules: unknown[]; indicators: unknown; scoring: unknown }
type Settings = { revision: number; strategies: Strategy[] }

async function copyBalanced(page: Page, name: string): Promise<string> {
  await page.getByRole('link', { name: '策略庫' }).first().click()
  await page.getByRole('article', { name: '平衡型' }).first().getByRole('link', { name: '複製 平衡型' }).click()
  await expect(page.getByLabel('策略名稱')).toHaveValue('平衡型 副本')
  await page.getByLabel('策略名稱').fill(name)
  await page.getByRole('button', { name: '儲存', exact: true }).first().click()
  await page.waitForURL(/\/strategies\/stg_[a-z0-9]+\/edit$/)
  return page.url().split('/').at(-2)!
}

test('a built-in strategy copied in the designer saves on the server with all of its rules and reloads', async ({ page, consoleErrors }) => {
  void consoleErrors
  await page.goto('/strategies')
  await expect(page.getByRole('article', { name: '保守型' })).toBeVisible()
  await expect(page.getByText('私人資料已上鎖')).toBeVisible()
  await unlockOwner(page)
  await expect(page.getByRole('main').getByRole('article', { name: '平衡型' }), 'the built-in and the owner copy').toHaveCount(2)

  const id = await copyBalanced(page, 'E2E 平衡副本')
  const saved = (await apiGet(page, '/v1/technical-settings')) as Settings
  const official = ((await apiGet(page, '/v1/technical-settings/built-in-strategies')) as Strategy[]).find((item) => item.strategy_id === 'balanced')!
  const copy = saved.strategies.find((item) => item.strategy_id === id)!
  expect(copy.name).toBe('E2E 平衡副本')
  expect(copy.rules).toEqual(official.rules)
  expect(copy.indicators).toEqual(official.indicators)
  await page.screenshot({ path: `${SHOTS}/live-builder-saved.png`, fullPage: true })

  await page.reload()
  await expect(page.getByText('私人資料已上鎖')).toBeVisible()
  await unlockOwner(page)
  await expect(page.getByLabel('策略名稱')).toHaveValue('E2E 平衡副本')
})

test('a save from an older revision keeps the draft and saves it into the newer settings', async ({ browser }) => {
  const contexts = await Promise.all([browser.newContext(), browser.newContext()])
  const [first, second] = await Promise.all(contexts.map((context) => context.newPage()))
  for (const page of [first!, second!]) {
    await page.goto('/strategies/new?builtin=balanced')
    await unlockOwner(page)
    await expect(page.getByLabel('策略名稱')).toHaveValue('平衡型 副本')
  }
  await first!.getByLabel('策略名稱').fill('E2E 先存')
  await first!.getByRole('button', { name: '儲存', exact: true }).first().click()
  await first!.waitForURL(/\/edit$/, { timeout: 30_000 })

  await second!.route('**/v1/technical-settings', async (route) => {
    if (route.request().method() === 'GET') await new Promise((resolve) => setTimeout(resolve, 2_000))
    await route.continue()
  })
  await second!.getByLabel('策略名稱').fill('E2E 後存')
  await second!.getByRole('button', { name: '儲存', exact: true }).first().click()
  await expect(second!.getByText('你開啟這個策略後，設定已被變更')).toBeVisible({ timeout: 15_000 })
  await second!.getByRole('button', { name: '再次儲存我的草稿' }).click()
  await second!.waitForURL(/\/edit$/, { timeout: 30_000 })

  const names = ((await apiGet(second!, '/v1/technical-settings')) as Settings).strategies.map((item) => item.name)
  expect(names).toEqual(expect.arrayContaining(['E2E 先存', 'E2E 後存']))
  await Promise.all(contexts.map((context) => context.close()))
})

test('the overview charts the TAIEX as the default index, lists the most traded stocks and shows the breadth as the server sends them', async ({ page, consoleErrors }) => {
  void consoleErrors
  const history = (await apiGet(page, '/v1/market/indexes/taiex?bars=260')) as { bars: { close: number }[] }
  const mostTraded = (await apiGet(page, '/v1/market/most-traded')) as { stock_id: string }[]
  const breadth = (await apiGet(page, '/v1/market/breadth')) as {
    market: { advancers: number; decliners: number; unchanged: number }
    industries: Record<string, unknown>
  }
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '市場總覽', level: 1 })).toBeVisible()

  const level = new Intl.NumberFormat('zh-TW', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(history.bars.at(-1)!.close)
  const trend = page.getByRole('region', { name: /加權指數/ })
  await expect(trend.getByRole('heading', { level: 2 })).toContainText('指數 · 預設')
  await expect(trend.getByText(level, { exact: true }).first()).toBeVisible({ timeout: 60_000 })
  await trend.getByRole('tab', { name: '1 年' }).click()
  await expect(trend.getByText('1 年漲跌', { exact: true })).toBeVisible()

  const most = page.getByRole('region', { name: '成交熱絡' })
  await expect(most.getByRole('link')).toHaveCount(Math.min(mostTraded.length, 10))
  await expect(most.getByRole('link').first()).toContainText(mostTraded[0]!.stock_id)
  if (mostTraded.length > 10) {
    await most.getByRole('button', { name: `顯示全部 ${mostTraded.length} 檔` }).click()
    await expect(most.getByRole('link')).toHaveCount(mostTraded.length)
  }

  const panel = page.getByRole('region', { name: '市場廣度' })
  const count = (value: number) => new Intl.NumberFormat('zh-TW').format(value)
  for (const [label, value] of [['上漲', breadth.market.advancers], ['下跌', breadth.market.decliners], ['平盤', breadth.market.unchanged]] as const) {
    await expect(panel.getByRole('term').filter({ hasText: label }).locator('xpath=following-sibling::dd[1]')).toHaveText(count(value))
  }
  await expect(panel.getByText('尚無資料來源')).toHaveCount(0)
  const industries = Object.keys(breadth.industries).length
  const rows = panel.getByRole('table', { name: '產業漲跌' }).getByRole('row')
  if (industries > 8) {
    await panel.getByRole('button', { name: `顯示全部 ${industries} 個產業` }).click()
  }
  await expect(rows.filter({ hasNotText: '⋯' })).toHaveCount(industries + 1)
  await page.screenshot({ path: `${SHOTS}/live-overview.png`, fullPage: true })

  await unlockOwner(page)
  await expect(page.getByText(/需要 \d+ 根/)).toBeVisible()
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: `${SHOTS}/live-overview-unlocked.png`, fullPage: true })
})

test('the research target can be changed through the listing search, kept in the address, and set back', async ({ page, consoleErrors }) => {
  void consoleErrors
  await page.goto('/')
  await page.getByRole('button', { name: '更換' }).click()
  await page.getByRole('combobox').fill('2330')
  await page.getByRole('option', { name: /2330/ }).first().click({ timeout: 120_000 })
  await expect(page).toHaveURL(/\?target=2330$/)
  const trend = page.getByRole('region', { name: /2330/ })
  await expect(trend.getByRole('heading', { level: 2 })).toContainText('台積電', { timeout: 60_000 })
  await expect(trend.getByRole('heading', { level: 2 })).not.toContainText('預設')
  await page.reload()
  await expect(page.getByRole('region', { name: /2330/ }).getByRole('heading', { level: 2 })).toContainText('台積電', { timeout: 60_000 })
  await page.getByRole('link', { name: '改回加權指數' }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole('region', { name: /加權指數/ }).getByRole('heading', { level: 2 })).toContainText('指數 · 預設')
})

test('after switching the strategy in use, the stock page evaluates with the new one', async ({ page, consoleErrors }) => {
  void consoleErrors
  await page.goto('/strategies')
  await unlockOwner(page)
  const activate = async (name: string) => {
    const card = page.getByRole('region', { name: '我的策略' }).getByRole('article', { name })
    await expect(card).toBeVisible()
    const use = card.getByRole('button', { name: '使用這套策略' })
    if (await use.count()) await use.click()
    await expect(card.getByText('使用中').first()).toBeVisible()
  }
  const evaluatedWith = async (name: string) => {
    await page.getByRole('button', { name: '搜尋股票' }).click()
    await page.getByRole('dialog').getByRole('combobox').fill('2330')
    await page.getByRole('option', { name: /2330/ }).first().click({ timeout: 120_000 })
    await expect(page.getByRole('region', { name: '技術評估' })).toContainText(name, { timeout: 120_000 })
    await page.getByRole('link', { name: '策略庫' }).first().click()
  }
  await activate('平衡型')
  await evaluatedWith('平衡型')
  await activate('積極型')
  await evaluatedWith('積極型')
  await activate('平衡型')
  await evaluatedWith('平衡型')
})

test('a card whose request fails says so and loads on retry, and going offline is announced', async ({ page }) => {
  let failing = true
  await page.route('**/v1/market/most-traded', (route) => (failing ? route.fulfill({ status: 503, json: { detail: 'The exchange listing is unavailable.' } }) : route.continue()))
  await page.goto('/')
  const most = page.getByRole('region', { name: '成交熱絡' })
  await expect(most.getByText('無法載入成交排行')).toBeVisible({ timeout: 30_000 })
  await expect(most.getByText('行情資料暫時無法取得，請稍後再試。')).toBeVisible()
  failing = false
  await most.getByRole('button', { name: '重試' }).click()
  await expect(most.getByRole('link').first()).toBeVisible({ timeout: 30_000 })

  await page.context().setOffline(true)
  await expect(page.getByText('目前離線。恢復連線後會自動重新載入資料。')).toBeVisible()
  await page.context().setOffline(false)
  await expect(page.getByText('目前離線。恢復連線後會自動重新載入資料。')).toBeHidden()
})

test('search finds a listed stock, its page shows real bars and the backend evaluation, and it can be watched', async ({ page, consoleErrors }) => {
  void consoleErrors
  const unwatch = await page.request.post(`${API_URL}/v1/watchlist/manual/remove`, {
    headers: { Authorization: `Bearer ${OWNER_TOKEN}` },
    data: { confirm: true, stock_ids: ['2330'] },
  })
  expect(unwatch.ok(), 'starts with 2330 off the manual watchlist').toBe(true)
  await page.goto('/')
  await unlockOwner(page)
  await page.getByRole('button', { name: '搜尋股票' }).click()
  await page.getByRole('dialog').getByRole('combobox').fill('2330')
  await page.getByRole('option', { name: /2330/ }).first().click({ timeout: 120_000 })
  await expect(page.getByRole('heading', { level: 1 })).toContainText('台積電', { timeout: 120_000 })
  await expect(page.getByRole('heading', { name: '技術評估' })).toBeVisible({ timeout: 120_000 })
  await expect(page.getByText(/^\d{4}\/\d{2}\/\d{2} 收盤$/).first()).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/live-stock-2330.png`, fullPage: true })

  const manual = async () =>
    ((await apiGet(page, '/v1/watchlist')) as { stock_id: string; watchlist_type: string }[]).filter((entry) => entry.watchlist_type === 'manual').map((entry) => entry.stock_id)
  await page.getByRole('button', { name: '加入觀察清單' }).click()
  await expect(page.getByRole('button', { name: '移除' })).toBeVisible()
  await expect.poll(manual).toContain('2330')

  await page.getByRole('link', { name: '觀察清單' }).first().click()
  await page.getByRole('button', { name: /把 .* 從手動觀察清單移除/ }).first().click()
  await expect(page.getByText('觀察清單是空的')).toBeVisible()
  await expect.poll(manual).toEqual([])
})

test('a specific-stock run starts after confirming its AI cost, ends, and keeps its report', async ({ page, consoleErrors }) => {
  void consoleErrors
  await page.goto('/runs')
  await unlockOwner(page)
  await page.getByLabel('要分析的股票代號').fill('2330')
  await page.getByLabel('要分析的股票代號').press('Enter')
  await expect(page.getByRole('alertdialog')).toContainText('每檔一次付費 AI 呼叫')
  await page.getByRole('button', { name: '啟動任務' }).click()
  await page.waitForURL(/\/runs\/[0-9a-f-]{36}$/)
  const runId = page.url().split('/').at(-1)!
  await expect.poll(async () => ((await apiGet(page, `/v1/runs/${runId}`)) as { state: string }).state, { timeout: 170_000 }).toBe('finished')
  await expect(page.getByRole('heading', { name: '股票報告' })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole('main').getByText('已完成', { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: /2330/ }).first()).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/live-run-detail.png`, fullPage: true })

  const run = (await apiGet(page, `/v1/runs/${runId}`)) as { state: string; reports: { stock_id: string }[] }
  expect(run.state).toBe('finished')
  expect(run.reports.map((report) => report.stock_id)).toEqual(['2330'])
})

test('the account page says it is the mock broker’s paper account', async ({ page, consoleErrors }) => {
  void consoleErrors
  await page.goto('/account')
  await unlockOwner(page)
  await expect(page.getByText('模擬券商').first()).toBeVisible()
  await expect(page.getByText('不是真實資產')).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/live-account.png`, fullPage: true })
})

test('administration needs its own token, previews a change, saves it with a backup, refuses a stale restore and restores it', async ({ page, consoleErrors }) => {
  void consoleErrors
  await page.goto('/admin/settings')
  await unlockOwner(page)
  await expect(page.getByText('系統管理已上鎖')).toBeVisible()
  await page.getByRole('main').getByRole('button', { name: '解鎖' }).click()
  await page.getByLabel('管理員 token').fill(ADMIN_TOKEN)
  await page.getByRole('dialog').getByRole('button', { name: '解鎖' }).click()
  const field = page.getByLabel('溫度（隨機程度）')
  await expect(field).not.toHaveValue('')
  const before = await field.inputValue()
  const next = before === '0.5' ? '0.6' : '0.5'

  const restoreButtons = page.getByRole('button', { name: '預覽還原' })
  const backupsBefore = await restoreButtons.count()
  await field.fill(next)
  await page.getByRole('button', { name: '驗證並預覽' }).click()
  await expect(page.getByText('設定驗證通過。')).toBeVisible()
  await expect(page.getByText(`+  temperature: ${next}`)).toBeVisible()
  await page.getByRole('button', { name: '儲存檔案' }).click()
  await expect(page.getByText('重新啟動伺服器後套用')).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/live-admin-saved.png`, fullPage: true })

  await expect(restoreButtons).toHaveCount(Math.min(backupsBefore + 1, 20))
  await restoreButtons.first().click()
  const restore = page.getByRole('button', { name: '還原', exact: true })
  await expect(restore).toBeVisible()
  const other = ['0.3', '0.4'].find((value) => value !== before)!
  const file = (await apiGet(page, '/v1/admin/settings/appsetting', ADMIN_TOKEN)) as { status: { revision: string } }
  const elsewhere = await page.request.put(`${API_URL}/v1/admin/settings/appsetting`, {
    headers: { Authorization: `Bearer ${ADMIN_TOKEN}` },
    data: { confirm: true, revision: file.status.revision, changes: { 'ai.temperature': Number(other) } },
  })
  expect(elsewhere.ok(), 'a save made after the restore preview').toBe(true)
  await restore.click()
  await expect(page.getByText('此頁讀取後檔案已被變更。請重新載入後再修改一次。')).toBeVisible()
  await expect(page.getByLabel('溫度（隨機程度）')).toHaveValue(other)
  await expect(restore).toBeHidden()
  await expect(page.getByText('此頁讀取後檔案已被變更，儲存將被拒絕。')).toBeVisible()

  const rows = page.getByRole('listitem').filter({ has: restoreButtons })
  await expect(rows.first()).toContainText(file.status.revision.slice(0, 12))
  await rows.nth(1).getByRole('button', { name: '預覽還原' }).click()
  await restore.click()
  await expect(page.getByText('已還原備份')).toBeVisible()
  await expect(page.getByLabel('溫度（隨機程度）')).toHaveValue(before)
  const audit = (await apiGet(page, '/v1/admin/audit', ADMIN_TOKEN)) as { action: string; settings: string[] }[]
  expect(audit.slice(0, 2).map((entry) => entry.action)).toEqual(['restore', 'save'])
  expect(Object.keys(audit[0]!).sort()).toEqual(['action', 'actor', 'file', 'from_revision', 'recorded_at', 'settings', 'to_revision'])
})

const VIEWPORTS = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'mobile', width: 390, height: 844 },
]
const PAGES = ['/', '/strategies', '/runs', '/valuation', '/watchlist', '/account', '/admin/settings', '/stocks/2330']

for (const viewport of VIEWPORTS) {
  test(`${viewport.name}: every page fits without horizontal overflow, in both themes`, async ({ page, consoleErrors }) => {
    void consoleErrors
    await page.setViewportSize(viewport)
    for (const path of PAGES) {
      await page.goto(path)
      await page.waitForLoadState('networkidle')
      expect(await horizontalOverflow(page), path).toBeLessThanOrEqual(0)
    }
    await expect(page.getByRole('banner').getByRole('button', { name: '解鎖' }), 'the header unlock button has a name at this width').toBeVisible()
    await page.screenshot({ path: `${SHOTS}/${viewport.name}-stock-dark.png`, fullPage: true })
    await page.emulateMedia({ colorScheme: 'light' })
  })
}

test('English, light theme, keyboard skip link and focus', async ({ page, consoleErrors }) => {
  void consoleErrors
  await page.goto('/')
  await page.getByRole('button', { name: '語言' }).click()
  await page.getByRole('menuitem', { name: 'English' }).click()
  await expect(page.getByRole('heading', { name: 'Market overview', level: 1 })).toBeVisible()
  await page.getByRole('button', { name: 'Theme' }).click()
  await page.getByRole('menuitem', { name: 'Light' }).click()
  await expect(page.locator('html')).not.toHaveClass(/dark/)
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(1000)
  await page.screenshot({ path: `${SHOTS}/light-en-overview.png`, fullPage: true })

  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.locator('#main')).toBeFocused()
  const unlock = page.getByRole('banner').getByRole('button', { name: 'Unlock' })
  await unlock.focus()
  const ring = await unlock.evaluate((element) => getComputedStyle(element).outlineStyle + getComputedStyle(element).boxShadow)
  expect(ring).not.toBe('nonenone')
})

/** A run in progress, served to the page itself: the badge's motion is the subject, and no run has to be started. */
const RUNNING = { run_id: '00000000-0000-4000-8000-000000000001', state: 'running', summary: null, error: null, reports: [] }

test('reduced motion stops the running state badge from spinning', async ({ browser }) => {
  const spinning: Record<string, boolean> = {}
  for (const reducedMotion of ['reduce', 'no-preference'] as const) {
    const context = await browser.newContext({ reducedMotion, locale: 'zh-TW', timezoneId: 'Asia/Taipei' })
    const page = await context.newPage()
    await page.route(`**/v1/runs/${RUNNING.run_id}`, (route) => route.fulfill({ json: RUNNING }))
    await page.goto(`/runs/${RUNNING.run_id}`)
    await unlockOwner(page)
    const icon = page.getByRole('main').getByText('執行中', { exact: true }).first().locator('svg')
    await expect(icon).toBeVisible()
    spinning[reducedMotion] = await icon.evaluate((element) => element.getAnimations().some((animation) => animation.playState === 'running'))
    await context.close()
  }
  expect(spinning).toEqual({ reduce: false, 'no-preference': true })
})
