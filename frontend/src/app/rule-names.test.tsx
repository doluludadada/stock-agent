import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { RouterProvider, createMemoryRouter, type RouteObject } from 'react-router'
import { builtInJson } from '@/features/strategies/model/built-ins.test-support'
import { changeLocale, initI18n, type Locale } from '@/i18n'
import { session } from '@/shared/api'
import { TEST_USER } from '@/test/users'
import { RunRoute } from './router/routes/runs'
import { EditStrategyRoute, NewStrategyRoute, StrategyLibraryRoute } from './router/routes/strategies'

const RUN = '22222222-2222-4222-8222-222222222222'
const MY_RUN = '33333333-3333-4333-8333-333333333333'
const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
const i18n = initI18n('zh-TW')

const balanced = builtInJson('balanced')
const mine = { ...balanced, strategy_id: 'mine', name: 'Mine', rules: [balanced.rules[0]!, { ...balanced.rules[1]!, name: 'My own rule' }] }
const report = {
  stock_id: '2330',
  name: '台積電',
  current_price: 1000,
  latest_market_data_at: null,
  technical_report: { score: 20, hard_failures: ['Price Above MA_20', 'My own rule'], soft_failures: [], observations: [] },
  ai_report: null,
  composite_score: null,
}

/** A specific-stock run's record that applied the strategy `strategyId`. */
const summary = (strategyId: string) => ({
  workflow: 'specific_stocks',
  execution_provider: 'mock',
  order_mode: 'mock_only',
  start_time: '2026-11-05T01:00:00Z',
  end_time: '2026-11-05T01:01:00Z',
  total_scanned: 0,
  buzz_scanned: 0,
  buzz_qualified: 0,
  passed_technical: 0,
  ai_analysed: 0,
  signals_generated: 0,
  orders_submitted: 0,
  orders_refused: 0,
  stale_market_data_count: 0,
  technical_strategy_id: strategyId,
  errors: [],
  execution_log: [],
})

function serve() {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url === '/v1/technical-settings/built-in-strategies') return json([balanced])
    if (url === '/v1/technical-settings') return json({ active_strategy_id: 'mine', buzz_strategy_id: 'mine', strategies: [mine], revision: 1 })
    if (url === `/v1/runs/${RUN}`) return json({ run_id: RUN, state: 'finished', error: null, summary: summary('balanced'), reports: [report] })
    if (url === `/v1/runs/${MY_RUN}`) return json({ run_id: MY_RUN, state: 'finished', error: null, summary: summary('mine'), reports: [report] })
    return json([])
  }))
}

async function open(locale: Locale, routes: RouteObject[], path: string) {
  await act(() => changeLocale(locale))
  render(
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

describe('the built-in strategies’ rule names', () => {
  beforeAll(() => {
    Element.prototype.scrollIntoView = () => undefined
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
  })
  beforeEach(() => {
    serve()
    session.signIn(TEST_USER)
  })
  afterEach(() => session.signOut())
  afterAll(() => vi.unstubAllGlobals())

  it('read in Chinese in the rules sheet of the zh-TW library', async () => {
    const user = userEvent.setup()
    await open('zh-TW', [{ path: '/strategies', element: <StrategyLibraryRoute /> }], '/strategies')
    await user.click(within(await screen.findByRole('article', { name: '平衡型' })).getByRole('button', { name: '查看規則' }))
    const sheet = await screen.findByRole('dialog')
    expect(within(sheet).getByText('股價站上 20 日均線')).toBeVisible()
    expect(sheet.textContent).not.toContain('Price Above MA_20')
  })

  it('stay in English in the English rules sheet', async () => {
    const user = userEvent.setup()
    await open('en', [{ path: '/strategies', element: <StrategyLibraryRoute /> }], '/strategies')
    await user.click(within(await screen.findByRole('article', { name: 'Balanced' })).getByRole('button', { name: 'View rules' }))
    expect(within(await screen.findByRole('dialog')).getByText('Price Above MA_20')).toBeVisible()
  })

  it('read in Chinese among the exclusions of a zh-TW run on the built-in strategy', async () => {
    await open('zh-TW', [{ path: '/runs/:runId', element: <RunRoute /> }], `/runs/${RUN}`)
    const excluded = (await screen.findByText('被 2 條規則排除')).parentElement!
    expect(within(excluded).getAllByRole('listitem').map((item) => item.textContent)).toEqual(['股價站上 20 日均線', 'My own rule'])
  })

  it('stay as the owner typed them in a zh-TW run on the owner’s own strategy, even one a built-in rule is named', async () => {
    await open('zh-TW', [{ path: '/runs/:runId', element: <RunRoute /> }], `/runs/${MY_RUN}`)
    const excluded = (await screen.findByText('被 2 條規則排除')).parentElement!
    expect(within(excluded).getAllByRole('listitem').map((item) => item.textContent)).toEqual(['Price Above MA_20', 'My own rule'])
  })

  it('read in the designer’s preview exactly as its name fields hold them', async () => {
    await open('zh-TW', [{ path: '/strategies/:id/edit', element: <EditStrategyRoute /> }], '/strategies/mine/edit')
    const fields = (await screen.findAllByLabelText('規則名稱')).map((input) => (input as HTMLInputElement).value)
    expect(fields).toEqual(['Price Above MA_20', 'My own rule'])
    const preview = await screen.findByRole('region', { name: '公式預覽' })
    expect(within(preview).getByText('Price Above MA_20')).toBeVisible()
    expect(preview.textContent).not.toContain('股價站上 20 日均線')
  })

  it('stay in English among an English run’s exclusions', async () => {
    await open('en', [{ path: '/runs/:runId', element: <RunRoute /> }], `/runs/${RUN}`)
    const excluded = (await screen.findByText('Excluded by 2 rules')).parentElement!
    expect(within(excluded).getAllByRole('listitem').map((item) => item.textContent)).toEqual(['Price Above MA_20', 'My own rule'])
  })

  it('are written in Chinese into a zh-TW copy of a built-in', async () => {
    const builder = [{ path: '/strategies/new', element: <NewStrategyRoute /> }]
    await open('zh-TW', builder, '/strategies/new?builtin=balanced')
    const copied = (await screen.findAllByLabelText('規則名稱')).map((input) => (input as HTMLInputElement).value)
    expect(copied.slice(0, 3)).toEqual(['股價站上 20 日均線', '均線多頭排列（20 日 > 60 日）', 'MACD 多頭（快線 > 訊號線）'])
    expect(copied).toHaveLength(balanced.rules.length)
    expect(copied).not.toContain('Price Above MA_20')
  })

  it('stay as the owner typed them in a copy of the owner’s own strategy', async () => {
    await open('zh-TW', [{ path: '/strategies/new', element: <NewStrategyRoute /> }], '/strategies/new?from=mine')
    const copied = (await screen.findAllByLabelText('規則名稱')).map((input) => (input as HTMLInputElement).value)
    expect(copied).toEqual(['Price Above MA_20', 'My own rule'])
  })
})
