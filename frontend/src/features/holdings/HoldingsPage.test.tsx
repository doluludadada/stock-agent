import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n } from '@/i18n'
import { session, type Schemas } from '@/shared/api'
import { SHIPPED_FORMULA } from '@/test/ranking'
import { TEST_USER } from '@/test/users'
import { HoldingsPage } from './HoldingsPage'
import type { Holding, Holdings, WatchedStock } from './model'

type Standing = Schemas['StockRankingResponse']

const SCORED: Standing = {
  decided_on: '2026-11-13',
  revenue_month: '2026-10-01',
  universe: 1800,
  scored: 987,
  formula: SHIPPED_FORMULA,
  holds_cash: false,
  place: 12,
  score: 98.88,
  in_top: true,
  exclusion: null,
  stock: {
    stock_id: '2330',
    stock_name: null,
    factors: [
      { value: 1.253, rank: 0.92 },
      { value: 0.982, rank: 0.78 },
    ],
    score: 1.7,
  },
}
const AN_ETF: Standing = { ...SCORED, place: null, score: null, stock: null, in_top: false, exclusion: 'not_a_stock' }

const REVENUE = { year: 2026, month: 10, revenue: 367_473_000, year_over_year: 0.169, acceleration: 1.253, served_date: '2026-11-10' }

const AT_THE_BROKER: Holding = {
  source: 'brokerage',
  stock_name: '台積電',
  position: { stock_id: '2330', quantity: 1000, average_cost: 500, mark_price: 600, marked_at: '2026-11-13T05:30:00Z', market_value: 597_345, unrealized_pnl: 97_345, cost_basis: 500_000, unrealized_return: 0.1947, opened_at: null },
  weight: 0.7323,
  standing: SCORED,
  revenue: REVENUE,
  accelerating_months: 3,
}
const AN_ODD_LOT_BY_HAND: Holding = {
  source: 'manual',
  stock_name: '台積電',
  position: { stock_id: '2330', quantity: 37, average_cost: 550, mark_price: 600, marked_at: '2026-11-13T05:30:00Z', market_value: 22_101, unrealized_pnl: 1_751, cost_basis: 20_350, unrealized_return: 0.086, opened_at: '2026-03-02T01:00:00Z' },
  weight: 0.0271,
  standing: SCORED,
  revenue: REVENUE,
  accelerating_months: 3,
}
const AN_ETF_IN_THE_MOCK_ACCOUNT: Holding = {
  source: 'mock',
  stock_name: '元大台灣50',
  position: { stock_id: '0050', quantity: 2000, average_cost: 98.1, mark_price: 98.1, marked_at: null, market_value: 196_200, unrealized_pnl: 0, cost_basis: 196_200, unrealized_return: 0, opened_at: '2026-11-05T02:00:00Z' },
  weight: 0.2406,
  standing: AN_ETF,
  revenue: null,
  accelerating_months: null,
}

const MIXED: Holdings = {
  asked: ['brokerage', 'manual', 'mock'],
  sources: ['brokerage', 'manual', 'mock'],
  holdings: [AT_THE_BROKER, AN_ETF_IN_THE_MOCK_ACCOUNT, AN_ODD_LOT_BY_HAND],
  market_value: 815_646,
  cost: 716_550,
  unrealized_pnl: 99_096,
  unrealized_return: 0.1383,
  concentration_positions: 3,
  concentration: 1,
  top_share: 0.7594,
  scored_share: 0.7594,
  weighted_score: 98.88,
  lowest: AN_ODD_LOT_BY_HAND,
  highest: AT_THE_BROKER,
}
const NOTHING_HELD: Holdings = {
  ...MIXED,
  asked: ['manual', 'mock'],
  sources: ['manual', 'mock'],
  holdings: [],
  market_value: 0,
  cost: 0,
  unrealized_pnl: 0,
  unrealized_return: null,
  concentration: 0,
  top_share: 0,
  scored_share: 0,
  weighted_score: null,
  lowest: null,
  highest: null,
}

const LISTING: Record<string, string> = { '2330': '台積電', '2317': '鴻海' }
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

interface Sent {
  url: string
  body: unknown
}

