import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { initI18n } from '@/i18n'
import { CommandGroup, CommandItem } from './command'
import { StockSearchCommand } from './stock-picker'

const listed = [{ stock_id: '2330', name: 'TSMC', market: 'twse', today: null }]

describe('the stock search', () => {
  beforeAll(() => {
    Element.prototype.scrollIntoView = () => undefined
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
  })
  afterAll(() => vi.unstubAllGlobals())

  it('opens the first match on Enter, not the item that was selected before the matches arrived', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(listed), { status: 200, headers: { 'Content-Type': 'application/json' } })))
    const opened: string[] = []
    const user = userEvent.setup()
    render(
      <I18nextProvider i18n={initI18n('en')}>
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <StockSearchCommand onSelect={(stockId) => opened.push(stockId)}>
            <CommandGroup heading="Pages">
              <CommandItem value="page:strategies" onSelect={() => opened.push('page:strategies')}>
                Strategy library
              </CommandItem>
            </CommandGroup>
          </StockSearchCommand>
        </QueryClientProvider>
      </I18nextProvider>,
    )

    await user.type(screen.getByRole('combobox'), '2330')
    await screen.findByRole('option', { name: /TSMC/ })
    await user.keyboard('{Enter}')

    expect(opened).toEqual(['2330'])
  })

  it('opens nothing on Enter right after a new code is typed, until the matches for that code arrive', async () => {
    const stock = (stockId: string, name: string) => ({ stock_id: stockId, name, market: 'twse', today: null })
    const rows: Record<string, unknown[]> = { '2330': [stock('2330', 'TSMC')], '2317': [stock('2317', 'Hon Hai')] }
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const query = new URL(url, 'http://localhost').searchParams.get('query') ?? ''
      return new Response(JSON.stringify(rows[query] ?? []), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }))
    const opened: string[] = []
    const user = userEvent.setup()
    render(
      <I18nextProvider i18n={initI18n('en')}>
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <StockSearchCommand onSelect={(stockId) => opened.push(stockId)} />
        </QueryClientProvider>
      </I18nextProvider>,
    )
    const input = screen.getByRole('combobox')

    await user.type(input, '2330')
    await screen.findByRole('option', { name: /TSMC/ })
    await user.clear(input)
    await user.type(input, '2317{Enter}')
    expect(opened).toEqual([])

    await screen.findByRole('option', { name: /Hon Hai/ })
    await user.keyboard('{Enter}')
    expect(opened).toEqual(['2317'])
  })
})
