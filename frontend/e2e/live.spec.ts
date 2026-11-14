import type { Page } from '@playwright/test'
import { apiGet, apiWrite, expect, horizontalOverflow, signIn, test } from './fixtures'

/**
 * The live app against a real backend and a disposable database: every assertion about saved data reads the
 * server's own answer. Each test signs in as the administrator through the API, so the browser holds the session
 * cookie the way it does after the sign-in page. The backend runs with a placeholder AI key, so no paid AI call
 * succeeds.
 */

const SHOTS = process.env.E2E_SHOTS ?? 'docs/screenshots'

type Strategy = { strategy_id: string; name: string; rules: { name: string }[]; indicators: unknown; scoring: unknown }
type Settings = { revision: number; strategies: Strategy[] }

async function copyBalanced(page: Page, name: string): Promise<string> {
  await page.goto('/strategies')
  await page.getByRole('button', { name: '新增策略' }).click()
  await page.getByRole('menuitem', { name: '複製 平衡型' }).click()
  await expect(page.getByLabel('策略名稱')).toHaveValue('平衡型 副本')
  await page.getByLabel('策略名稱').fill(name)
  await page.getByRole('button', { name: '儲存', exact: true }).first().click()
  await page.waitForURL(/\/strategies\/stg_[a-z0-9]+\/edit$/)
  return page.url().split('/').at(-2)!
}

test('a built-in strategy copied in the designer saves on the server with all of its rules and reloads', async ({ page, consoleErrors }) => {
  void consoleErrors
  const site = (await apiGet(page, '/v1/auth/status')) as { features: { strategy_library: 'off' | 'administrators' | 'everyone' } }
  await page.goto('/strategies')
  // A visitor is invited to sign in only where the site shows the library to everyone; kept for administrators, the address answers like one that does not exist.
  if (site.features.strategy_library === 'everyone') await expect(page.getByText('登入後保存並使用你自己的策略')).toBeVisible()
  else await expect(page.getByRole('heading', { name: '找不到這個頁面', level: 1 })).toBeVisible()
  await signIn(page)
  await page.reload()
  await expect(page.getByRole('radiogroup', { name: '使用中的策略' }).getByRole('radio'), 'one choice per built-in').toHaveText(['平衡型'])

  const id = await copyBalanced(page, 'E2E 平衡副本')
  const saved = (await apiGet(page, '/v1/technical-settings')) as Settings
  const official = ((await apiGet(page, '/v1/technical-settings/built-in-strategies')) as Strategy[]).find((item) => item.strategy_id === 'balanced')!
  const copy = saved.strategies.find((item) => item.strategy_id === id)!
  expect(copy.name).toBe('E2E 平衡副本')
  const unnamed = (rules: Strategy['rules']) => rules.map((rule) => ({ ...rule, name: null }))
  expect(unnamed(copy.rules), 'the copy keeps every rule of the built-in').toEqual(unnamed(official.rules))
  expect(copy.rules[0]?.name, 'a copy made in zh-TW names its rules in Chinese').toBe('股價站上 20 日均線')
  expect(copy.indicators).toEqual(official.indicators)
  await page.screenshot({ path: `${SHOTS}/live-builder-saved.png`, fullPage: true })

  await page.reload()
  await expect(page.getByLabel('策略名稱'), 'the session survives a reload').toHaveValue('E2E 平衡副本')
})

