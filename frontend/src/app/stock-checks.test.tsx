import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { builtInJson } from '@/features/strategies/model/built-ins.test-support'
import { initI18n } from '@/i18n'
import { session } from '@/shared/api'
import { TEST_USER } from '@/test/users'
import { StockRoute } from './router/routes/stock'

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
const bars = ['2026-11-03', '2026-11-04'].map((day, index) => ({
  ts: `${day}T13:30:00+08:00`,
  open: 2300,
  high: 2335,
  low: 2280,
  close: 2295 - index * 35,
  volume: 46_137_336,
  change: index === 0 ? null : -35,
}))

describe('the stock page’s checks', () => {
  beforeAll(() => vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }))
  afterAll(() => vi.unstubAllGlobals())
  afterEach(() => session.signOut())

  it('say each rule the report names in the reader’s words, and name it in Chinese on hover, never in the strategy’s English', { timeout: 30_000 }, async () => {
    const strategy = builtInJson('balanced')
    const [excluding, , bonus] = strategy.rules.filter((rule) => rule.effect !== 'reduce_score_on_fail')
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.startsWith('/v1/market/stocks/2330/technical')) {
          return json({
            stock_id: '2330',
            strategy,
            required_bars: 61,
            bar_times: bars.map((bar) => bar.ts),
            latest_price: 2260,
            report: { score: 20, hard_failures: [excluding!.name], soft_failures: [], observations: [`${bonus!.name}: not detected`] },
            readings: {},
            notes: [],
          })
        }
        if (url.startsWith('/v1/market/stocks/2330')) return json({ stock: { stock_id: '2330', name: '台積電', market: 'twse', today: bars[1] }, bars, notes: [] })
        return json([])
      }),
    )
    session.signIn(TEST_USER)
    const router = createMemoryRouter([{ path: '/stocks/:code', element: <StockRoute /> }], { initialEntries: ['/stocks/2330'] })
    render(
      <I18nextProvider i18n={initI18n('zh-TW')}>
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </I18nextProvider>,
    )

    const details = await screen.findByRole('region', { name: '評估明細' }, { timeout: 15_000 })
    const excluded = within(details).getByRole('heading', { name: /排除項目/ }).closest('section')!
    expect(excluded.textContent).not.toContain(excluding!.name)
    expect(within(excluded).getByTitle('股價站上 20 日均線').textContent).toMatch(/[一-鿿]/)
    expect(within(excluded).queryByTitle(excluding!.name)).not.toBeInTheDocument()
    const bonuses = within(details).getByRole('heading', { name: /加分檢查/ }).closest('section')!
    expect(within(bonuses).getByText('未出現')).toBeVisible()
    expect(bonuses.textContent).not.toContain('not detected')
  })
})
