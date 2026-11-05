import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { builtInJson } from '@/features/strategies/model/built-ins.test-support'
import { initI18n } from '@/i18n'
import { session } from '@/shared/api'
import { NewStrategyRoute, StrategyLibraryRoute } from './router/routes/strategies'

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })

describe('copying an official strategy', () => {
  beforeAll(() => {
    Element.prototype.scrollIntoView = () => undefined
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
  })
  afterAll(() => vi.unstubAllGlobals())
  afterEach(() => session.lock('owner'))

  it('copies the official strategy, not the owner strategy that kept its id', async () => {
    const official = builtInJson('balanced')
    const edited = { ...official, name: 'My balanced', rules: official.rules.slice(0, 1) }
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url === '/v1/technical-settings/built-in-strategies') return json([official])
      if (url === '/v1/technical-settings') return json({ active_strategy_id: 'balanced', buzz_strategy_id: 'balanced', strategies: [edited], revision: 1 })
      return json([])
    }))
    session.unlock('owner', 'owner-token')
    const router = createMemoryRouter(
      [
        { path: '/strategies', element: <StrategyLibraryRoute /> },
        { path: '/strategies/new', element: <NewStrategyRoute /> },
      ],
      { initialEntries: ['/strategies'] },
    )
    render(
      <I18nextProvider i18n={initI18n('en')}>
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </I18nextProvider>,
    )

    await screen.findByRole('link', { name: 'Copy My balanced' })
    await userEvent.setup().click(screen.getByRole('link', { name: 'Copy Balanced' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Balanced copy' })).toBeInTheDocument()
  }, 20_000)
})
