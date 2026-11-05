import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { initI18n } from '@/i18n'
import { session } from '@/shared/api'
import { ValuationPage } from './ValuationPage'

const scenario = (targetPe: number, fairPrice: number) => ({ target_pe: targetPe, fair_price: fairPrice, undervaluation: 0.5 })
const report = {
  valuation: {
    stock: { stock_id: '2330', name: 'TSMC', industry: 'Semiconductors', market: 'twse' },
    close: { close: 1000, ts: '2026-11-02T13:30:00+08:00' },
    close_is_fresh: true,
    eps: { value: 100, period_label: '2026Q3', kind: 'trailing_twelve_months' },
    current_pe: { value: 10 },
    warnings: [],
  },
  target_pe: 15,
  fair_value: { conservative: scenario(12, 1200), base: scenario(15, 1500), optimistic: scenario(18, 1800) },
  undervaluation: 0.5,
}

function backend(answered: Promise<void> = Promise.resolve()) {
  const explained: unknown[] = []
  const answers = { sent: 0 }
  const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  const fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input)
    if (url.startsWith('/v1/valuation/market')) return json({ last_closed_session: '2026-11-02', valued_stocks: 900, median_pe: null, source_warnings: [] })
    if (url.startsWith('/v1/valuation/scan')) {
      const targetPe = Number(new URL(url, 'http://app').searchParams.get('target_pe'))
      return json({
        criteria: { target_pe: targetPe, min_undervaluation: 0.3 },
        market: { last_closed_session: '2026-11-02', valued_stocks: 900, median_pe: null, source_warnings: [] },
        survivors: [report],
        eliminated: {},
        explanation_candidates: ['2330'],
        technical_strategy_id: new URL(url, 'http://app').searchParams.get('technical') === 'true' ? 'balanced' : null,
        technical_failures: {},
      })
    }
    if (url === '/v1/valuation/explanation') {
      explained.push(JSON.parse(String(init?.body)))
      await answered
      answers.sent += 1
      return json({ stock_id: '2330', sections: [{ title: 'Why', lines: ['Earnings grew.'] }] })
    }
    return new Response('{}', { status: 404 })
  })
  return { fetch, explained, answers }
}

function renderPage() {
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <ValuationPage />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
}

describe('the undervalued scan', () => {
  afterEach(() => {
    session.lock('owner')
    vi.unstubAllGlobals()
  })

  it('asks the AI about the P/E the scan used, even after the field was edited', async () => {
    const server = backend()
    vi.stubGlobal('fetch', server.fetch)
    session.unlock('owner', 'owner-token')
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByRole('tab', { name: 'Undervalued scan' }))
    await user.click(screen.getByRole('button', { name: 'Scan' }))
    await screen.findByRole('link', { name: /TSMC/ })
    const pe = screen.getByLabelText('Target P/E')
    await user.clear(pe)
    await user.type(pe, '25')
    await user.click(screen.getByRole('button', { name: 'Explain with AI' }))
    await user.click(await screen.findByRole('button', { name: 'Make the AI call' }))

    expect(await screen.findByText('Earnings grew.')).toBeInTheDocument()
    expect(server.explained).toEqual([{ confirm: true, stock_id: '2330', target_pe: 15 }])
  })

  it('keeps a paid explanation through a tab switch and the technical step, and asks for it once', async () => {
    let answer = () => {}
    const server = backend(new Promise<void>((resolve) => (answer = resolve)))
    vi.stubGlobal('fetch', server.fetch)
    session.unlock('owner', 'owner-token')
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByRole('tab', { name: 'Undervalued scan' }))
    await user.click(screen.getByRole('button', { name: 'Scan' }))
    await user.click(await screen.findByRole('button', { name: 'Explain with AI' }))
    await user.click(await screen.findByRole('button', { name: 'Make the AI call' }))
    expect(screen.getByRole('button', { name: /Confirm the 1 survivors/ })).toBeDisabled()

    await user.click(screen.getByRole('tab', { name: 'Specific stocks' }))
    await user.click(screen.getByRole('tab', { name: 'Undervalued scan' }))
    await user.click(screen.getByRole('button', { name: 'Scan' }))
    expect(await screen.findByRole('button', { name: 'The AI is writing…' })).toBeDisabled()
    await user.click(screen.getByRole('tab', { name: 'Specific stocks' }))
    answer()
    await waitFor(() => expect(server.answers.sent).toBe(1))
    await user.click(screen.getByRole('tab', { name: 'Undervalued scan' }))
    await user.click(screen.getByRole('button', { name: 'Scan' }))
    expect(await screen.findByText('Earnings grew.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Confirm the 1 survivors/ }))
    await screen.findByText(/Confirmed with the strategy in use/)
    expect(screen.getByText('Earnings grew.')).toBeInTheDocument()
    expect(server.explained).toHaveLength(1)
  })
})
