import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { builtInJson } from '@/features/strategies/model/built-ins.test-support'
import { initI18n } from '@/i18n'
import { session, type Audience } from '@/shared/api'
import { PERSONAL_SITE, PUBLIC_SITE } from '@/test/audiences'
import { TEST_USER } from '@/test/users'
import { StrategyLibraryPage } from './StrategyLibraryPage'

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })

/** The library of a user with one strategy of their own, in use, while Social Buzz runs a built-in. */
async function renderLibrary(site: Audience) {
  const official = builtInJson('balanced')
  const mine = { ...official, strategy_id: 'stg_mine', name: 'Mine' }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url === '/v1/market/audience') return json(site)
    if (url === '/v1/technical-settings/built-in-strategies') return json([official])
    if (url === '/v1/technical-settings') return json({ active_strategy_id: 'stg_mine', buzz_strategy_id: 'balanced', strategies: [mine], revision: 1 })
    return json([])
  }))
  session.signIn(TEST_USER)
  render(
    <I18nextProvider i18n={initI18n('en')}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <StrategyLibraryPage />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  )
  await screen.findByRole('article', { name: 'Mine' })
}

describe('the strategy library', { timeout: 20_000 }, () => {
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('offers a strategy for Social Buzz on the owner’s site', async () => {
    await renderLibrary(PERSONAL_SITE)

    expect(await screen.findByRole('button', { name: 'Use for Buzz' })).toBeInTheDocument()
    expect(screen.getByText(/Social Buzz uses its own/)).toBeInTheDocument()
  })

  it('offers no Social Buzz choice on a site without realtime quotes, and says which runs use the strategy', async () => {
    await renderLibrary(PUBLIC_SITE)

    expect(await screen.findByText('Full Cycle and specific stocks use the strategy in use.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Use for Buzz' })).not.toBeInTheDocument()
  })
})
