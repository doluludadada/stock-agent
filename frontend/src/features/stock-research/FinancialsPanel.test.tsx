import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { initI18n } from '@/i18n'
import type { StockFinancials } from './api'
import { FinancialsPanel } from './FinancialsPanel'

const quarter = (quarterOfYear: number, revenue: number, grossProfit: number | null) => ({
  quarter: { year: 2026, quarter: quarterOfYear },
  revenue,
  gross_profit: grossProfit,
  operating_income: 3_100_000,
  net_income: 2_600_000,
  eps: 5.47,
  total_assets: 158_000_000,
  total_liabilities: 61_000_000,
  equity: 95_000_000,
  book_value_per_share: null,
})

const month = {
  stock_id: '1215',
  year: 2026,
  month: 9,
  market: 'twse',
  served_date: '2026-10-12',
  company_name: 'Charoen Pokphand',
  industry: 'Food',
  revenue: 2_450_000,
  previous_month_revenue: 2_330_000,
  last_year_revenue: 2_510_000,
  month_over_month_percent: 5.15,
  year_over_year_percent: -2.39,
  cumulative_revenue: 21_866_426,
  last_year_cumulative_revenue: 21_000_000,
  cumulative_year_over_year_percent: 4.12,
  note: '',
} satisfies StockFinancials['monthly_revenues'][number]

function renderFinancials(financials: StockFinancials) {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(financials), { status: 200, headers: { 'Content-Type': 'application/json' } })))
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <FinancialsPanel stockId="1215" />
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

describe('a stock’s financials', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('read each archived quarter newest first, a figure the format does not report as a dash, and the latest month with its changes', async () => {
    renderFinancials({ stock_id: '1215', quarters: [quarter(2, 14_000_000, 2_000_000), quarter(3, 21_866_426, null)], monthly_revenues: [month] })

    const table = await screen.findByRole('table', { name: 'Quarterly figures' })
    expect(within(table).getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual(['Figure', 'Q3 2026', 'Q2 2026'])
    const row = (name: string) => within(table).getByRole('row', { name: new RegExp(`^${name}`) }).textContent
    expect(row('Revenue')).toBe('Revenue21.9B14B')
    expect(row('Gross profit')).toBe('Gross profit—2B')
    expect(row('EPS')).toBe('EPS (TWD)5.475.47')
    expect(row('Book value per share')).toBe('Book value per share (TWD)——')

    const latest = screen.getByRole('region', { name: 'Revenue of September 2026' })
    expect(within(latest).getByText('2.5B')).toBeInTheDocument()
    expect(within(latest).getByText('+5.15%')).toHaveClass('text-up')
    expect(within(latest).getByText('-2.39%')).toHaveClass('text-down')
  })

  it('say so when the archive holds nothing of the stock', async () => {
    renderFinancials({ stock_id: '1215', quarters: [], monthly_revenues: [] })

    expect(await screen.findByText('No financials archived yet')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })
})