/** The holdings endpoints and the listing as the backend answers them; `entry` answers a save. */
function serve(holdings: () => Response, entry: () => Response = () => json(AN_ODD_LOT_BY_HAND.position)) {
  const asked: string[] = []
  const sent: Sent[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const { pathname, searchParams } = new URL(url, 'http://localhost')
      if (init?.method === 'POST') {
        sent.push({ url, body: JSON.parse(String(init.body)) })
        if (pathname === '/v1/holdings/manual') return entry()
        if (pathname === '/v1/holdings/manual/remove') return new Response(null, { status: 204 })
      }
      asked.push(url)
      if (pathname === '/v1/holdings') return holdings()
      if (pathname === '/v1/market/stocks') {
        const code = searchParams.get('query') ?? ''
        return json(LISTING[code] ? [{ stock_id: code, name: LISTING[code], market: 'twse', today: null }] : [])
      }
      return json({ detail: 'Not found.', code: 'not_found' }, 404)
    }),
  )
  return { asked, sent }
}

function open(watched?: readonly WatchedStock[]) {
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <HoldingsPage watched={watched} />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

const rows = async () => within(await screen.findByRole('table', { name: 'Holdings' })).getAllByRole('row').slice(1)

describe('My holdings', () => {
  beforeEach(() => session.signIn(TEST_USER))
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('keeps the same stock at the broker and entered by hand as two rows, each under its source, largest first', async () => {
    serve(() => json(MIXED))
    open()

    const [broker, etf, byHand] = await rows()
    expect(within(broker!).getByRole('link', { name: /台積電/ })).toHaveAttribute('href', '/stocks/2330')
    expect(within(broker!).getByText('SinoPac account')).toBeVisible()
    expect(broker).toHaveTextContent('1,000 shares @ 500.00')
    expect(broker).toHaveTextContent('+97,345')
    expect(broker).toHaveTextContent('+19.47%')
    expect(broker).toHaveTextContent('73.2%')
    expect(broker).toHaveTextContent('600.00, 11/13 close')

    expect(within(byHand!).getByRole('link', { name: /台積電/ })).toHaveAttribute('href', '/stocks/2330')
    expect(within(byHand!).getByText('Entered by hand')).toBeVisible()
    expect(byHand, 'an odd lot reads as its own count of shares').toHaveTextContent('37 shares @ 550.00')

    expect(within(etf!).getByText('Mock account (play money)')).toBeVisible()
  })

  it('shows a score as the stock page does, and the reason in its place for a stock the ranking leaves out', async () => {
    serve(() => json(MIXED))
    open()

    const [broker, etf] = await rows()
    expect(broker).toHaveTextContent('99')
    expect(broker).toHaveTextContent('place 12 of 987')
    expect(broker).toHaveTextContent('Revenue acceleration PR 92 · Nearness to high PR 78')
    expect(within(broker!).getAllByText('In the top 20')[0]).toBeVisible()
    expect(broker).toHaveTextContent('×1.25')
    expect(broker).toHaveTextContent('above 1 for 3 months in a row')

    expect(within(etf!).getAllByText('No score')[0]).toBeVisible()
    expect(etf).toHaveTextContent('The ranking scores stocks only, not ETFs.')
    expect(etf).not.toHaveTextContent('In the top')
    expect(etf).toHaveTextContent('no close held, valued at cost')
    expect(etf).toHaveTextContent('no monthly revenue held')

    expect(screen.getByText(/It is no forecast\./)).toBeVisible()
    expect(screen.getByText('For research and reference only, not investment advice.')).toBeVisible()
  })

  it('reads the portfolio in figures: value, gain, concentration, the ranking’s share, the weighted score and what has none', async () => {
    serve(() => json(MIXED))
    open()

    const summary = within((await screen.findByText('815,646')).closest('section')!)
    expect(summary.getByText('Unrealized P&L').parentElement).toHaveTextContent('+99,096')
    expect(summary.getByText('Unrealized P&L').parentElement).toHaveTextContent('+13.83%')
    expect(summary.getByText('Top 3 holdings').parentElement).toHaveTextContent('100.0%')
    expect(summary.getByText('In this month’s ranking').parentElement).toHaveTextContent('75.9%')
    const weighted = summary.getByText('Value-weighted score').parentElement!
    expect(weighted).toHaveTextContent('99')
    expect(weighted).toHaveTextContent('24.1% of the value has no score')
  })

  it('never tells the reader what to do with a holding', async () => {
    serve(() => json(MIXED))
    open([{ stockId: '2317', name: '鴻海' }])

    await rows()
    expect(document.body.textContent).not.toMatch(/\b(buy|sell|add|trim|reduce|consider|should|recommend)\b/i)
  })

  it('leaves the score figures out where the site does not show the viewer the ranking', async () => {
    const unscored = (holding: Holding): Holding => ({ ...holding, standing: null })
    serve(() => json({ ...MIXED, holdings: MIXED.holdings.map(unscored), top_share: null, scored_share: null, weighted_score: null, lowest: null, highest: null }))
    open()

    await rows()
    expect(screen.queryByText('Value-weighted score')).not.toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Ranking score' })).not.toBeInTheDocument()
    expect(screen.queryByText(/It is no forecast/)).not.toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Revenue acceleration' })).toBeInTheDocument()
  })

  it('says once that the SinoPac login is down when the brokerage was asked and not read', async () => {
    serve(() => json({ ...MIXED, sources: ['manual', 'mock'], holdings: [AN_ETF_IN_THE_MOCK_ACCOUNT, AN_ODD_LOT_BY_HAND] }))
    open()

    expect(await rows()).toHaveLength(2)
    expect(screen.getAllByText('The site’s SinoPac login is down, so the holdings of the SinoPac account are not included here.')).toHaveLength(1)
  })

  it('asks again with the sources left checked, and keeps the last one checked', async () => {
    const { asked } = serve(() => json(MIXED))
    const user = userEvent.setup()
    open()

    await rows()
    const filter = within(screen.getByRole('group', { name: 'Count the holdings of' }))
    expect(filter.getAllByRole('checkbox').map((box) => box.getAttribute('aria-checked'))).toEqual(['true', 'true', 'true'])

    await user.click(filter.getByRole('checkbox', { name: 'Mock account (play money)' }))
    await waitFor(() => expect(asked.filter((url) => url.startsWith('/v1/holdings'))).toEqual(['/v1/holdings', '/v1/holdings?sources=brokerage&sources=manual']))

    await user.click(filter.getByRole('checkbox', { name: 'Entered by hand' }))
    await waitFor(() => expect(asked).toContain('/v1/holdings?sources=brokerage'))
    expect(filter.getByRole('checkbox', { name: 'SinoPac account' })).toBeDisabled()
  })

  it('with nothing held, says what the page does and leads to the entry form', async () => {
    serve(() => json(NOTHING_HELD))
    const user = userEvent.setup()
    open()

    expect(await screen.findByText('No holdings yet')).toBeVisible()
    expect(screen.getByText('Enter a stock you hold elsewhere. It is a note, not an order.')).toBeVisible()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Enter a holding' }))
    expect(await screen.findByRole('dialog', { name: 'Enter a holding' })).toBeVisible()
  })

  it('still takes an entry while the site holds no decision of the ranking', async () => {
    serve(() => json({ detail: 'No ranking can be made yet.', code: 'ranking_unavailable' }, 422))
    const user = userEvent.setup()
    open()

    expect(await screen.findByText('No ranking decision held yet')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Enter a holding' }))
    expect(await screen.findByRole('dialog', { name: 'Enter a holding' })).toBeVisible()
  })

  it('refuses a bad number at the form and sends nothing, then sends the entry as the API takes it', async () => {
    const { asked, sent } = serve(() => json(NOTHING_HELD))
    const user = userEvent.setup()
    open([{ stockId: '2317', name: '鴻海' }])

    await user.click(await screen.findByRole('button', { name: 'Enter 鴻海 as a holding' }))
    const form = within(await screen.findByRole('dialog', { name: 'Enter a holding' }))
    expect(await form.findByText('鴻海')).toBeVisible()

    await user.type(form.getByLabelText('Shares'), '1.5')
    await user.type(form.getByLabelText('Average cost per share (NT$)'), '0')
    await user.click(form.getByRole('button', { name: 'Keep the entry' }))
    expect(form.getByText('Whole shares from 1 to 1,000,000,000.')).toBeVisible()
    expect(form.getByText('A cost above 0, at most 1,000,000.')).toBeVisible()
    expect(sent).toEqual([])

    await user.clear(form.getByLabelText('Shares'))
    await user.type(form.getByLabelText('Shares'), '37')
    await user.clear(form.getByLabelText('Average cost per share (NT$)'))
    await user.type(form.getByLabelText('Average cost per share (NT$)'), '101.5')
    const before = asked.filter((url) => url === '/v1/holdings').length
    await user.click(form.getByRole('button', { name: 'Keep the entry' }))

    await waitFor(() => expect(sent).toEqual([{ url: '/v1/holdings/manual', body: { confirm: true, stock_id: '2317', quantity: 37, average_cost: 101.5 } }]))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await waitFor(() => expect(asked.filter((url) => url === '/v1/holdings').length, 'a save reloads the holdings').toBeGreaterThan(before))
  })

  it('takes the stock from the listing search, never from typed text, and refuses a form with none chosen', async () => {
    Element.prototype.scrollIntoView = () => undefined
    vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
    const { sent } = serve(() => json(NOTHING_HELD))
    const user = userEvent.setup()
    open()

    await user.click(await screen.findByRole('button', { name: 'Enter a holding' }))
    const form = within(await screen.findByRole('dialog', { name: 'Enter a holding' }))
    await user.type(form.getByLabelText('Shares'), '2000')
    await user.type(form.getByLabelText('Average cost per share (NT$)'), '98.1')
    await user.click(form.getByRole('button', { name: 'Keep the entry' }))
    expect(form.getByText('Choose a stock from the listing.')).toBeVisible()
    expect(sent).toEqual([])

    await user.click(form.getByRole('button', { name: 'Choose a stock' }))
    await user.type(await screen.findByRole('combobox'), '2330')
    await user.click(await screen.findByRole('option', { name: /台積電/ }))
    expect(await form.findByText('台積電')).toBeVisible()
    await user.click(form.getByRole('button', { name: 'Keep the entry' }))

    await waitFor(() => expect(sent).toEqual([{ url: '/v1/holdings/manual', body: { confirm: true, stock_id: '2330', quantity: 2000, average_cost: 98.1 } }]))
  })

  it('shows the server’s refusal of an unlisted stock at the form, and keeps the form open', async () => {
    const refusal = { detail: [{ loc: ['body', 'stock_id'], msg: 'Not a listed stock: 2317', type: 'unlisted_stock', input: '2317' }] }
    serve(() => json(NOTHING_HELD), () => json(refusal, 422))
    const user = userEvent.setup()
    open([{ stockId: '2317', name: '鴻海' }])

    await user.click(await screen.findByRole('button', { name: 'Enter 鴻海 as a holding' }))
    const form = within(await screen.findByRole('dialog', { name: 'Enter a holding' }))
    await user.type(form.getByLabelText('Shares'), '1000')
    await user.type(form.getByLabelText('Average cost per share (NT$)'), '100')
    await user.click(form.getByRole('button', { name: 'Keep the entry' }))

    expect(await form.findByText('2317 is not in the listing, so it was not kept.')).toBeVisible()
  })

  it('says the listing is unavailable when the server cannot check the stock', async () => {
    serve(() => json(NOTHING_HELD), () => json({ detail: 'The listing is unavailable.', code: 'listing_unavailable' }, 503))
    const user = userEvent.setup()
    open([{ stockId: '2317', name: '鴻海' }])

    await user.click(await screen.findByRole('button', { name: 'Enter 鴻海 as a holding' }))
    const form = within(await screen.findByRole('dialog', { name: 'Enter a holding' }))
    await user.type(form.getByLabelText('Shares'), '1000')
    await user.type(form.getByLabelText('Average cost per share (NT$)'), '100')
    await user.click(form.getByRole('button', { name: 'Keep the entry' }))

    expect(await form.findByText('Not kept. The list of stocks is unavailable right now. Try again later.')).toBeVisible()
    expect(form.queryByText(/The listing is unavailable\./), 'never the server’s own sentence').not.toBeInTheDocument()
  })

  it('offers a change and a removal on a hand-entered row only, and removes after a yes', async () => {
    const { sent } = serve(() => json(MIXED))
    const user = userEvent.setup()
    open()

    const [broker, , byHand] = await rows()
    expect(within(broker!).queryByRole('button')).not.toBeInTheDocument()

    await user.click(within(byHand!).getByRole('button', { name: 'Entry of 台積電' }))
    await user.click(await screen.findByRole('menuitem', { name: 'Change the entry' }))
    const form = within(await screen.findByRole('dialog', { name: 'Change the entry' }))
    expect(form.getByLabelText('Shares')).toHaveValue('37')
    expect(form.getByLabelText('Average cost per share (NT$)')).toHaveValue('550')
    expect(form.getByLabelText('Day bought (optional)')).toHaveValue('2026-03-02')
    expect(form.queryByRole('button', { name: /Choose/ }), 'a change keeps its stock').not.toBeInTheDocument()
    await user.click(form.getByRole('button', { name: 'Cancel' }))

    await user.click(within(byHand!).getByRole('button', { name: 'Entry of 台積電' }))
    await user.click(await screen.findByRole('menuitem', { name: 'Remove the entry' }))
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Remove the entry' }))

    await waitFor(() => expect(sent).toEqual([{ url: '/v1/holdings/manual/remove', body: { confirm: true, stock_id: '2330' } }]))
  })
})
