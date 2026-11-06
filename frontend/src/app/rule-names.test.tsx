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
import { NewStrategyRoute, StrategyLibraryRoute } from './router/routes/strategies'

const RUN = '22222222-2222-4222-8222-222222222222'
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

function serve() {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url === '/v1/technical-settings/built-in-strategies') return json([balanced])
    if (url === '/v1/technical-settings') return json({ active_strategy_id: 'mine', buzz_strategy_id: 'mine', strategies: [mine], revision: 1 })
    if (url === `/v1/runs/${RUN}`) return json({ run_id: RUN, state: 'finished', error: null, summary: null, reports: [report] })
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

  it('read in Chinese among a zh-TW run’s exclusions, while a name the owner typed stays as typed', async () => {
    const runRoute = [{ path: '/runs/:runId', element: <RunRoute /> }]
    await open('zh-TW', runRoute, `/runs/${RUN}`)
    const excluded = (await screen.findByText('被 2 條規則排除')).parentElement!
    expect(within(excluded).getAllByRole('listitem').map((item) => item.textContent)).toEqual(['股價站上 20 日均線', 'My own rule'])
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
