import { apiGet, expect, signIn, test, withoutSecureContext } from './fixtures'

/**
 * The formula designer for an administrator who has saved nothing yet, on the site as it is reached over plain http
 * at a host name. It runs on any backend, a fresh one too: E2E_SETUP_CODE sets up the first administrator there.
 */

type Settings = { strategies: { strategy_id: string; name: string; rules: { name: string }[] }[] }

const STRATEGY = 'E2E 最小策略'
const RULES = ['收盤站上均線', '第二條規則']

test.beforeEach(async ({ page }) => {
  await withoutSecureContext(page)
  await signIn(page)
})

test('a strategy built from blank in the designer, opened from the navigation, saves with its rules', async ({ page, consoleErrors }) => {
  void consoleErrors
  await page.goto('/')
  expect(await page.evaluate(() => typeof crypto.randomUUID), 'the page has no secure context').toBe('undefined')
  await page.getByRole('button', { name: '其他工具' }).click()
  await page.getByRole('link', { name: '公式設計器' }).click()
  await page.waitForURL('**/strategies/new')
  await expect(page.getByText('尚未儲存').first()).toBeVisible()

  await page.getByLabel('策略名稱').fill(STRATEGY)
  await page.getByRole('region', { name: '規則 1' }).getByLabel('規則名稱').fill(RULES[0]!)
  await page.getByRole('button', { name: '新增規則' }).click()
  await page.getByRole('region', { name: '規則 2' }).getByLabel('規則名稱').fill(RULES[1]!)
  await page.getByRole('button', { name: '儲存', exact: true }).first().click()
  await page.waitForURL(/\/strategies\/stg_[0-9a-f]+\/edit$/)

  const id = page.url().split('/').at(-2)!
  const saved = ((await apiGet(page, '/v1/technical-settings')) as Settings).strategies.find((strategy) => strategy.strategy_id === id)
  expect(saved?.name).toBe(STRATEGY)
  expect(saved?.rules.map((rule) => rule.name)).toEqual(RULES)

  await page.reload()
  await expect(page.getByLabel('策略名稱'), 'the saved strategy opens again').toHaveValue(STRATEGY)
})

test('the library opens the designer on a blank strategy and on a copy of a built-in', async ({ page, consoleErrors }) => {
  void consoleErrors
  await page.goto('/strategies')
  await page.getByRole('button', { name: '新增策略' }).click()
  await page.getByRole('menuitem', { name: '空白策略' }).click()
  await expect(page.getByRole('region', { name: '規則 1' })).toBeVisible()
  await expect(page.getByLabel('策略名稱')).toHaveValue('')

  await page.goto('/strategies')
  await page.getByRole('button', { name: '新增策略' }).click()
  await page.getByRole('menuitem', { name: '複製 平衡型' }).click()
  await expect(page.getByLabel('策略名稱')).toHaveValue('平衡型 副本')

  await page.reload()
  await expect(page.getByLabel('策略名稱'), 'a copy opens by its address too').toHaveValue('平衡型 副本')
})