test('a save from an older revision keeps the draft and saves it into the newer settings', async ({ browser }) => {
  const contexts = await Promise.all([browser.newContext(), browser.newContext()])
  const [first, second] = await Promise.all(contexts.map((context) => context.newPage()))
  for (const page of [first!, second!]) {
    await signIn(page)
    await page.goto('/strategies/new?builtin=balanced')
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
  await page.goto('/market')
  await expect(page.getByRole('heading', { name: '市場總覽', level: 1 })).toBeVisible()
  await expect(page).toHaveTitle('市場總覽 · Stock Agent')

  const level = new Intl.NumberFormat('zh-TW', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(history.bars.at(-1)!.close)
  const trend = page.getByRole('region', { name: /加權指數/ })
  await expect(trend.getByRole('heading', { level: 2 })).toContainText('指數 · 預設')
  await expect(trend.getByText(level, { exact: true }).first()).toBeVisible({ timeout: 60_000 })
  await trend.getByRole('radio', { name: '1 年' }).click()
  await expect(trend.getByText('1 年漲跌', { exact: true })).toBeVisible()

  const most = page.getByRole('region', { name: '成交熱絡' })
  await expect(most.getByRole('link')).toHaveCount(Math.min(mostTraded.length, 10))
  await expect(most.getByRole('link').first()).toContainText(mostTraded[0]!.stock_id)
  if (mostTraded.length > 10) {
    await most.getByRole('button', { name: `顯示全部 ${mostTraded.length} 檔` }).click()
    await expect(most.getByRole('link')).toHaveCount(mostTraded.length)
  }

  const panel = page.getByRole('region', { name: '漲跌家數' })
  const count = (value: number) => new Intl.NumberFormat('zh-TW').format(value)
  for (const [label, value] of [['上漲', breadth.market.advancers], ['下跌', breadth.market.decliners], ['平盤', breadth.market.unchanged]] as const) {
    await expect(panel.getByRole('term').filter({ hasText: label }).locator('xpath=following-sibling::dd[1]')).toHaveText(count(value))
  }
  const industries = Object.keys(breadth.industries).length
  const heatMap = page.getByRole('region', { name: '產業強弱' }).getByRole('list', { name: '產業強弱' })
  await expect(heatMap.getByRole('listitem'), 'every industry on the wide heat map').toHaveCount(industries)
  await page.screenshot({ path: `${SHOTS}/live-overview.png`, fullPage: true })

})

test('the home page reads the market, the ranking, the holdings and the watchlist, each card leading to its page; a navigation names the tab and moves the focus to the content', async ({ page, consoleErrors }) => {
  void consoleErrors
  await signIn(page)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '今日', level: 1 })).toBeVisible()
  await expect(page).toHaveTitle('今日 · Stock Agent')
  const main = page.getByRole('main')
  const cards = { 加權指數: ['市場總覽', '/market'], 這個月的排名: ['全部 20 檔與回測', '/ranking'], 我的持股: ['全部持股', '/holdings'], 觀察清單: ['完整清單', '/watchlist'] }
  for (const [card, [link, to]] of Object.entries(cards)) await expect(main.getByRole('region', { name: card }).getByRole('link', { name: link! }), card).toHaveAttribute('href', to!)
  await expect(main.getByRole('link', { name: '登入', exact: true }), 'a signed-in reader is asked nothing').toHaveCount(0)
  // The first ranking after a server start reads the whole history.
  await expect(main.getByRole('table', { name: '這個月的排名' }).getByRole('row')).toHaveCount(11, { timeout: 180_000 })
  await page.screenshot({ path: `${SHOTS}/live-home.png`, fullPage: true })

  const nav = page.getByRole('navigation', { name: '主要導覽' })
  await expect(nav.getByRole('link').first()).toHaveText('今日')
  await expect(nav.getByRole('link', { name: '今日' })).toHaveAttribute('aria-current', 'page')
  await expect(nav.getByRole('button', { name: '輔助分析工具' })).toHaveAttribute('aria-expanded', 'false')
  await nav.getByRole('link', { name: '我的持股' }).click()
  await expect(page.getByRole('heading', { name: '我的持股', level: 1 })).toBeVisible()
  await expect(page).toHaveTitle('我的持股 · Stock Agent')
  await expect(page.locator('#main')).toBeFocused()

  await page.goto('/no-such-page')
  await page.getByRole('link', { name: '回到首頁' }).click()
  await expect(page.getByRole('heading', { name: '今日', level: 1 })).toBeVisible()
})

