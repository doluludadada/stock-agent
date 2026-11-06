import { apiGet, expect, signIn, test } from './fixtures'

/**
 * What the site's audience allows, against a real backend of either audience: the server's own answers decide what each
 * page must show. Every page credits the open data and says nothing here is advice, and the stock page reads the
 * stock's archived financials. E2E_SHOTS names the folder each view is saved to.
 */

const SHOTS = process.env.E2E_SHOTS ?? 'docs/screenshots'

type Audience = { audience: 'personal' | 'public'; open_data_only: boolean; realtime_quotes: boolean; mops: boolean }
type Attribution = { providers: { provider: string; datasets: string[] }[]; license: string; license_url: string }
type Financials = { quarters: { quarter: { year: number; quarter: number } }[]; monthly_revenues: unknown[] }

test('the navigation and the runs page offer what the site’s audience allows, and a link to the valuation says why a site without it has none', async ({ page, consoleErrors }) => {
  void consoleErrors
  await signIn(page)
  const site = (await apiGet(page, '/v1/market/audience')) as Audience
  await page.goto('/')
  const main = page.getByRole('main')
  await expect(main.getByRole('button', { name: '啟動', exact: true }), 'Full Cycle, specific stocks, and Buzz and Intraday only with realtime quotes').toHaveCount(
    site.realtime_quotes ? 4 : 2,
  )
  for (const kind of ['社群熱度', '盤中檢查']) await expect(main.getByRole('heading', { name: new RegExp(`^${kind}`) })).toHaveCount(site.realtime_quotes ? 1 : 0)
  const nav = page.getByRole('navigation', { name: '主要導覽' })
  await expect(nav.getByRole('link', { name: '市場總覽' })).toBeVisible()
  await expect(nav.getByRole('link', { name: '估值' })).toHaveCount(site.mops ? 1 : 0)
  await page.screenshot({ path: `${SHOTS}/${site.audience}-navigation.png`, fullPage: true })

  await page.goto('/valuation')
  if (site.mops) {
    await expect(page.getByRole('heading', { level: 1, name: '本益比估值' })).toBeVisible()
  } else {
    await expect(page.getByRole('status').getByText('本站不提供估值')).toBeVisible()
    await expect(page.getByRole('status').getByRole('link', { name: '資料來源與授權' })).toHaveAttribute('href', '/attribution')
  }
  await page.screenshot({ path: `${SHOTS}/${site.audience}-valuation-link.png`, fullPage: true })
})

test('every page links to the open data’s credit, which names each provider, its datasets and the license as the server gives them', async ({ page, consoleErrors }) => {
  void consoleErrors
  const attribution = (await apiGet(page, '/v1/market/attribution')) as Attribution
  const site = (await apiGet(page, '/v1/market/audience')) as Audience
  await page.goto('/market')
  const footer = page.getByRole('contentinfo')
  await expect(footer.getByText(/不構成投資建議/)).toBeVisible()
  await footer.getByRole('link', { name: '資料來源與授權' }).click()

  await expect(page.getByRole('heading', { level: 1, name: '資料來源與授權' })).toBeVisible()
  for (const provider of attribution.providers) {
    const panel = page.getByRole('region', { name: provider.provider })
    await expect(panel.getByRole('listitem')).toHaveText(provider.datasets)
  }
  await expect(page.getByRole('link', { name: attribution.license })).toHaveAttribute('href', attribution.license_url)
  await expect(page.getByText(attribution.license_url, { exact: true })).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/${site.audience}-attribution.png`, fullPage: true })
})

test('on open data the market overview says how far the archive has come until it holds the sessions the strategies need', async ({ page, consoleErrors }) => {
  void consoleErrors
  const site = (await apiGet(page, '/v1/market/audience')) as Audience
  const archive = (await apiGet(page, '/v1/market/archive-status')) as { sessions: number; needed: number }
  await page.goto('/market')
  await expect(page.getByRole('heading', { level: 1, name: '市場總覽' })).toBeVisible()
  const warmUp = page.getByRole('region', { name: '開放資料存檔' })
  if (site.open_data_only && archive.sessions < archive.needed) await expect(warmUp).toContainText(`資料累積中 ${archive.sessions}/${archive.needed}`)
  else await expect(warmUp).toHaveCount(0)
  await page.screenshot({ path: `${SHOTS}/${site.audience}-market-overview.png`, fullPage: true })
})

test('the stock page shows the stock’s archived quarters and latest monthly revenue beside its not-advice note', async ({ page, consoleErrors }) => {
  void consoleErrors
  const site = (await apiGet(page, '/v1/market/audience')) as Audience
  const stockId = process.env.E2E_FINANCIALS_STOCK ?? '2330'
  const financials = (await apiGet(page, `/v1/market/stocks/${stockId}/financials`)) as Financials
  await page.goto(`/stocks/${stockId}`)
  await expect(page.getByRole('main').getByText('僅供研究參考，不構成投資建議。')).toBeVisible()
  const panel = page.getByRole('region', { name: '財務數據' })
  const latest = financials.quarters.at(-1)
  if (latest) {
    const table = panel.getByRole('table', { name: '季度數據' })
    await expect(table.getByRole('columnheader').nth(1)).toHaveText(`${latest.quarter.year} Q${latest.quarter.quarter}`)
    await expect(table.getByRole('row')).toHaveCount(10)
  } else if (financials.monthly_revenues.length === 0) {
    await expect(panel.getByText('尚未保存財務數據')).toBeVisible()
  }
  if (financials.monthly_revenues.length > 0) await expect(panel.getByText(/營收$/)).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/${site.audience}-stock-financials.png`, fullPage: true })
})
