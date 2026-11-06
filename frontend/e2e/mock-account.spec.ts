import type { Page } from '@playwright/test'
import { apiGet, APP_HEADER, apiWrite, expect, signIn, test } from './fixtures'

/**
 * The mock account against a real backend on the mock broker: a reset through My settings and its confirmation, then
 * a follow of a finished Full Cycle into the account. Every assertion about saved data reads the server's own answer.
 *
 * The follow test needs E2E_FOLLOW_RUN_ID: a finished Full Cycle run of the administrator whose BUYs and SELLs can all
 * fill now (no SELL of a stock the account does not hold). It skips without it, and outside the site's follow window.
 */
test.describe.configure({ mode: 'serial' })

const FOLLOW_RUN_ID = process.env.E2E_FOLLOW_RUN_ID ?? ''

type Opening = { initial_cash: number; opened_at: string }
type History = { opening: Opening | null; current: { cash: number; positions: unknown[] } }
type Trade = { order: { run_id: string; filled_quantity: number }; run: { run_id: string; workflow: string } }
type Follow = { refusal: 'nothing_to_follow' | 'outside_follow_window' | null; open_decision_ids: string[] }

async function trades(page: Page): Promise<Trade[]> {
  return (await apiGet(page, '/v1/account/trades?limit=50&offset=0')) as Trade[]
}

test('a reset through My settings asks first, then the account opens again with the new capital and says how to fill it', async ({ page, consoleErrors }) => {
  void consoleErrors
  await signIn(page)
  const opened = ((await apiGet(page, '/v1/account/history')) as History).opening?.opened_at
  expect(opened, 'the mock broker reports when the account opened').toBeDefined()
  await page.goto('/settings')
  const panel = page.getByRole('region', { name: '模擬帳戶' })
  await panel.getByLabel('新的起始資金').fill('2345678')
  await panel.getByRole('button', { name: '重設模擬帳戶…' }).click()

  const dialog = page.getByRole('alertdialog', { name: '要重設你的模擬帳戶嗎？' })
  await expect(dialog).toContainText('所有持股。')
  await expect(dialog).toContainText('現金變為 2,345,678。')
  await expect(dialog).toContainText('你的分析任務與它們的訂單，仍在「分析任務」中。')
  expect(((await apiGet(page, '/v1/account/history')) as History).opening?.opened_at, 'nothing reset before the yes').toBe(opened)
  await dialog.getByRole('button', { name: '重設', exact: true }).click()
  await expect(panel.getByText(/^已重設。模擬帳戶於 .+ 以 2,345,678 重新開始。$/)).toBeVisible()

  const history = (await apiGet(page, '/v1/account/history')) as History
  expect(history.opening).toMatchObject({ initial_cash: 2_345_678 })
  expect(history.opening?.opened_at, 'opened again').not.toBe(opened)
  expect(history.current).toMatchObject({ cash: 2_345_678, positions: [] })
  expect(await trades(page), 'the trades start anew').toEqual([])

  await page.goto('/account')
  await expect(page.getByText('起始資金').locator('..')).toContainText('2,345,678')
  await expect(page.getByText('模擬帳戶目前是空的')).toBeVisible()
  await expect(page.getByRole('link', { name: '前往分析任務' })).toHaveAttribute('href', '/')
})

test('a followed Full Cycle fills in the mock account, the trade names that run, and the run has nothing left to follow', async ({ page, consoleErrors }) => {
  void consoleErrors
  test.skip(FOLLOW_RUN_ID === '', 'E2E_FOLLOW_RUN_ID is not set')
  await signIn(page)
  await apiWrite(page, 'post', '/v1/account/reset', { confirm: true, initial_cash: 1_000_000 })
  const before = (await apiGet(page, `/v1/runs/${FOLLOW_RUN_ID}/follow`)) as Follow
  test.skip(before.refusal === 'outside_follow_window', 'outside the site’s follow window')
  expect(before.refusal, 'the reset opened every decision again').toBeNull()

  await page.goto(`/runs/${FOLLOW_RUN_ID}`)
  const panel = page.getByRole('region', { name: '跟單到模擬帳戶' })
  await expect(panel).toContainText(`（${before.open_decision_ids.length} 筆）`)
  await panel.getByRole('button', { name: '跟單到我的模擬帳戶' }).click()
  const dialog = page.getByRole('alertdialog', { name: '要把這次任務跟單到模擬帳戶嗎？' })
  await expect(dialog.getByRole('listitem')).toHaveCount(before.open_decision_ids.length)
  await dialog.getByRole('button', { name: '跟單', exact: true }).click()

  await page.waitForURL((url) => url.pathname.startsWith('/runs/') && !url.pathname.endsWith(FOLLOW_RUN_ID))
  const followId = page.url().split('/').at(-1)!
  await expect(page.getByRole('heading', { name: '跟單', level: 1 })).toBeVisible()
  await expect(page.getByRole('link', { name: '開啟原始任務' })).toHaveAttribute('href', `/runs/${FOLLOW_RUN_ID}`)
  await expect(page.getByText('已完成', { exact: true }).first(), 'the follow ends').toBeVisible({ timeout: 120_000 })

  const filled = (await trades(page)).filter((trade) => trade.order.run_id === followId)
  expect(filled.length, 'the follow filled').toBeGreaterThan(0)
  for (const trade of filled) expect(trade.run).toMatchObject({ run_id: FOLLOW_RUN_ID, workflow: 'full_cycle' })

  await page.goto('/account')
  const table = page.getByRole('table', { name: '成交紀錄' })
  const source = table.getByRole('link', { name: /^全市場分析 · / }).first()
  await expect(source).toHaveAttribute('href', `/runs/${FOLLOW_RUN_ID}`)
  await expect(table.getByText('跟單', { exact: true }).first()).toBeVisible()

  await page.goto(`/runs/${FOLLOW_RUN_ID}`)
  await expect(page.getByText(/^這次任務的每筆買進與賣出都已跟單到模擬帳戶。/)).toBeVisible()
  await expect(page.getByRole('button', { name: '跟單到我的模擬帳戶' })).toBeDisabled()
  const again = await page.request.post(`/v1/runs/${FOLLOW_RUN_ID}/follow`, { headers: APP_HEADER, data: { confirm: true } })
  expect(again.status()).toBe(409)
  expect(((await again.json()) as { code: string }).code).toBe('nothing_to_follow')
})