test('a visitor’s home page shows the market and one invitation to sign in, not one per private card', async ({ page, consoleErrors }) => {
  void consoleErrors
  await page.goto('/')
  const main = page.getByRole('main')
  await expect(main.getByRole('region', { name: '加權指數' })).toBeVisible()
  await expect(main.getByRole('link', { name: '登入', exact: true })).toHaveCount(1)
  await expect(main.getByText('你的帳號會保存')).toBeVisible()
  for (const card of ['這個月的排名', '我的持股', '觀察清單']) await expect(main.getByRole('region', { name: card }), card).toHaveCount(0)
  await page.screenshot({ path: `${SHOTS}/live-home-visitor.png`, fullPage: true })
})

test('the ranking shows this month’s 20 stocks, a five-year backtest kept in the address, and a past decision, each simulated figure named as one', async ({ page, consoleErrors }) => {
  void consoleErrors
  await signIn(page)
  await page.goto('/ranking')
  await expect(page.getByRole('heading', { name: '月營收排名', level: 1 })).toBeVisible()
  // The first answer after a server start reads the whole history, which can take a minute.
  const latest = page.getByRole('table', { name: '這個月的排名' })
  await expect(latest).toBeVisible({ timeout: 180_000 })
  await expect(latest.getByRole('row'), 'the header and 20 stocks').toHaveCount(21)
  const served = (await apiGet(page, '/v1/rankings/latest')) as { stocks: { stock_id: string }[] }
  await expect(latest.getByRole('row').nth(1), 'the first row is the server’s first stock').toContainText(served.stocks[0]!.stock_id)

  // The backtest shows as three figures marked simulated; its period and every decision are one tap away.
  const backtest = page.getByRole('region', { name: /^回測/ }).first()
  await expect(backtest.getByRole('table', { name: /排名組合與 .+ 的比較/ }).getByRole('row')).toHaveCount(4, { timeout: 180_000 })
  await expect(backtest.getByText('模擬', { exact: true }), 'the backtest says it is simulated').toBeVisible()
  await expect(page.getByRole('button', { name: '近 5 年' }), 'the detail is closed until asked for').toHaveCount(0)
  await backtest.getByRole('button', { name: '期間、走勢與每次決策' }).click()
  await page.getByRole('button', { name: '近 5 年' }).click()
  await expect(page).toHaveURL(/[?&]period=5Y(&|$)/)
  await expect(page.getByRole('button', { name: '近 5 年' })).toHaveAttribute('aria-pressed', 'true')
  await page.reload()
  await expect(page.getByRole('button', { name: '近 5 年' }), 'the period survives a reload and opens the detail').toHaveAttribute('aria-pressed', 'true', { timeout: 180_000 })

  const months = page.getByRole('region', { name: '回測：過去每一次決策' })
  await expect(months.getByRole('table')).toBeVisible({ timeout: 180_000 })
  await expect(page.getByRole('main').getByText('僅供研究參考，不構成投資建議。').first()).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/live-ranking.png`, fullPage: true })

  await months.getByRole('link', { name: /^查看 .+ 的排名$/ }).nth(1).click()
  await expect(page).toHaveURL(/[?&]month=\d{4}-\d{2}-\d{2}/)
  await expect(page).toHaveURL(/[?&]period=5Y(&|$)/)
  const decision = page.getByRole('dialog', { name: /.+ 的排名$/ })
  await expect(decision.getByRole('table').getByRole('row'), 'the header and that decision’s 20 stocks').toHaveCount(21, { timeout: 60_000 })
  await page.reload()
  await expect(page.getByRole('dialog', { name: /.+ 的排名$/ }), 'the open decision survives a reload').toBeVisible({ timeout: 180_000 })
})

test('the research target can be changed through the listing search, kept in the address, and set back', async ({ page, consoleErrors }) => {
  void consoleErrors
  await page.goto('/market')
  await page.getByRole('button', { name: '更換' }).click()
  await page.getByRole('combobox').fill('2330')
  await page.getByRole('option', { name: /2330/ }).first().click({ timeout: 120_000 })
  await expect(page).toHaveURL(/\/market\?target=2330$/)
  const trend = page.getByRole('region', { name: /2330/ })
  await expect(trend.getByRole('heading', { level: 2 })).toContainText('台積電', { timeout: 60_000 })
  await expect(trend.getByRole('heading', { level: 2 })).not.toContainText('預設')
  await page.reload()
  await expect(page.getByRole('region', { name: /2330/ }).getByRole('heading', { level: 2 })).toContainText('台積電', { timeout: 60_000 })
  await page.getByRole('link', { name: '改回加權指數' }).click()
  await expect(page).toHaveURL(/\/market$/)
  await expect(page.getByRole('region', { name: /加權指數/ }).getByRole('heading', { level: 2 })).toContainText('指數 · 預設')
})

test('after switching the strategy in use, the stock page evaluates with the new one', async ({ page, consoleErrors }) => {
  void consoleErrors
  await signIn(page)
  await copyBalanced(page, 'E2E 切換用')
  await page.goto('/strategies')
  const activateBuiltIn = async () => {
    const choice = page.getByRole('radiogroup', { name: '使用中的策略' }).getByRole('radio', { name: '平衡型' })
    if ((await choice.getAttribute('aria-checked')) !== 'true') await choice.click()
    await expect(choice).toHaveAttribute('aria-checked', 'true')
  }
  const activateOwn = async (name: string) => {
    // An instance the suite ran on before holds a copy of this name from each run; any one of them will do.
    const row = page.getByRole('listitem', { name }).first()
    await row.getByRole('button', { name: '使用', exact: true }).click()
    await expect(row.getByText('使用中', { exact: true })).toBeVisible()
  }
  const evaluatedWith = async (name: string) => {
    await page.getByRole('button', { name: '搜尋股票' }).click()
    await page.getByRole('dialog').getByRole('combobox').fill('2330')
    await page.getByRole('option', { name: /2330/ }).first().click({ timeout: 120_000 })
    // The technical evaluation is a supporting tool: closed until the reader opens it.
    const evaluation = page.getByRole('region', { name: '技術評估' })
    await evaluation.getByRole('button', { name: '技術評估' }).click({ timeout: 120_000 })
    await expect(evaluation).toContainText(name, { timeout: 120_000 })
    await page.goto('/strategies')
  }
  await activateBuiltIn()
  await evaluatedWith('平衡型')
  await activateOwn('E2E 切換用')
  await evaluatedWith('E2E 切換用')
  await activateBuiltIn()
  await evaluatedWith('平衡型')
})

test('a card whose request fails says so and loads on retry, and going offline is announced', async ({ page }) => {
  let failing = true
  await page.route('**/v1/market/most-traded', (route) => (failing ? route.fulfill({ status: 503, json: { detail: 'The exchange listing is unavailable.' } }) : route.continue()))
  await page.goto('/market')
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
  await signIn(page)
  await apiWrite(page, 'post', '/v1/watchlist/manual/remove', { confirm: true, stock_ids: ['2330'] })
  await page.goto('/')
  await page.getByRole('button', { name: '搜尋股票' }).click()
  await page.getByRole('dialog').getByRole('combobox').fill('2330')
  await page.getByRole('option', { name: /2330/ }).first().click({ timeout: 120_000 })
  await expect(page.getByRole('heading', { level: 1 })).toContainText('台積電', { timeout: 120_000 })
  await expect(page.getByRole('heading', { name: '技術評估' })).toBeVisible({ timeout: 120_000 })
  await expect(page.getByText(/^\d{1,2}\/\d{1,2} 收盤/).first()).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/live-stock-2330.png`, fullPage: true })

  const manual = async () =>
    ((await apiGet(page, '/v1/watchlist')) as { stock_id: string; watchlist_type: string }[]).filter((entry) => entry.watchlist_type === 'manual').map((entry) => entry.stock_id)
  await page.getByRole('button', { name: '加入觀察清單' }).click()
  await expect(page.getByRole('button', { name: '已在觀察清單' })).toHaveAttribute('aria-pressed', 'true')
  await expect.poll(manual).toContain('2330')

  await page.getByRole('link', { name: '觀察清單' }).first().click()
  await page.getByRole('button', { name: '編輯' }).click()
  // The site may hold other watched stocks: only this one leaves.
  const others = (await manual()).filter((stock) => stock !== '2330')
  const row = page.getByRole('row', { name: /2330/ })
  await row.getByRole('button', { name: /^把 .+ 從手動觀察清單移除$/ }).click()
  await expect(row).toHaveCount(0)
  await expect.poll(manual).toEqual(others)
  if (others.length === 0) await expect(page.getByText('觀察清單是空的')).toBeVisible()
})

