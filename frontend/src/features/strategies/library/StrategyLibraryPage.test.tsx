import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { I18nextProvider } from 'react-i18next'
import { MemoryRouter } from 'react-router'
import { builtInJson } from '@/features/strategies/model/built-ins.test-support'
import { initI18n } from '@/i18n'
import { session } from '@/shared/api'
import { PERSONAL_SITE } from '@/test/audiences'
import { TEST_USER } from '@/test/users'
import { StrategyLibraryPage } from './StrategyLibraryPage'

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })

const BUILT_INS = [builtInJson('conservative'), builtInJson('balanced'), builtInJson('aggressive')]
const MINE = { ...builtInJson('balanced'), strategy_id: 'stg_mine', name: 'Mine' }

/** The library of a user who has the first read's copies of the built-ins and one strategy of their own. */
async function renderLibrary(active: string) {
  const saved: unknown[] = []
  const settings = { active_strategy_id: active, strategies: [...BUILT_INS, MINE], revision: 1 }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/v1/market/audience') return json(PERSONAL_SITE)
      if (url === '/v1/technical-settings/built-in-strategies') return json(BUILT_INS)
      if (url === '/v1/technical-settings' && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as { settings: typeof settings }
        saved.push(body.settings)
        return json({ ...body.settings, revision: 2 })
      }
      if (url === '/v1/technical-settings') return json(settings)
      return json([])
    }),
  )
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
  await screen.findByRole('radiogroup', { name: 'Strategy in use' })
  return saved
}

describe('the strategy library', { timeout: 20_000 }, () => {
  afterEach(() => {
    session.signOut()
    vi.unstubAllGlobals()
  })

  it('picks the one strategy in use among the built-ins, and lists only the user’s own below', async () => {
    const saved = await renderLibrary('balanced')

    const choice = screen.getByRole('radiogroup', { name: 'Strategy in use' })
    expect(within(choice).getAllByRole('radio').map((option) => option.textContent)).toEqual(['Conservative', 'Balanced', 'Aggressive'])
    expect(within(choice).getByRole('radio', { name: 'Balanced' })).toHaveAttribute('aria-checked', 'true')
    const mine = screen.getByRole('list')
    expect(within(mine).getAllByRole('listitem').map((row) => row.getAttribute('aria-label'))).toEqual(['Mine'])
    expect(screen.queryByText(/Social Buzz/)).not.toBeInTheDocument()

    fireEvent.click(within(choice).getByRole('radio', { name: 'Aggressive' }))

    await waitFor(() => expect(saved).toEqual([expect.objectContaining({ active_strategy_id: 'aggressive', revision: 1 })]))
  })

  it('says which of the user’s own strategies is in use, and offers each one to use, edit, duplicate or delete', async () => {
    await renderLibrary('stg_mine')

    expect(within(screen.getByRole('radiogroup', { name: 'Strategy in use' })).queryByRole('radio', { checked: true })).toBeNull()
    expect(screen.getByText('Every workflow uses your strategy “Mine”.')).toBeInTheDocument()
    const row = screen.getByRole('listitem', { name: 'Mine' })
    expect(within(row).getByText('In use')).toBeInTheDocument()
    expect(within(row).queryByRole('button', { name: 'Use' })).not.toBeInTheDocument()
    expect(within(row).getByRole('link', { name: 'Edit' })).toHaveAttribute('href', '/strategies/stg_mine/edit')
    expect(within(row).getByRole('link', { name: 'Copy Mine' })).toHaveAttribute('href', '/strategies/new?from=stg_mine')
    expect(within(row).getByRole('button', { name: /^Delete Mine: / })).toBeDisabled()
  })
})