test('a specific-stock run starts after confirming its AI cost, ends, and keeps its report', async ({ page, consoleErrors }) => {
  void consoleErrors
  await signIn(page)
  await page.goto('/runs')
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
  await signIn(page)
  await page.goto('/account')
  await expect(page.getByText('模擬券商').first()).toBeVisible()
  await expect(page.getByText('不是真實資產')).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/live-account.png`, fullPage: true })
})

const VIEWPORTS = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'mobile', width: 390, height: 844 },
]
const PAGES = ['/', '/market', '/ranking', '/holdings', '/watchlist', '/account/sinopac', '/settings', '/runs', '/account', '/valuation', '/strategies', '/backtest', '/strategies/new', '/admin/users', '/admin/settings', '/stocks/2330']

for (const viewport of VIEWPORTS) {
  test(`${viewport.name}: every page fits without horizontal overflow, in both themes`, async ({ page, consoleErrors }) => {
    void consoleErrors
    await page.setViewportSize(viewport)
    await signIn(page)
    for (const path of PAGES) {
      await page.goto(path)
      await page.waitForLoadState('networkidle')
      expect(await horizontalOverflow(page), path).toBeLessThanOrEqual(0)
    }
    await expect(page.getByRole('banner').getByRole('button', { name: /的帳號選單/ }), 'the account menu has a name at this width').toBeVisible()
    await page.screenshot({ path: `${SHOTS}/${viewport.name}-stock-dark.png`, fullPage: true })
    await page.emulateMedia({ colorScheme: 'light' })
  })
}

test('English, light theme, keyboard skip link and focus', async ({ page, consoleErrors }) => {
  void consoleErrors
  await page.goto('/')
  await page.getByRole('button', { name: '語言' }).click()
  await page.getByRole('menuitem', { name: 'English' }).click()
  await expect(page.getByRole('heading', { name: 'Today', level: 1 })).toBeVisible()
  await expect(page).toHaveTitle('Today · Stock Agent')
  await page.getByRole('button', { name: 'Theme' }).click()
  await page.getByRole('menuitem', { name: 'Light' }).click()
  await expect(page.locator('html')).not.toHaveClass(/dark/)
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(1000)
  await page.screenshot({ path: `${SHOTS}/light-en-home.png`, fullPage: true })

  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.locator('#main')).toBeFocused()
  const signInLink = page.getByRole('banner').getByRole('link', { name: 'Sign in' })
  await signInLink.focus()
  const ring = await signInLink.evaluate((element) => getComputedStyle(element).outlineStyle + getComputedStyle(element).boxShadow)
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
    await signIn(page)
    await page.goto(`/runs/${RUNNING.run_id}`)
    const icon = page.getByRole('main').getByText('執行中', { exact: true }).first().locator('svg')
    await expect(icon).toBeVisible()
    spinning[reducedMotion] = await icon.evaluate((element) => element.getAnimations().some((animation) => animation.playState === 'running'))
    await context.close()
  }
  expect(spinning).toEqual({ reduce: false, 'no-preference': true })
})
